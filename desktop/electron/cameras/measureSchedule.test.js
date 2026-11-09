// Run with: npm test  (node's built-in runner, no dependency)
import assert from "node:assert/strict";
import { test } from "node:test";
import { SETTLE_MS, SETTLE_TTL_MS, STEADY_TTL_MS, isSettling, needsCheckBeforeStart, needsMeasuring } from "./measureSchedule.js";

const NOW = Date.parse("2026-11-09T14:00:00Z");
const ago = (ms) => new Date(NOW - ms).toISOString();
const OLD_START = NOW - 2 * SETTLE_MS;
const camera = (profile, extra = {}) => ({
  id: "c1", label: "Court 1", connectionType: "onvif", streamUri: "rtsp://10.0.0.5/s0",
  addedAt: ago(30 * 24 * 3600 * 1000), profile, ...extra,
});

test("a camera added a few minutes ago is settling; one added last month is not", () => {
  assert.equal(isSettling(camera({}, { addedAt: ago(3 * 60 * 1000) }), { now: NOW, appStartedAt: OLD_START }), true);
  assert.equal(isSettling(camera({}), { now: NOW, appStartedAt: OLD_START }), false);
});

test("every camera settles again after the app starts", () => {
  assert.equal(isSettling(camera({}), { now: NOW, appStartedAt: NOW - 60 * 1000 }), true);
});

// 2026-11-09 (operator): the first probe after hooking a camera up can land
// while the stream settles and read low, and that reading stood for 10
// minutes, exactly when someone is about to record.
test("while settling, a reading older than a minute is measured again", () => {
  const cam = camera({ fps: 30, measuredFps: 22, measuredAt: ago(SETTLE_TTL_MS + 1000), measuredAtFps: 30 }, { addedAt: ago(2 * 60 * 1000) });
  assert.equal(needsMeasuring(cam, { now: NOW, appStartedAt: OLD_START }), true);
});

test("once settled, a reading stands for 10 minutes", () => {
  const fresh = camera({ fps: 30, measuredFps: 30, measuredAt: ago(STEADY_TTL_MS - 1000), measuredAtFps: 30 });
  const stale = camera({ fps: 30, measuredFps: 30, measuredAt: ago(STEADY_TTL_MS + 1000), measuredAtFps: 30 });
  assert.equal(needsMeasuring(fresh, { now: NOW, appStartedAt: OLD_START }), false);
  assert.equal(needsMeasuring(stale, { now: NOW, appStartedAt: OLD_START }), true);
});

test("never measured, or the setting changed since: measured at once", () => {
  assert.equal(needsMeasuring(camera({ fps: 30 }), { now: NOW, appStartedAt: OLD_START }), true);
  const changed = camera({ fps: 25, measuredFps: 30, measuredAt: ago(1000), measuredAtFps: 30 });
  assert.equal(needsMeasuring(changed, { now: NOW, appStartedAt: OLD_START }), true);
});

test("a start the stored reading would refuse gets a fresh look first", () => {
  const rtsp = camera({ fps: null, measuredFps: 15, measuredAt: ago(1000) }, { connectionType: "rtsp" });
  assert.equal(needsCheckBeforeStart(rtsp), true);
});

test("a start the stored reading allows is not delayed", () => {
  // The fresh look holds the start for the length of a probe; a camera that
  // would start anyway must not lose those seconds of its booking.
  assert.equal(needsCheckBeforeStart(camera({ fps: 30, measuredFps: 30 })), false);
  assert.equal(needsCheckBeforeStart(camera({ fps: 30, measuredFps: 15 })), false, "a network shortfall records anyway");
  assert.equal(needsCheckBeforeStart(camera({ fps: 30, measuredFps: 15 }, { connectionType: "sampleClip", streamUri: null })), false);
});
