// Live-camera calibration: take a snapshot, let the operator click the 12
// court points + 2 net-tape points, then hand the clicks off to
// cloud_pipeline/save_calibration.py to fit the homography -- exactly the
// flow webapp/app.py's browser calibrate_page/calibrate_save routes
// already use, ported here instead of the earlier "pass an existing
// calib.json path in" scope (store.js's setCalibPath/system.js's
// pickCalibFile) that PIC-68 shipped with. The homography math itself
// stays in Python (calibrate.py), invoked as a subprocess -- ADR-071's
// "don't reimplement the existing Python in JS," same convention
// pipeline.js already follows for run_desktop_job.py.
//
// The point-clicking UI itself moved to the cloud console (ADR-080,
// 2026-09-05, superseding ADR-077's "scoped out, not just deferred" call
// on this) -- desktop's own job is now just the two LAN-bound halves:
// grabbing a snapshot and uploading it (grabAndUploadSnapshot), and
// running the unchanged homography fit once the console sends back the
// clicked points (applyPendingCalibration). saveCalibration() itself is
// untouched and still does the actual math either way.
import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { grabSnapshot, grabFrameFromFile, probeDuration, discardSnapshot, RECORDINGS_ROOT, sanitizeForPath } from "./capture.js";
import { setCalibPath } from "./cameras/store.js";
import { PYTHON_BIN } from "./pythonBin.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.join(__dirname, "..", "..");
const SAVE_CALIBRATION = path.join(REPO_ROOT, "cloud_pipeline", "save_calibration.py");
const UPLOAD_SNAPSHOT = path.join(REPO_ROOT, "cloud_pipeline", "upload_calibration_snapshot.py");

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

function uploadToR2(localPath, key) {
  const result = spawnSync(PYTHON_BIN, [UPLOAD_SNAPSHOT, "--local-path", localPath, "--key", key], {
    cwd: REPO_ROOT,
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
    throw new Error(parsed?.error || (result.stderr || "").trim().slice(-2000) || `upload_calibration_snapshot.py exited (code ${result.status})`);
  }
  return parsed.url;
}

// Snapshot grab and point-clicking are now separate round-trips over the
// cloud->agent command channel (ADR-080) -- the gap between them is
// however long the operator takes on the console, not just "however long
// a modal stays open," so the snapshot file has to survive past the end
// of grabAndUploadSnapshot() itself. Keyed by camera id since only one
// calibration attempt per camera makes sense at a time; a stale entry
// (operator abandoned the flow, or grabbed a new snapshot before applying
// the old one) is swept on the next grab rather than tracked with its own
// timer, matching capture.js's own "clean up opportunistically" approach
// to outstandingSnapshots.
const PENDING_TTL_MS = 15 * 60 * 1000;
const pendingSnapshots = new Map(); // cameraId -> { path, uploadedAt }

function sweepExpiredSnapshots() {
  const now = Date.now();
  for (const [cameraId, pending] of pendingSnapshots) {
    if (now - pending.uploadedAt > PENDING_TTL_MS) {
      discardSnapshot(pending.path);
      pendingSnapshots.delete(cameraId);
    }
  }
}

// Console-driven calibration, step 1: grab a fresh frame (the only
// LAN-bound part) and upload it so the console can render it for the
// operator to click on. A fresh random key per grab (ADR-075's "the
// object key is the entire access boundary" -- unlike a reel, which is
// meant to be reshared, a calibration snapshot of someone's court has no
// reason to be guessable at all).
export async function grabAndUploadSnapshot(camera) {
  sweepExpiredSnapshots();
  const stale = pendingSnapshots.get(camera.id);
  if (stale) discardSnapshot(stale.path); // a retake replaces, not accumulates

  const snapshot = await takeCalibrationSnapshot(camera);
  const key = `calibration-snapshots/${randomUUID()}.png`;
  let url;
  try {
    url = uploadToR2(snapshot.path, key);
  } catch (err) {
    discardSnapshot(snapshot.path);
    throw err;
  }
  pendingSnapshots.set(camera.id, { path: snapshot.path, uploadedAt: Date.now() });
  return { snapshotUrl: url };
}

// Console-driven calibration, step 2: the operator has clicked all 14
// points against the snapshot from step 1 -- run the exact same
// saveCalibration() a desktop-side click-through would have, then back
// the finished calib.json up to R2 too (best-effort: a failed backup
// upload shouldn't fail a calibration that already succeeded locally,
// same "log, don't throw" call sendHeartbeat already makes for
// connectivity hiccups). The backup key is stable (not random) -- meant
// to be overwritten on every recalibration, not to accumulate.
export function applyPendingCalibration(camera, points) {
  const pending = pendingSnapshots.get(camera.id);
  if (!pending) throw new Error("no recent snapshot for this camera -- grab a new one and try again");

  // saveCalibration only discards the snapshot file on its own success
  // path, so a thrown error here leaves `pending` still valid for a retry
  // -- only clear it once the save actually succeeded.
  const result = saveCalibration(camera, pending.path, points);
  pendingSnapshots.delete(camera.id);

  try {
    uploadToR2(result.calibPath, `calibration-backups/${camera.id}.json`);
  } catch (err) {
    console.error(`[calibration] backup upload failed: ${err.message}`);
  }

  return result;
}
