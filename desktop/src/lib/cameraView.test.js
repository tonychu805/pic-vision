// The camera list's status tag: what a camera is ready for (2026-09-29).
import assert from "node:assert/strict";
import { test } from "node:test";
import { readiness, cardVisuals, configuredCard } from "./cameraView.js";

const cam = (extra = {}) => ({ id: "c", label: "Court 1", connectionType: "onvif", calibrationKnown: true, isCalibrated: true,
  profile: { fps: 30 }, ...extra });

test("a calibrated camera at 30 fps, not recording, is Ready", () => {
  assert.equal(readiness(cam()).label, "Ready");
});

test("recording is shown above everything else", () => {
  assert.equal(readiness(cam({ isRecording: true, isCalibrated: false })).label, "Recording");
});

// The case that started this: reachable, so it used to say "Online", yet
// recording and calibration are refused.
test("a camera too slow to record says so, even though it answers", () => {
  assert.equal(readiness(cam({ profile: { measuredFps: 15 } })).label, "Frame rate too low");
});

test("one the console hasn't calibrated says Needs calibration", () => {
  assert.equal(readiness(cam({ isCalibrated: false })).label, "Needs calibration");
});

// Paired: before the console has reported calibration (launch, or a machine
// that isn't connected), no camera may be accused of needing it.
test("before the console has reported, calibration isn't claimed either way", () => {
  const r = readiness(cam({ isCalibrated: false, calibrationKnown: false }));
  assert.equal(r.label, "Online");
  assert.notEqual(r.label, "Ready");
});

test("25–29 fps records, so it's a warning, not a block", () => {
  assert.equal(readiness(cam({ profile: { fps: 25 } })).label, "Low frame rate");
});

// Paired: a camera that doesn't answer keeps saying why, untouched by readiness.
test("unreachable cameras keep their own status", () => {
  for (const [state, label] of [["offline", "Not answering"], ["auth", "Sign-in needed"], ["checking", "Checking…"]]) {
    assert.equal(cardVisuals(configuredCard(cam({ isRecording: true }), state)).stateLabel, label);
  }
});

test("the card and the detail page take the same readiness label", () => {
  assert.equal(cardVisuals(configuredCard(cam({ isCalibrated: false }), "ok")).stateLabel, "Needs calibration");
  assert.equal(cardVisuals(configuredCard(cam({ connectionType: "sampleClip", calibrationKnown: false }), "ok")).stateLabel, "File ready");
});
