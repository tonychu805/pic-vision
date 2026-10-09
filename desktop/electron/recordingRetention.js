// How long recordings stay on the venue computer (2026-09-29, ADR-141).
//
// They used to stay forever. The privacy policy (picvisionai.com/privacy)
// says raw recordings are deleted 30 days after recording, and the cloud
// copy already goes as soon as the reel is made -- but the copy here, on the
// venue's own machine, was never deleted by anything.
//
// Raw footage is short-lived recovery material, not an archive. At the end
// of the *venue-local day the recording ended*, it goes if its reel exists.
// If the reel has not succeeded yet, keep it only until it does, then remove
// it on the next sweep. This preserves the one thing a failed cloud job needs
// (a retryable source) without quietly retaining venue footage for days.
//
//   reel done before local midnight -> delete at that midnight
//   reel succeeds after local midnight -> delete promptly
//   no reel yet / failed             -> keep, surface "waiting for reel"
//   recording now, or uploading      -> never
//
// A recording sent in parts counts as done when every piece has a reel.
//
// Only timestamp-named folders under RECORDINGS_ROOT/<camera>/ are ever
// touched. A sample clip is the operator's own file somewhere else, and is
// never considered.
import { existsSync, readdirSync, readFileSync, rmSync, statSync } from "node:fs";
import path from "node:path";
import { RECORDINGS_ROOT, activeRecordingDirs, uploadDirFor } from "./capture.js";
import { isPipelineRunning } from "./pipeline.js";
import { listParts, SEGMENT_RE } from "./autoSplit.js";
import { listCameras } from "./cameras/store.js";
import { logEvent } from "./activityLog.js";

// capture.js names a recording's folder new Date().toISOString() with ':'
// and '.' made filesystem-safe. Anything else in there is not ours to judge.
const RECORDING_DIR_RE = /^(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})-(\d{3})Z$/;

/** When a recording started, from its folder name, or null. */
export function recordingStartedAt(dirName) {
  const m = RECORDING_DIR_RE.exec(dirName);
  return m ? Date.parse(`${m[1]}T${m[2]}:${m[3]}:${m[4]}.${m[5]}Z`) : null;
}

// Local calendar dates must come from the venue, never the Mac's configured
// timezone: an installer can be travelling, or a venue's laptop can simply
// be set wrong. `en-CA` gives stable numeric parts without depending on the
// renderer's locale.
function localYmd(at, timezone) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date(at));
  const value = Object.fromEntries(parts.filter((p) => p.type !== "literal").map((p) => [p.type, p.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

function nextYmd(ymd) {
  const next = new Date(`${ymd}T00:00:00.000Z`);
  next.setUTCDate(next.getUTCDate() + 1);
  return next.toISOString().slice(0, 10);
}

/** The first instant of the following venue-local date, DST-safe. */
export function endOfVenueDay(at, timezone) {
  if (!timezone) return null;
  let ymd;
  try {
    ymd = localYmd(at, timezone);
  } catch {
    return null; // an unknown timezone is never a reason to delete footage
  }
  const target = nextYmd(ymd);
  // Every IANA offset is within this interval around UTC midnight. Binary
  // search finds the actual civil-midnight instant even on DST transition
  // days, which are not necessarily 24 hours long.
  let lo = Date.parse(`${ymd}T00:00:00.000Z`) - 18 * 60 * 60 * 1000;
  let hi = Date.parse(`${target}T00:00:00.000Z`) + 18 * 60 * 60 * 1000;
  while (lo + 1 < hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (localYmd(mid, timezone) >= target) hi = mid;
    else lo = mid;
  }
  return hi;
}

/**
 * What to do with one recording. Pure.
 *   endedAt   -- ms, the last captured segment (falls back to start)
 *   doneAt    -- ms when its reel was finished, or null
 *   busy      -- recording into it, or uploading it, right now
 *   timezone  -- IANA venue timezone; absent/invalid means keep safely
 */
export function retentionDecision({ endedAt, doneAt, busy, timezone }, now) {
  if (busy) return { action: "keep", reason: "in use" };
  const deleteAt = endOfVenueDay(endedAt, timezone);
  if (deleteAt === null) return { action: "keep", reason: "venue timezone unavailable" };
  if (doneAt == null) return { action: "keep", reason: now >= deleteAt ? "waiting for reel after end of day" : "waiting for reel", deleteAt };
  return now >= deleteAt
    ? { action: "delete", reason: "reel ready; local day ended", deleteAt }
    : { action: "keep", reason: "reel ready; deletes at end of day", deleteAt };
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

/**
 * The recording's end for local-day retention. Segment mtimes are written
 * when ffmpeg closes each segment; looking only at the folder timestamp
 * would incorrectly delete a session that started before midnight and ended
 * after it. Cloud-job files are intentionally excluded: processing time must
 * not move the venue's deletion deadline.
 */
export function recordingEndedAt(recordingDir, startedAt) {
  let endedAt = startedAt;
  const dirs = new Set([recordingDir, uploadDirFor(recordingDir)]);
  for (const dir of dirs) {
    if (!existsSync(dir)) continue;
    for (const name of readdirSync(dir)) {
      if (!SEGMENT_RE.test(name)) continue;
      try {
        endedAt = Math.max(endedAt, statSync(path.join(dir, name)).mtimeMs);
      } catch {
        // A segment can disappear between readdir and stat during cleanup;
        // retaining until the next hourly sweep is safer than failing it.
      }
    }
  }
  return endedAt;
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
 * every minute from main.js. Returns what it did, for the log and the tests.
 */
export function retentionSweep({ now = Date.now(), timezone = null, apply = true } = {}) {
  if (!existsSync(RECORDINGS_ROOT)) return [];
  const activeDirs = activeRecordingDirs();
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

      const endedAt = recordingEndedAt(dir, startedAt);
      const decision = retentionDecision({ endedAt, doneAt: reelDoneAt(dir), busy: isBusy(dir, activeDirs), timezone }, now);
      const label = labels.get(cameraId) ?? "a camera that has been removed";
      if (apply && decision.action === "delete") {
        rmSync(dir, { recursive: true, force: true });
        // A dual-stream camera's sub-stream sibling (Stage 2) is never its
        // own entry in this loop (RECORDING_DIR_RE doesn't match "-sub"),
        // so without this it would survive main's deletion forever --
        // exactly the disk leak this fix closes. Deleted as a unit with
        // main, not on its own schedule.
        const subDir = `${dir}-sub`;
        if (existsSync(subDir)) rmSync(subDir, { recursive: true, force: true });
        logEvent("recording_deleted", `Removed a recording of ${label} from this computer`,
          "Its highlights are ready and the venue-local recording day has ended.");
      }
      results.push({ cameraId, dir, startedAt, endedAt, doneAt: reelDoneAt(dir), ...decision });
    }
  }
  return results;
}

/**
 * Non-destructive, per-camera state for the desktop UI and cloud heartbeat.
 * The console never receives a filesystem path or booking/customer data --
 * just enough to tell an operator whether raw footage will disappear tonight
 * or is being held only because a reel still needs to succeed.
 */
export function retentionSummary({ now = Date.now(), timezone = null } = {}) {
  const summaries = {};
  for (const item of retentionSweep({ now, timezone, apply: false })) {
    const summary = summaries[item.cameraId] ?? {
      recording: 0, waitingForReel: 0, waitingAfterEndOfDay: 0,
      deletesAt: null, readyToDelete: 0,
    };
    if (item.reason === "in use") summary.recording++;
    else if (item.doneAt == null) {
      if (item.reason === "waiting for reel after end of day") summary.waitingAfterEndOfDay++;
      else summary.waitingForReel++;
    } else if (item.action === "delete") {
      summary.readyToDelete++;
    } else if (typeof item.deleteAt === "number") {
      summary.deletesAt = summary.deletesAt === null ? item.deleteAt : Math.min(summary.deletesAt, item.deleteAt);
    }
    summaries[item.cameraId] = summary;
  }
  return summaries;
}
