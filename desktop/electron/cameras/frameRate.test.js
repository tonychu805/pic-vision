// Run with: npm test  (node's built-in runner, no dependency)
import assert from "node:assert/strict";
import { test } from "node:test";
import { BLOCK_BELOW_FPS, MIN_FPS, WARN_BELOW_FPS, assertUsableFrameRate, effectiveFps, frameRateProblem, frameRateWarning , formatFps, frameRateLevel } from "./frameRate.js";

const camera = (fps, extra = {}) => ({
  label: "Court 1",
  hostname: "192.168.1.50",
  profile: fps === undefined ? undefined : { fps },
  ...extra,
});

// configured = what ONVIF says the camera is set to
// measured   = what actually arrived, counted off the stream
const both = (configured, measured) => ({
  label: "Court 1",
  hostname: "192.168.1.50",
  profile: { fps: configured, measuredFps: measured },
});

test("a 30fps camera is fine", () => {
  assert.equal(frameRateProblem(camera(30)), null);
});

test("29.97 (NTSC) passes -- it means 30 everywhere in practice", () => {
  assert.equal(frameRateProblem(camera(29.97)), null);
});

test("a genuine 30fps camera measured slightly low is not blocked", () => {
  // Sampling a few seconds of live video carries noise. Blocking here would
  // send a venue to change a setting that is already correct.
  assert.equal(frameRateProblem(both(30, 29.4)), null);
});

test("25 and 28fps record, with a warning -- 30 is a soft floor, 25 the hard one", () => {
  // 2026-09-25, PGC: a camera set to 30 read 28 an hour later and a booked
  // hour was refused outright. Between the floors it records and says so.
  for (const fps of [25, 28]) {
    assert.equal(frameRateProblem(camera(fps)), null, `${fps}fps should not be blocked`);
    const warning = frameRateWarning(camera(fps));
    assert.ok(warning, `${fps}fps should warn`);
    assert.match(warning, /Recording anyway/);
    assert.match(warning, /set the camera's video frame rate to 30/);
  }
});

test("24fps is refused", () => {
  const problem = frameRateProblem(camera(24));
  assert.ok(problem);
  assert.match(problem, /at least 25 fps/);
  assert.equal(frameRateWarning(camera(24)), null, "a blocked camera gets the block, not a warning too");
});

test("15fps is refused, since it halves the rallies found", () => {
  const problem = frameRateProblem(camera(15));
  assert.ok(problem, "expected 15fps to be refused");
  assert.match(problem, /15 fps/);
  assert.match(problem, /half the rallies/);
});

test("the refusal says where to go and what to set", () => {
  // The whole point of blocking rather than warning: the operator must be
  // able to fix it without asking anyone.
  const problem = frameRateProblem(camera(15));
  assert.match(problem, /http:\/\/192\.168\.1\.50/);
  assert.match(problem, /set the video frame rate to 30/);
});

test("a camera whose frame rate we don't know is never blocked", () => {
  // RTSP-added cameras never went through ONVIF, and a sample clip has no
  // camera at all -- blocking those would refuse real setups over missing
  // data rather than over a known-bad one.
  assert.equal(frameRateProblem(camera(undefined)), null);
  assert.equal(frameRateProblem({ label: "x" }), null);
  assert.equal(frameRateProblem(camera(0)), null);
  assert.equal(frameRateProblem(camera(null)), null);
  assert.equal(frameRateProblem(camera("30")), null);
});

test("both boundaries are inclusive, and the soft one sits at the tolerance not the target", () => {
  assert.equal(MIN_FPS, 30);
  assert.equal(WARN_BELOW_FPS, 29);
  assert.equal(BLOCK_BELOW_FPS, 25);
  assert.equal(frameRateWarning(camera(WARN_BELOW_FPS)), null);
  assert.ok(frameRateWarning(camera(WARN_BELOW_FPS - 0.1)));
  assert.equal(frameRateProblem(camera(BLOCK_BELOW_FPS)), null);
  assert.ok(frameRateProblem(camera(BLOCK_BELOW_FPS - 0.1)));
});

test("assertUsableFrameRate throws below the hard floor and returns the warning above it", () => {
  assert.equal(assertUsableFrameRate(camera(30)), null);
  assert.match(assertUsableFrameRate(camera(28)), /Recording anyway/);
  assert.throws(() => assertUsableFrameRate(camera(15)), /15 fps/);
});

test("a camera set to 30 but only 27 arriving is warned about the network, not the setting", () => {
  const warning = frameRateWarning(both(30, 27));
  assert.match(warning, /set to 30 fps but only about 27/);
  assert.match(warning, /Wi-Fi/);
  assert.doesNotMatch(warning, /set the camera's video frame rate/);
});


// --- configured vs. measured (ADR-087 amendment) ---------------------------

test("what actually arrives decides pass/fail, not what the camera claims", () => {
  // The hole this closes: a camera set to 30 that only delivers 15 used to
  // sail through, because only the configured number was ever checked.
  assert.equal(effectiveFps(both(30, 15)), 15);
  assert.ok(frameRateProblem(both(30, 15)));
});

test("a camera set correctly but starved by the network is told it's the network", () => {
  const problem = frameRateProblem(both(30, 15));
  assert.match(problem, /set to 30 fps but only about 15 fps are reaching/);
  assert.match(problem, /network problem/);
  // Must NOT send them to change a setting that is already right.
  assert.doesNotMatch(problem, /set the video frame rate/);
});

test("a camera genuinely set too low is told to change the setting", () => {
  const problem = frameRateProblem(both(15, 15));
  assert.match(problem, /set the video frame rate to 30/);
  assert.doesNotMatch(problem, /network problem/);
});

test("an RTSP camera has no configured rate, so it gets the settings advice", () => {
  // Nothing knows what it's *set* to -- only what arrived -- so blaming the
  // network would be a guess.
  const rtsp = { label: "Court 2", hostname: "10.0.0.9", profile: { fps: null, measuredFps: 15 } };
  const problem = frameRateProblem(rtsp);
  assert.match(problem, /set the video frame rate to 30/);
  assert.doesNotMatch(problem, /network problem/);
});

test("measured and configured both healthy passes", () => {
  assert.equal(frameRateProblem(both(30, 30)), null);
  assert.equal(effectiveFps(both(30, 29.4)), 29.4);
});

test("a failed measurement falls back to the configured rate", () => {
  assert.equal(effectiveFps(both(30, null)), 30);
  assert.equal(frameRateProblem(both(30, null)), null);
  assert.ok(frameRateProblem(both(15, null)));
});

// 2026-09-29: one reading of the rule for every screen.
test("the level matches the actual gate: blocked below 25, low from 25 to 29, fine from 29", () => {
  assert.equal(frameRateLevel(camera(15)), "blocked");
  assert.equal(frameRateLevel({ profile: { measuredFps: 24.8 } }), "blocked");
  assert.equal(frameRateLevel(camera(25)), "low");
  assert.equal(frameRateLevel(camera(28)), "low");
  assert.equal(frameRateLevel(camera(29.97)), "ok");
  assert.equal(frameRateLevel(camera(undefined)), "unknown");
});

// Paired with the gate itself: the level must never disagree with what
// recording actually does, which is the bug the camera page had.
test("a camera the level calls blocked is exactly one recording refuses", () => {
  for (const fps of [10, 15, 24, 24.8, 25, 26, 28.9, 29, 30]) {
    assert.equal(frameRateLevel(camera(fps)) === "blocked", frameRateProblem(camera(fps)) !== null, `${fps} fps`);
  }
});

test("a frame rate is never rounded across a limit", () => {
  assert.equal(formatFps(24.8), "24.8");
  assert.equal(formatFps(30), "30");
  assert.equal(formatFps(29.97), "30");
  assert.equal(formatFps(15), "15");
});

test("a camera that only reports what arrives isn't described as 'set to' a rate", () => {
  const rtsp = { label: "Court 2", hostname: "192.168.1.22", profile: { measuredFps: 24.8 } };
  assert.match(frameRateProblem(rtsp), /Court 2 is sending about 24\.8 fps/);
  assert.doesNotMatch(frameRateProblem(rtsp), /set to 25/);
  // Paired: a camera that did report its setting still says so.
  assert.match(frameRateProblem(camera(15)), /is set to 15 fps/);
});
