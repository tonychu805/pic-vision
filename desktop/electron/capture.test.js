// estimateFpsFromPacketTimes (PIC-150): the frame-rate math, pulled out of
// measureStreamProfile so it's testable without a real camera or a real
// ffprobe process -- exactly the reasoning frameRate.js's own header
// already states for keeping logic pure.
//
// Every case here is built from synthetic packet timestamps, never a real
// camera -- per this project's standing rule against pulling live frames
// or streams from real hardware to verify code.
import assert from "node:assert/strict";
import { test } from "node:test";
import { estimateFpsFromPacketTimes } from "./capture.js";

// A run of N packets at a fixed interval, optionally offset from t=0 --
// the "camera never wavers" case both the old and new estimator agree on.
function steadyTimes(count, intervalSec, startAt = 0) {
  return Array.from({ length: count }, (_, i) => startAt + i * intervalSec);
}

test("a steady 30fps stream reads as 30fps", () => {
  const fps = estimateFpsFromPacketTimes(steadyTimes(240, 1 / 30));
  assert.ok(fps > 29.9 && fps < 30.1, `expected ~30, got ${fps}`);
});

test("a steady 15fps stream still reads low -- the estimator must not mask it", () => {
  // The whole point of measuring at all: a real 15fps camera has to keep
  // reading below the 29fps floor, or the recording gate lets it through.
  const fps = estimateFpsFromPacketTimes(steadyTimes(120, 1 / 15));
  assert.ok(fps > 14.9 && fps < 15.1, `expected ~15, got ${fps}`);
});

test("a slow RTSP start no longer under-reads a real 30fps camera", () => {
  // The regression the median-gap estimator was originally written to
  // fix: the first second carries sparse packets while the connection
  // settles (here, 10fps for 1s), then the camera's real, steady 30fps.
  // A naive frames-over-the-WHOLE-span calculation would under-read this
  // -- the documented real-world case measured 24.9 instead of 30.
  const warmup = steadyTimes(10, 1 / 10);
  const steady = steadyTimes(210, 1 / 30, 1.0);
  const fps = estimateFpsFromPacketTimes([...warmup, ...steady]);
  assert.ok(fps > 29.5 && fps < 30.5, `expected ~30 despite the slow start, got ${fps}`);
});

test("alternating packet spacing reads its true average, not the more common gap", () => {
  // PIC-150's actual bug, reproduced: packets arriving 20ms, 47ms, 20ms,
  // 47ms... average 33.5ms apart, a true ~29.85fps -- but a median-of-gaps
  // estimator locks onto the more frequent 20ms gap and reads ~50fps.
  // Real Diagnostics measurement on this exact camera: 51.55fps.
  const times = [];
  let t = 0;
  const gaps = [0.020, 0.047];
  for (let i = 0; i < 200; i++) {
    times.push(t);
    t += gaps[i % 2];
  }
  const fps = estimateFpsFromPacketTimes(times);
  assert.ok(fps > 28 && fps < 32, `expected ~29.85 (the true average), got ${fps} -- not the ~50 a median would give`);
});

test("a mid-stream stall pulls the reading down rather than being hidden", () => {
  // Deliberate, not a bug: a real gap in the middle means frames genuinely
  // didn't arrive, and this number exists to catch exactly that.
  const before = steadyTimes(90, 1 / 30, 0);
  const after = steadyTimes(90, 1 / 30, 3 + 2 /* a 2s freeze */);
  const fps = estimateFpsFromPacketTimes([...before, ...after]);
  assert.ok(fps < 29, `a 2s stall across a ~5s sample should read noticeably below 30, got ${fps}`);
});

test("too few packets is unmeasurable, not a wild guess", () => {
  assert.equal(estimateFpsFromPacketTimes(steadyTimes(5, 1 / 30)), null);
  assert.equal(estimateFpsFromPacketTimes([]), null);
  assert.equal(estimateFpsFromPacketTimes(null), null);
});

test("packets that never advance in time is unmeasurable, not a divide-by-zero", () => {
  assert.equal(estimateFpsFromPacketTimes(Array(20).fill(1.0)), null);
});

test("out-of-order packet times are sorted first", () => {
  const shuffled = steadyTimes(120, 1 / 30);
  // Reverse a chunk in the middle -- ffprobe's own output is normally
  // sorted already, but nothing guarantees it, and the original code
  // sorted defensively too.
  const scrambled = [...shuffled.slice(60), ...shuffled.slice(0, 60)];
  const fps = estimateFpsFromPacketTimes(scrambled);
  assert.ok(fps > 29.5 && fps < 30.5, `expected ~30 regardless of input order, got ${fps}`);
});

test("an implausible result (corrupt timestamps) is rejected rather than reported", () => {
  // Same ceiling the old code enforced (1-240fps) -- a camera reporting
  // 2000fps is a parsing artifact, not a real measurement.
  const times = steadyTimes(200, 1 / 2000);
  assert.equal(estimateFpsFromPacketTimes(times), null);
});
