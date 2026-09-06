// Run with: npm test  (node's built-in runner, no dependency)
import assert from "node:assert/strict";
import { test } from "node:test";
import { MIN_FPS, assertUsableFrameRate, effectiveFps, frameRateProblem } from "./frameRate.js";

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

test("25fps (PAL region) still passes -- close enough to the tuning", () => {
  assert.equal(frameRateProblem(camera(25)), null);
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

test("the boundary is inclusive", () => {
  assert.equal(frameRateProblem(camera(MIN_FPS)), null);
  assert.ok(frameRateProblem(camera(MIN_FPS - 1)));
});

test("assertUsableFrameRate throws the same message it reports", () => {
  assert.doesNotThrow(() => assertUsableFrameRate(camera(30)));
  assert.throws(() => assertUsableFrameRate(camera(15)), /15 fps/);
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
  assert.equal(frameRateProblem(both(30, 29.4)), null);
  assert.equal(effectiveFps(both(30, 29.4)), 29.4);
});

test("a failed measurement falls back to the configured rate", () => {
  assert.equal(effectiveFps(both(30, null)), 30);
  assert.equal(frameRateProblem(both(30, null)), null);
  assert.ok(frameRateProblem(both(15, null)));
});
