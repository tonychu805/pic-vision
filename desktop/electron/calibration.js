// Live-camera calibration, agent half (ADR-084).
//
// The only part of calibration that has to happen at the venue is grabbing
// a frame -- that needs to be on the camera's network. Everything after
// that now happens elsewhere: the operator clicks the 14 court points in
// the cloud console (ADR-080 moved the UI there), and the homography fit
// runs on the operator's job runner, which has OpenCV and the same
// calibrate.py the project has always used.
//
// So this file no longer runs Python, and the desktop no longer keeps a
// calib.json at all -- the fitted calibration lives on the camera's row in
// the console and gets attached to every cloud job from there. That's what
// makes this app packageable for a venue: no Python, no OpenCV, no
// credentials (see pipeline.js's header).
import { grabSnapshot, grabFrameFromFile, probeDuration, discardSnapshot } from "./capture.js";
import { consoleFetch } from "./consoleApi.js";
import { uploadFile } from "./consoleApi.js";
import { logEvent } from "./activityLog.js";

// A sample-clip camera (2026-09-03) has no live stream to grab from --
// its snapshot comes from seeking into the uploaded file instead. Default
// seek point mirrors webapp/app.py's own _grab_frame heuristic (10% into
// the clip, so an intro/black frame at t=0 isn't what gets clicked).
export async function takeCalibrationSnapshot(camera, atSec) {
  if (camera.connectionType === "sampleClip") {
    const at = atSec ?? Math.max(0, probeDuration(camera.sampleClipPath) * 0.1);
    return grabFrameFromFile(camera.sampleClipPath, at);
  }
  return grabSnapshot(camera);
}

// Console-driven calibration, the agent's only step: grab a fresh frame
// and put it where the console can render it for the operator to click on.
//
// The local file is discarded as soon as it's uploaded -- unlike the
// previous version, nothing here needs to still have it when the points
// come back, because the fit happens on the runner from the copy in
// storage. That also closes the "a live frame of someone's court sat in
// /tmp indefinitely" gap that the old pending-snapshot map had to sweep.
export async function grabAndUploadSnapshot(camera) {
  const snapshot = await takeCalibrationSnapshot(camera);
  try {
    const { url, publicUrl } = await consoleFetch("/api/agents/calibration-snapshots", { method: "POST" });
    await uploadFile(url, snapshot.path);
    logEvent("calibration_snapshot", `Grabbed a calibration frame from ${camera.label}`);
    return { snapshotUrl: publicUrl };
  } finally {
    discardSnapshot(snapshot.path);
  }
}
