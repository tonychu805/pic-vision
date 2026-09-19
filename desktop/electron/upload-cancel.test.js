// Cancel has to stop the bytes, not just the bookkeeping.
//
// The bug this pins (2026-09-19): pressing Cancel during a "Send to cloud"
// upload told the console, which cancelled the job row correctly, and then
// the agent uploaded every remaining segment anyway -- gigabytes, over a
// venue's uplink, after the operator asked it to stop -- and finally
// reported "upload failed" when `complete` 409'd against the now-cancelled
// job. The operator's description was that it "stops after a while": that
// while was the whole rest of the upload.
//
// A segment is hundreds of MB, so stopping at the next segment boundary is
// not stopping. These tests are about the request already in flight.
//
// Paired, per CLAUDE.md: a test that the stop works sits beside one that a
// normal upload still completes with the same plumbing in place. Proving
// something no longer happens is not proof the feature still works.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createServer } from "node:http";
import { syntheticBody } from "./bandwidth.js";
import { putStream } from "./consoleApi.js";

// A server that accepts the first chunk and then stops reading, so the
// transfer stalls with the body only partly sent -- the state a real
// upload spends nearly all its time in, and the only state where Cancel
// actually matters.
async function withStalledServer(run) {
  let received = 0;
  let sawRequest = false;
  const server = createServer((req) => {
    sawRequest = true;
    req.on("data", (chunk) => {
      received += chunk.length;
      req.pause(); // stall here; never respond
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${server.address().port}/presigned-lookalike`;
  try {
    return await run(url, () => ({ received, sawRequest }));
  } finally {
    server.closeAllConnections?.();
    server.close();
  }
}

// A bounded timeout, because the regression this guards against does not
// fail loudly -- it hangs. With the abort wiring removed the stalled
// upload simply never settles, so without this the suite stops instead of
// reporting, which is a worse signal than a failed assertion.
test("aborting mid-transfer rejects as a cancellation, not a transport failure", { timeout: 15_000 }, async () => {
  await withStalledServer(async (url, state) => {
    const total = 40 * 1024 * 1024; // far more than can slip through before the stall
    const controller = new AbortController();

    let firstProgress;
    const upload = putStream(url, syntheticBody(total), total, (sent) => {
      firstProgress ??= sent;
      if (sent > 0) controller.abort();
    }, controller.signal);

    const err = await upload.then(
      () => { throw new Error("the upload resolved -- it was supposed to be cancelled"); },
      (e) => e,
    );

    // `aborted` is what stops uploadWithRetry from cheerfully restarting
    // the very transfer the operator just cancelled, and what tells
    // runCloudJob to write "cancelled" instead of "upload failed".
    assert.equal(err.aborted, true, `expected an abort, got: ${err.message}`);

    // Guards against the test passing vacuously: an abort that landed
    // before a single byte left would satisfy the assertion below without
    // proving anything about tearing down a transfer in flight.
    assert.ok(firstProgress > 0, "aborted before the upload had started, so this proves nothing");

    // The real assertion: the bytes stopped. Destroying the request has to
    // leave the server having seen only a fraction of the body -- if this
    // ever reads `total`, the upload ran to completion and Cancel is
    // decorative again.
    const { received } = state();
    assert.ok(received < total, `server received all ${total} bytes despite the abort`);
  });
});

test("a signal that never fires leaves a normal upload alone", async () => {
  // The paired half. An abort path that breaks ordinary uploads would be
  // worse than the bug it fixes.
  const received = [];
  const server = createServer((req, res) => {
    let size = 0;
    req.on("data", (c) => (size += c.length));
    req.on("end", () => {
      received.push(size);
      res.writeHead(200);
      res.end("ok");
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${server.address().port}/presigned-lookalike`;
  try {
    const total = 300_000;
    const controller = new AbortController();
    const result = await putStream(url, syntheticBody(total), total, null, controller.signal);
    assert.equal(result.total, total);
    assert.deepEqual(received, [total]);
  } finally {
    server.close();
  }
});

test("a signal already aborted never opens the connection at all", { timeout: 15_000 }, async () => {
  // Cancel landing between two segments: there is no request to tear down,
  // and the next one must not start. Cheaper than a socket, and the case
  // the old code walked straight past into the next segment.
  await withStalledServer(async (url, state) => {
    const controller = new AbortController();
    controller.abort();
    await assert.rejects(
      () => putStream(url, syntheticBody(1_000_000), 1_000_000, null, controller.signal),
      (err) => err.aborted === true,
    );
    assert.equal(state().sawRequest, false, "a cancelled upload still contacted the server");
  });
});
