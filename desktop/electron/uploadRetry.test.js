// The upload retry window (2026-10-28): part 1 of the first real production
// run was lost to a ~2-minute stall because the upload gave up after 3
// tries a few seconds apart. These run on a fake clock.
import assert from "node:assert/strict";
import { test } from "node:test";
import { UPLOAD_RETRY_WINDOW_MS, retryDelayMs, retryWithinWindow } from "./uploadRetry.js";

function fakeClock() {
  let t = 0;
  return { now: () => t, sleep: async (ms) => { t += ms; } };
}

const stalled = () => new Error("upload stalled: no data moved for 60s");

test("waits longer between tries, then every minute", () => {
  assert.deepEqual([1, 2, 3, 4, 5, 6, 7].map(retryDelayMs), [5_000, 10_000, 20_000, 40_000, 60_000, 60_000, 60_000]);
});

// The production failure: three ~60 s stalls in a row, then the link is
// back. The old loop gave up here.
test("a part survives several minutes of stalls and then uploads", async () => {
  const clock = fakeClock();
  let tries = 0;
  const result = await retryWithinWindow(async () => {
    tries++;
    if (tries <= 4) {
      clock.sleep(60_000); // each stall burns its 60 s before failing
      throw stalled();
    }
    return "uploaded";
  }, clock);
  assert.equal(result, "uploaded");
  assert.equal(tries, 5);
});

// Paired: it still gives up, so an outage a person must see isn't hidden forever.
test("gives up once the window is spent, with the last error", async () => {
  const clock = fakeClock();
  let tries = 0;
  await assert.rejects(retryWithinWindow(async () => { tries++; clock.sleep(60_000); throw stalled(); }, clock), /upload stalled/);
  assert.ok(clock.now() <= UPLOAD_RETRY_WINDOW_MS + 60_000, `stopped at ${clock.now()} ms`);
  assert.ok(tries >= 6, `only ${tries} tries`);
});

test("a cancel stops at once, even while waiting to retry", async () => {
  const clock = fakeClock();
  let cancelled = false;
  let tries = 0;
  const run = retryWithinWindow(async () => {
    tries++;
    throw stalled();
  }, { ...clock, shouldStop: () => cancelled, sleep: async () => { cancelled = true; } });
  await assert.rejects(run, /upload stalled/);
  assert.equal(tries, 1, "no new transfer after the operator pressed Cancel");
});

test("an aborted transfer is not retried", async () => {
  let tries = 0;
  const aborted = Object.assign(new Error("upload cancelled"), { aborted: true });
  await assert.rejects(retryWithinWindow(async () => { tries++; throw aborted; }, { ...fakeClock(), shouldStop: (e) => Boolean(e.aborted) }), /cancelled/);
  assert.equal(tries, 1);
});

test("beforeRetry runs between tries, and its own failure doesn't end the upload", async () => {
  const clock = fakeClock();
  let tries = 0;
  let refreshed = 0;
  const result = await retryWithinWindow(async () => {
    tries++;
    if (tries < 3) throw Object.assign(new Error("upload failed (HTTP 403)"), { status: 403 });
    return "ok";
  }, { ...clock, beforeRetry: async () => { refreshed++; if (refreshed === 1) throw new Error("fetch failed"); } });
  assert.equal(result, "ok");
  assert.equal(refreshed, 2);
});
