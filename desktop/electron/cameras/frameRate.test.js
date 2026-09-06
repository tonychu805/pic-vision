// Run with: npm test  (node's built-in runner, no dependency)
import assert from "node:assert/strict";
import { test } from "node:test";
import { MIN_FPS, assertUsableFrameRate, frameRateProblem } from "./frameRate.js";

const camera = (fps, extra = {}) => ({
  label: "Court 1",
  hostname: "192.168.1.50",
  profile: fps === undefined ? undefined : { fps },
  ...extra,
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
