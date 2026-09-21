// The deadline is what stops one stuck step from freezing the venue agent's
// command queue and heartbeat (2026-09-21). Real timers and real sockets, in
// milliseconds -- a mocked clock would prove the mechanism against a
// simulation of the hang rather than the hang.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { Readable } from "node:stream";
import { test } from "node:test";
import { DeadlineError, withDeadline } from "./deadline.js";
import { putStream } from "./consoleApi.js";

test("a step that finishes in time returns its own result", async () => {
  assert.equal(await withDeadline(Promise.resolve(42), 200, "quick"), 42);
});

test("a step that fails in time still throws its own error, not a deadline", async () => {
  await assert.rejects(withDeadline(Promise.reject(new Error("boom")), 200, "fails"), /^Error: boom$/);
});

test("a step that never finishes is given up on, and says which one", async () => {
  const started = Date.now();
  await assert.rejects(
    withDeadline(new Promise(() => {}), 50, "grab_calibration_snapshot"),
    (err) => err instanceof DeadlineError && /grab_calibration_snapshot did not finish/.test(err.message),
  );
  assert.ok(Date.now() - started < 1000);
});

test("an abandoned step that fails later does not crash the process", async () => {
  let rejectLater;
  const slow = new Promise((_, reject) => { rejectLater = reject; });
  await assert.rejects(withDeadline(slow, 20, "slow"), DeadlineError);
  rejectLater(new Error("late failure")); // would be an unhandled rejection if not swallowed
  await new Promise((r) => setTimeout(r, 30));
});

// The upload half of the same story: the stall that most plausibly froze the
// snapshot command was a PUT that stopped moving and never errored.
async function withSilentServer(run) {
  const server = createServer(() => { /* accept the request, never read it or respond */ });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    return await run(`http://127.0.0.1:${server.address().port}/x`);
  } finally {
    server.closeAllConnections();
    server.close();
  }
}

test("an upload that stops moving is torn down instead of hanging", async () => {
  await withSilentServer(async (url) => {
    // A body bigger than the socket buffers, so the write really does block
    // once the server stops reading -- the shape of a stalled uplink.
    const total = 64 * 1024 * 1024;
    const body = Readable.from((function* () { for (let i = 0; i < 64; i++) yield Buffer.alloc(1024 * 1024); })());
    const started = Date.now();
    await assert.rejects(putStream(url, body, total, undefined, undefined, 300), /upload stalled/);
    assert.ok(Date.now() - started < 5000, "should give up on the idle limit");
  });
});

test("an upload that keeps moving is not cut off by the idle limit", async () => {
  // Paired with the stall test: a limit that also killed slow-but-alive
  // transfers would pass the test above and break every real recording upload.
  const server = createServer((req, res) => {
    req.on("data", () => {});
    req.on("end", () => { res.writeHead(200); res.end("ok"); });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const chunks = 6;
    const body = Readable.from((async function* () {
      for (let i = 0; i < chunks; i++) {
        await new Promise((r) => setTimeout(r, 100)); // 600ms total, well past a 300ms idle limit
        yield Buffer.alloc(1024);
      }
    })());
    const result = await putStream(`http://127.0.0.1:${server.address().port}/x`, body, chunks * 1024, undefined, undefined, 300);
    assert.equal(result.total, chunks * 1024);
  } finally {
    server.closeAllConnections();
    server.close();
  }
});
