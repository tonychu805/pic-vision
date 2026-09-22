// Concurrent uploads across different recordings/cameras were tested
// (2026-09-22) to slow each other down rather than add real throughput --
// a venue's uplink is one shared, often thin pipe (ADR-092: bimodal,
// roughly 3.5 vs. 30 Mbps), and the machine has nothing else to gain by
// racing them since it sits otherwise idle during an upload anyway.
// withUploadSlot() is the fix: a FIFO queue around the actual transfer,
// so a second camera's job still gets created and its status starts
// moving as soon as its turn at the wire comes up, rather than the whole
// upload phase being blocked behind the first job's entire pipeline.
//
// Own file, plain async functions rather than real uploads: the queuing
// behavior itself doesn't touch a file, a socket, or Electron, so nothing
// here needs the real uploadSegments()/consoleFetch() machinery to prove
// the ordering and error-isolation guarantees.
import assert from "node:assert/strict";
import { test } from "node:test";
import { withUploadSlot } from "./pipeline.js";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test("a second upload does not start until the first one finishes", async () => {
  const events = [];
  const first = withUploadSlot(async () => {
    events.push("first-start");
    await sleep(30);
    events.push("first-end");
  });
  const second = withUploadSlot(async () => {
    events.push("second-start");
  });
  await Promise.all([first, second]);
  assert.deepEqual(events, ["first-start", "first-end", "second-start"]);
});

test("their active windows never overlap, even with several queued at once", async () => {
  const active = { count: 0, maxSeen: 0 };
  async function upload() {
    active.count++;
    active.maxSeen = Math.max(active.maxSeen, active.count);
    await sleep(10);
    active.count--;
  }
  await Promise.all([1, 2, 3, 4, 5].map(() => withUploadSlot(upload)));
  assert.equal(active.maxSeen, 1, "at most one upload must be running its transfer at a time");
});

test("onWaiting fires only for a call that actually has to wait", async () => {
  const waited = [];
  const first = withUploadSlot(async () => sleep(20), () => waited.push("first"));
  const second = withUploadSlot(async () => {}, () => waited.push("second"));
  await Promise.all([first, second]);
  assert.deepEqual(waited, ["second"], "the first call found the queue empty and must not be told it waited");
});

test("a failed upload does not wedge every upload queued behind it", async () => {
  const events = [];
  const failing = withUploadSlot(async () => {
    events.push("failing-ran");
    throw new Error("upload failed");
  });
  const next = withUploadSlot(async () => {
    events.push("next-ran");
    return "ok";
  });
  await assert.rejects(failing, /upload failed/);
  assert.equal(await next, "ok");
  assert.deepEqual(events, ["failing-ran", "next-ran"]);
});

test("each caller gets its own real result or rejection, not the queue's", async () => {
  // The queue's own internal chain swallows rejections so it can keep
  // moving (see the comment in withUploadSlot) -- this pins that the
  // swallowing is internal-only and never leaks into what a caller awaits.
  const ok = withUploadSlot(async () => "camera A's real result");
  const bad = withUploadSlot(async () => {
    throw new Error("camera B's real failure");
  });
  assert.equal(await ok, "camera A's real result");
  await assert.rejects(bad, /camera B's real failure/);
});

test("three uploads run in strict submission order", async () => {
  const order = [];
  const jobs = ["A", "B", "C"].map((label) =>
    withUploadSlot(async () => {
      order.push(label);
      await sleep(5);
    }),
  );
  await Promise.all(jobs);
  assert.deepEqual(order, ["A", "B", "C"]);
});
