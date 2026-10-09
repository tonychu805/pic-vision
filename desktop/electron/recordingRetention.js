// How long recordings stay on the venue computer (2026-09-29, ADR-141).
//
// They used to stay forever. The privacy policy (picvisionai.com/privacy)
// says raw recordings are deleted 30 days after recording, and the cloud
// copy already goes as soon as the reel is made -- but the copy here, on the
// venue's own machine, was never deleted by anything.
//
// The clock starts when the REEL IS DONE, not when the recording was made:
// once the cloud copy is gone, this is the only copy, and a machine that was
// offline for a week must not lose a booking before its reel exists.
//
//   reel done                    -> delete 7 days after it was done
//   never sent, or reel failed   -> delete 30 days after recording (the
//                                   policy's limit), with a Log line a day
//                                   before, so someone can still send it
//   recording now, or uploading  -> never
//
// A recording sent in parts counts as done when every piece of it is in a
// part whose reel is done; the whole folder goes 7 days after the last one.
//
// Only timestamp-named folders under RECORDINGS_ROOT/<camera>/ are ever
// touched. A sample clip is the operator's own file somewhere else, and is
// never considered.
import { existsSync, readdirSync, readFileSync, rmSync, statSync } from "node:fs";
import path from "node:path";
import Store from "electron-store";
import { RECORDINGS_ROOT, activeRecordingDirs, uploadDirFor } from "./capture.js";
import { isPipelineRunning } from "./pipeline.js";
import { listParts, SEGMENT_RE } from "./autoSplit.js";
import { listCameras } from "./cameras/store.js";
import { logEvent } from "./activityLog.js";

const DAY = 24 * 60 * 60 * 1000;
export const KEEP_AFTER_REEL_DAYS = 7;
export const KEEP_UNSENT_DAYS = 30;
export const WARN_BEFORE_DAYS = 1;

// capture.js names a recording's folder new Date().toISOString() with ':'
// and '.' made filesystem-safe. Anything else in there is not ours to judge.
const RECORDING_DIR_RE = /^(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})-(\d{3})Z$/;

const store = new Store({ name: "recordingRetention", configFileMode: 0o600 });

/** When a recording started, from its folder name, or null. */
export function recordingStartedAt(dirName) {
  const m = RECORDING_DIR_RE.exec(dirName);
  return m ? Date.parse(`${m[1]}T${m[2]}:${m[3]}:${m[4]}.${m[5]}Z`) : null;
}

/**
 * What to do with one recording. Pure.
 *   startedAt -- ms
 *   doneAt    -- ms when its reel was finished, or null
 *   busy      -- recording into it, or uploading it, right now
 *   warned    -- the "removed tomorrow" line has already been logged
 */
export function retentionDecision({ startedAt, doneAt, busy, warned }, now) {
  if (busy) return { action: "keep", reason: "in use" };
  if (doneAt != null) {
    const deleteAt = doneAt + KEEP_AFTER_REEL_DAYS * DAY;
    return now >= deleteAt ? { action: "delete", reason: "reel done 7+ days ago", deleteAt } : { action: "keep", reason: "reel done", deleteAt };
  }
  const deleteAt = startedAt + KEEP_UNSENT_DAYS * DAY;
  if (now >= deleteAt) return { action: "delete", reason: "no reel after 30 days", deleteAt };
  if (now >= deleteAt - WARN_BEFORE_DAYS * DAY && !warned) return { action: "warn", reason: "no reel, 30 days tomorrow", deleteAt };
  return { action: "keep", reason: "waiting for a reel", deleteAt };
}

function readStatus(jobDir) {
  const file = path.join(jobDir, "status.json");
  if (!existsSync(file)) return null;
  try {
    const status = JSON.parse(readFileSync(file, "utf8"));
    if (status?.done !== true) return { done: false };
    // doneAt since 2026-09-29; before that, when the file was last written,
    // which is the moment it was marked done (nothing writes it afterwards).
    const at = Date.parse(status.doneAt ?? "");
    return { done: true, doneAt: Number.isFinite(at) ? at : statSync(file).mtimeMs };
  } catch {
    return { done: false };
  }
}

/**
 * When this recording's reel was finished -- whole, or every part -- or
 * null. Reads from uploadDirFor(recordingDir), not recordingDir itself: a
 * dual-stream camera's cloud_job/ and parts/ live under its sub-stream
 * sibling (Stage 2's upload-direction fix), never under main. Reading
 * `recordingDir` directly for such a camera would never find them -- every
 * dual-stream recording would read as "no reel ever made" forever, no
 * matter how many reels it actually produced. A no-op for a single-stream
 * camera, where uploadDirFor returns recordingDir unchanged.
 */
export function reelDoneAt(recordingDir) {
  const uploadDir = uploadDirFor(recordingDir);
  const whole = readStatus(path.join(uploadDir, "cloud_job"));
  if (whole?.done) return whole.doneAt;
  const parts = listParts(uploadDir);
  if (parts.length === 0) return null;
  const inParts = new Set(parts.flatMap((p) => p.segments));
  const segments = readdirSync(uploadDir).filter((f) => SEGMENT_RE.test(f));
  if (!segments.every((f) => inParts.has(f))) return null; // some of it was never sent
  let latest = 0;
  for (const part of parts) {
    const status = readStatus(path.join(part.dir, "cloud_job"));
    if (!status?.done) return null;
    latest = Math.max(latest, status.doneAt);
  }
  return latest;
}

// activeDirs.has(recordingDir) alone still covers "is this camera recording
// right now": activeRecordingDirs() always includes a dual-stream camera's
// main outDir (capture.js), so this check doesn't need uploadDirFor. The
// pipeline checks do, for the same reason reelDoneAt's do above -- a job
// actually runs under the sub-stream sibling, not main.
function isBusy(recordingDir, activeDirs) {
  if (activeDirs.has(recordingDir)) return true;
  const uploadDir = uploadDirFor(recordingDir);
  if (isPipelineRunning(uploadDir)) return true;
  return listParts(uploadDir).some((p) => isPipelineRunning(p.dir));
}

/**
 * Apply the rules to every recording on this computer. Run at launch and
 * hourly from main.js. Returns what it did, for the log and the tests.
 */
export function retentionSweep(now = Date.now()) {
  if (!existsSync(RECORDINGS_ROOT)) return [];
  const activeDirs = activeRecordingDirs();
  const warned = store.get("warned", {});
  const labels = new Map(listCameras().map((c) => [c.id, c.label]));
  const results = [];
  const root = path.resolve(RECORDINGS_ROOT);

  for (const cameraId of readdirSync(RECORDINGS_ROOT)) {
    const cameraDir = path.join(RECORDINGS_ROOT, cameraId);
    if (!statSync(cameraDir).isDirectory()) continue;
    for (const name of readdirSync(cameraDir)) {
      const startedAt = recordingStartedAt(name);
      if (startedAt === null) continue;
      const dir = path.join(cameraDir, name);
      if (!statSync(dir).isDirectory() || !path.resolve(dir).startsWith(root + path.sep)) continue;

      const decision = retentionDecision({ startedAt, doneAt: reelDoneAt(dir), busy: isBusy(dir, activeDirs), warned: Boolean(warned[dir]) }, now);
      const label = labels.get(cameraId) ?? "a camera that has been removed";
      if (decision.action === "delete") {
        rmSync(dir, { recursive: true, force: true });
        // A dual-stream camera's sub-stream sibling (Stage 2) is never its
        // own entry in this loop (RECORDING_DIR_RE doesn't match "-sub"),
        // so without this it would survive main's deletion forever --
        // exactly the disk leak this fix closes. Deleted as a unit with
        // main, not on its own schedule.
        const subDir = `${dir}-sub`;
        if (existsSync(subDir)) rmSync(subDir, { recursive: true, force: true });
        delete warned[dir];
        logEvent("recording_deleted", `Removed a recording of ${label} from this computer`,
          decision.reason === "reel done 7+ days ago"
            ? "Its highlights were made more than 7 days ago; the recording is no longer kept here."
            : "No highlights were made from it within 30 days of recording.");
      } else if (decision.action === "warn") {
        warned[dir] = true;
        logEvent("recording_expiring", `A recording of ${label} will be removed from this computer tomorrow`,
          "No highlights have been made from it. Send it from the camera's page today if you still want them.");
      }
      results.push({ dir, ...decision });
    }
  }
  // Forget warnings for recordings that are gone, however they went.
  for (const dir of Object.keys(warned)) if (!existsSync(dir)) delete warned[dir];
  store.set("warned", warned);
  return results;
}
