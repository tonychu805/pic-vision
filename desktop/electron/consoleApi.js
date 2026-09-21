// Authenticated calls to the cloud console, plus the presigned-URL upload
// used to hand recordings over to it (ADR-084).
//
// Everything the agent sends goes out through here so there's one place
// that knows the console URL and the bearer token -- and one place to look
// when a venue reports "it can't reach the cloud".
import { createReadStream, statSync } from "node:fs";
import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { getCloudConnection } from "./cloud.js";

export function requireConnection() {
  const connection = getCloudConnection();
  if (!connection?.apiToken) {
    throw new Error("This device isn't connected to the cloud console yet");
  }
  return connection;
}

// Every call to the console is a small JSON round trip; one that has not
// answered in this long is not going to. Without a limit, fetch() waits on a
// dead connection for minutes, and the command pass -- which runs one command
// at a time -- waits with it (see deadline.js for what that cost).
export const CONSOLE_FETCH_TIMEOUT_MS = 30_000;

// How long an upload may go without a single byte moving in either
// direction before it is treated as dead. An idle limit, not a total one: a
// recording segment is hundreds of MB and legitimately takes as long as the
// venue's uplink needs, but a transfer that has stopped entirely never
// recovers on its own.
export const UPLOAD_IDLE_TIMEOUT_MS = 60_000;

export async function consoleFetch(path, { method = "GET", body, connection, timeoutMs = CONSOLE_FETCH_TIMEOUT_MS } = {}) {
  const conn = connection ?? requireConnection();
  const res = await fetch(`${conn.consoleUrl}${path}`, {
    signal: AbortSignal.timeout(timeoutMs),
    method,
    headers: {
      Authorization: `Bearer ${conn.apiToken}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(payload.error || `the cloud console returned HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return payload;
}

// Streams `total` bytes from any readable to a presigned PUT URL, and
// resolves once the endpoint has acknowledged them.
//
// Deliberately node:https rather than fetch(): passing a stream to fetch()
// sends `Transfer-Encoding: chunked`, which S3-compatible endpoints (R2
// included) reject on a presigned PUT -- they need a real Content-Length,
// and the signature is computed against a request that has one. Streaming
// (rather than reading into a Buffer) matters because these are recording
// segments -- hundreds of MB each, occasionally more.
//
// Split out of uploadFile() (2026-09-08) so the Diagnostics tab's upload
// benchmark measures THIS request, byte for byte, instead of a lookalike
// written next to it -- a benchmark whose transport differs from the real
// one measures the wrong thing, and the Content-Length lesson above is
// exactly the kind of difference that would go unnoticed.
// `signal` (optional) aborts a transfer already in flight. Added 2026-09-19
// for Cancel: a segment is hundreds of MB, so "stop at the next segment
// boundary" is not stopping -- the request itself has to be torn down, or
// the venue keeps paying for bytes nobody wants. The socket is destroyed
// rather than left to drain, which is the point.
export function putStream(url, body, total, onProgress, signal, idleTimeoutMs = UPLOAD_IDLE_TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    const target = new URL(url);
    // http:// only ever appears in tests (a local server); every real
    // presigned URL is https.
    const request = target.protocol === "http:" ? httpRequest : httpsRequest;

    // Destroying a request makes it emit its own ECONNRESET, and the body
    // stream may error too, so every path settles through these: the first
    // outcome wins and the rest are ignored. Without that an abort would
    // report a socket error instead of a cancellation.
    let settled = false;
    const settle = (fn) => (value) => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener("abort", onAbort);
      fn(value);
    };
    const succeed = settle(resolve);
    const fail = settle(reject);

    const req = request(
      {
        protocol: target.protocol,
        hostname: target.hostname,
        port: target.port || 443,
        path: `${target.pathname}${target.search}`,
        method: "PUT",
        headers: { "Content-Length": total, "Content-Type": "application/octet-stream" },
      },
      (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          if (res.statusCode >= 200 && res.statusCode < 300) return succeed({ total });
          const err = new Error(`upload failed (HTTP ${res.statusCode})`);
          err.status = res.statusCode;
          err.body = Buffer.concat(chunks).toString("utf8").slice(0, 500);
          fail(err);
        });
      },
    );
    req.on("error", fail);

    // Idle, not total -- see UPLOAD_IDLE_TIMEOUT_MS. Destroying the request
    // emits its own error, which `fail` reports; the body is torn down too so
    // a file handle isn't left open on a transfer nobody is waiting for.
    req.setTimeout(idleTimeoutMs, () => {
      body.destroy();
      req.destroy(new Error(`upload stalled: no data moved for ${Math.round(idleTimeoutMs / 1000)}s`));
    });

    // Marked so a caller can tell a deliberate stop from a transport
    // failure, and doesn't retry it or report it as a failed upload.
    const onAbort = () => {
      body.destroy();
      req.destroy();
      fail(Object.assign(new Error("upload cancelled"), { aborted: true }));
    };

    let sent = 0;
    body.on("data", (chunk) => {
      sent += chunk.length;
      onProgress?.(sent, total);
    });
    body.on("error", (err) => {
      req.destroy();
      fail(err);
    });

    if (signal?.aborted) return onAbort();
    signal?.addEventListener("abort", onAbort, { once: true });
    body.pipe(req);
  });
}

// Streams one file to a presigned PUT URL.
export function uploadFile(url, filePath, onProgress, signal) {
  const total = statSync(filePath).size;
  return putStream(url, createReadStream(filePath), total, onProgress, signal);
}
