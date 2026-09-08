// Two things are covered here, deliberately paired (CLAUDE.md, "a test
// proving X must sit beside one proving the feature still works"):
//
//   1. The throughput maths, which is where a benchmark quietly lies --
//      an implausibly high number from measuring the socket buffer, or a
//      low one from counting the TLS handshake as transfer time.
//   2. That putStream(), extracted from uploadFile() so the benchmark and
//      a real recording upload share one transport, still sends a real
//      Content-Length and no chunked encoding -- the property a presigned
//      R2 PUT rejects outright, and the reason that function exists at
//      all. uploadFile() is exercised through the same server, because
//      the refactor is only safe if the path that carries actual
//      recordings still works.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createServer } from "node:http";
import { mkdtempSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  CAMERA_MBPS,
  MIN_USEFUL_MS,
  TEST_SIZES,
  UNSTABLE_SPREAD,
  WARMUP_MS,
  median,
  nextTestSize,
  sessionUploadMinutes,
  steadyStateMbps,
  syntheticBody,
  verdict,
} from "./bandwidth.js";
import { putStream, uploadFile } from "./consoleApi.js";

test("steady-state throughput ignores the warmup window", () => {
  const startedAt = 1_000_000;
  // 10 MB total. The first 2s "sent" 6 MB into a socket buffer at an
  // impossible rate; the real wire rate is the 4 MB that follow over 8s.
  const samples = [
    { at: startedAt + 100, sent: 6_000_000 },
    { at: startedAt + WARMUP_MS + 10, sent: 6_500_000 },
    { at: startedAt + 6000, sent: 9_000_000 },
  ];
  const endedAt = startedAt + 10_000;
  const mbps = steadyStateMbps(samples, 10_000_000, startedAt, endedAt);

  // (10.0 - 6.5) MB over (10000 - 2010) ms = 3.5 MB / 7.99s ≈ 3.5 Mbps.
  assert.ok(mbps > 3.4 && mbps < 3.6, `expected ~3.5 Mbps, got ${mbps}`);
  // The naive whole-transfer average would have claimed 8 Mbps.
  assert.ok(mbps < (10_000_000 * 8) / 10_000 / 1000);
});

test("a run too short to have a steady state falls back to the overall average", () => {
  const startedAt = 1_000_000;
  const samples = [{ at: startedAt + 200, sent: 1_000_000 }];
  const mbps = steadyStateMbps(samples, 1_000_000, startedAt, startedAt + 1000);
  assert.equal(mbps, 8); // 1 MB in 1s
});

test("a warmup sample at the very end falls back rather than reporting zero", () => {
  const startedAt = 1_000_000;
  // Every byte was handed over before the warmup mark; the only sample
  // past it carries the full total, so the steady-state window has no
  // bytes left in it.
  const samples = [{ at: startedAt + WARMUP_MS + 5, sent: 4_000_000 }];
  const mbps = steadyStateMbps(samples, 4_000_000, startedAt, startedAt + 4000);
  assert.equal(mbps, 8); // 4 MB in 4s, not 0
});

test("the size ladder climbs only while runs are too short to trust", () => {
  assert.equal(nextTestSize(TEST_SIZES[0], MIN_USEFUL_MS - 1), TEST_SIZES[1]);
  assert.equal(nextTestSize(TEST_SIZES[1], 500), TEST_SIZES[2]);
  // Long enough: stop, whatever rung we're on.
  assert.equal(nextTestSize(TEST_SIZES[0], MIN_USEFUL_MS), null);
  // Top of the ladder: stop even if it was quick.
  assert.equal(nextTestSize(TEST_SIZES[2], 100), null);
});

test("session estimates and verdicts are in venue terms", () => {
  // One camera, 2 hours, at exactly the rate a camera records: the
  // upload takes as long as the session did, which is the definition of
  // never catching up.
  assert.equal(Math.round(sessionUploadMinutes(CAMERA_MBPS, 2, 1)), 120);
  assert.equal(verdict(CAMERA_MBPS - 0.1, 1), "below");
  // Two cameras double the floor.
  assert.equal(verdict(CAMERA_MBPS + 0.1, 2), "below");
  assert.equal(verdict(10, 1), "slow"); // 2h session ≈ 36 min
  assert.equal(verdict(25, 1), "ok"); // ≈ 14 min
});

test("the median, not the mean, carries the repeated samples", () => {
  // The real reason this is a median: one pathological run shouldn't drag
  // the answer. Measured against real R2 on 2026-09-08, consecutive
  // 8 MB PUTs came back 28.8, 3.4 and 29.0 Mbps.
  assert.equal(median([28.8, 3.4, 29.0]), 28.8);
  assert.ok(median([28.8, 3.4, 29.0]) > (28.8 + 3.4 + 29.0) / 3, "the mean would report ~20");
  assert.equal(median([4, 8]), 6);
  assert.equal(median([7]), 7);
});

test("a spread that wide is reported as unstable, not averaged away", () => {
  const samples = [28.8, 3.4, 29.0];
  const spread = Math.max(...samples) / Math.min(...samples);
  assert.ok(spread > UNSTABLE_SPREAD, "8.5x apart has to trip the unstable flag");
  // A steady link must not trip it.
  assert.ok(31 / 27 < UNSTABLE_SPREAD);
});

test("the synthetic body is exactly the requested size", async () => {
  const bytes = 700_000; // deliberately not a multiple of the 256 KB block
  let seen = 0;
  for await (const chunk of syntheticBody(bytes)) seen += chunk.length;
  assert.equal(seen, bytes);
});

async function withServer(handler, run) {
  const received = [];
  const server = createServer((req, res) => {
    let size = 0;
    req.on("data", (c) => (size += c.length));
    req.on("end", () => {
      received.push({ headers: req.headers, size });
      handler?.(req, res);
      res.writeHead(200);
      res.end("ok");
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${server.address().port}/presigned-lookalike`;
  try {
    return await run(url, received);
  } finally {
    server.close();
  }
}

test("putStream sends a real Content-Length, not chunked encoding", async () => {
  await withServer(null, async (url, received) => {
    const total = 300_000;
    const progress = [];
    await putStream(url, syntheticBody(total), total, (sent) => progress.push(sent));

    assert.equal(received.length, 1);
    assert.equal(received[0].size, total);
    assert.equal(received[0].headers["content-length"], String(total));
    assert.equal(
      received[0].headers["transfer-encoding"],
      undefined,
      "chunked encoding is exactly what a presigned R2 PUT rejects",
    );
    assert.ok(progress.length > 0, "no progress reported, so the page would show a dead bar");
    assert.equal(progress.at(-1), total);
  });
});

test("uploadFile still uploads a real file through that same request", async () => {
  await withServer(null, async (url, received) => {
    const dir = mkdtempSync(path.join(os.tmpdir(), "bwtest-"));
    const file = path.join(dir, "segment.mkv");
    const body = Buffer.alloc(120_000, 7);
    writeFileSync(file, body);

    const result = await uploadFile(url, file);
    assert.equal(result.total, body.length);
    assert.equal(received[0].size, body.length);
    assert.equal(received[0].headers["content-length"], String(body.length));
  });
});

test("an HTTP error is surfaced, not swallowed as success", async () => {
  const server = createServer((req, res) => {
    req.resume();
    req.on("end", () => {
      res.writeHead(403);
      res.end("SignatureDoesNotMatch");
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${server.address().port}/expired`;
  try {
    await assert.rejects(() => putStream(url, syntheticBody(1000), 1000), /403/);
  } finally {
    server.close();
  }
});
