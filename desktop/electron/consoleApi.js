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

export async function consoleFetch(path, { method = "GET", body, connection } = {}) {
  const conn = connection ?? requireConnection();
  const res = await fetch(`${conn.consoleUrl}${path}`, {
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
export function putStream(url, body, total, onProgress) {
  return new Promise((resolve, reject) => {
    const target = new URL(url);
    // http:// only ever appears in tests (a local server); every real
    // presigned URL is https.
    const request = target.protocol === "http:" ? httpRequest : httpsRequest;
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
          if (res.statusCode >= 200 && res.statusCode < 300) return resolve({ total });
          const err = new Error(`upload failed (HTTP ${res.statusCode})`);
          err.status = res.statusCode;
          err.body = Buffer.concat(chunks).toString("utf8").slice(0, 500);
          reject(err);
        });
      },
    );
    req.on("error", reject);

    let sent = 0;
    body.on("data", (chunk) => {
      sent += chunk.length;
      onProgress?.(sent, total);
    });
    body.on("error", (err) => {
      req.destroy();
      reject(err);
    });
    body.pipe(req);
  });
}

// Streams one file to a presigned PUT URL.
export function uploadFile(url, filePath, onProgress) {
  const total = statSync(filePath).size;
  return putStream(url, createReadStream(filePath), total, onProgress);
}
