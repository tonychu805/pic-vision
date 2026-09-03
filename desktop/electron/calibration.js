// Live-camera calibration: take a snapshot, let the operator click the 12
// court points + 2 net-tape points in the renderer, then hand the clicks
// off to cloud_pipeline/save_calibration.py to fit the homography --
// exactly the flow webapp/app.py's browser calibrate_page/calibrate_save
// routes already use, ported here instead of the earlier "pass an
// existing calib.json path in" scope (store.js's setCalibPath/system.js's
// pickCalibFile) that PIC-68 shipped with. The homography math itself
// stays in Python (calibrate.py), invoked as a subprocess -- ADR-071's
// "don't reimplement the existing Python in JS," same convention
// pipeline.js already follows for run_desktop_job.py.
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { grabSnapshot, grabFrameFromFile, probeDuration, discardSnapshot, RECORDINGS_ROOT, sanitizeForPath } from "./capture.js";
import { setCalibPath } from "./cameras/store.js";
import { PYTHON_BIN } from "./pythonBin.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.join(__dirname, "..", "..");
const SAVE_CALIBRATION = path.join(REPO_ROOT, "cloud_pipeline", "save_calibration.py");

// A sample-clip camera (2026-09-03) has no live stream to grab from --
// its snapshot comes from seeking into the uploaded file instead. Default
// seek point mirrors webapp/app.py's own _grab_frame heuristic (10% into
// the clip, so an intro/black frame at t=0 isn't what gets clicked) rather
// than always grabbing frame zero; `atSec` lets the renderer override it
// once the operator sees the first frame isn't a usable one.
export async function takeCalibrationSnapshot(camera, atSec) {
  if (camera.connectionType === "sampleClip") {
    const at = atSec ?? Math.max(0, probeDuration(camera.sampleClipPath) * 0.1);
    return grabFrameFromFile(camera.sampleClipPath, at);
  }
  return grabSnapshot(camera);
}

export function discardCalibrationSnapshot(snapshotPath) {
  discardSnapshot(snapshotPath);
}

// Saves to RECORDINGS_ROOT/<camera>/calib.json -- a sibling of that
// camera's timestamped recording folders (capture.js's outDir layout),
// not nested inside any one of them, since a calibration is reused across
// every recording until the camera physically moves (ADR-049), not tied
// to a single session.
function calibPathFor(camera) {
  return path.join(RECORDINGS_ROOT, sanitizeForPath(camera.label), "calib.json");
}

export function saveCalibration(camera, snapshotPath, points) {
  const outPath = calibPathFor(camera);
  const result = spawnSync(PYTHON_BIN, [SAVE_CALIBRATION, "--snapshot", snapshotPath, "--out", outPath], {
    cwd: REPO_ROOT,
    input: JSON.stringify({ points }),
    encoding: "utf8",
  });

  const lastLine = (result.stdout || "").trim().split("\n").pop() || "";
  let parsed = null;
  try {
    parsed = JSON.parse(lastLine);
  } catch {
    // fall through to the generic error below
  }

  if (result.status !== 0 || !parsed || parsed.error) {
    throw new Error(parsed?.error || (result.stderr || "").trim().slice(-2000) || `save_calibration.py exited (code ${result.status})`);
  }

  discardSnapshot(snapshotPath); // only needed to grab the calibration frame, not kept after
  const camera_ = setCalibPath(camera.id, outPath);
  return { camera: camera_, calibPath: outPath, rmseFt: parsed.rmse_ft, worst: parsed.worst };
}
