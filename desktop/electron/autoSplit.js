// Auto-split: send a recording to the cloud in parts while it's still
// recording, so the reels for everything but the last part are ready by the
// time the session ends (2026-09-23, for in-person delivery at a venue test).
//
// It regroups files that already exist. capture.js has always written a
// recording as 10-minute segments (session-000.mkv, session-001.mkv, ...)
// and keeps recording across them, so a part is just a set of FINISHED
// segments: no stopping the camera, no footage lost at a split. Each part is
// a folder of hard links to its segments (<recording>/parts/part-01/), which
// is exactly the shape runCloudJob() already sends -- so every part rides the
// existing, tested upload path as an ordinary job, unchanged.
//
// Off unless the operator turns it on (autoSplitMinutes > 0), so a venue
// machine that updates keeps today's whole-session behaviour.
//
// This is the manual stand-in for ADR-066's rolling pipeline: parts are
// separate jobs with separate reels. Combining them into one session reel
// is that later work, not this.
import Store from "electron-store";
import { existsSync, linkSync, copyFileSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";

export const SEGMENT_RE = /^session-\d+\.mkv$/;
const PART_RE = /^part-(\d+)$/;
export const SEGMENT_MINUTES = 10; // capture.js: -segment_time 600

// A segment ffmpeg has moved past is finished; this guards the moment right
// after the switch, before the old file's last write has landed.
export const SETTLE_MS = 15_000;

const store = new Store({ name: "autoSplit", configFileMode: 0o600 });

/** Part length in minutes; 0 = off. Rounded to whole 10-minute segments. */
export function getAutoSplitMinutes() {
  const v = store.get("minutes", 0);
  return Number.isFinite(v) && v > 0 ? v : 0;
}

export function setAutoSplitMinutes(minutes) {
  const n = Number(minutes);
  if (!Number.isFinite(n) || n < 0 || n > 120) throw new Error("part length must be 0 (off) to 120 minutes");
  const rounded = n === 0 ? 0 : Math.max(SEGMENT_MINUTES, Math.round(n / SEGMENT_MINUTES) * SEGMENT_MINUTES);
  store.set("minutes", rounded);
  return rounded;
}

// ---------- pure planning (unit-tested) ----------

/**
 * Which segments go into new parts now.
 *   finished      finished segment names, in order
 *   sent          names already in some part
 *   partSegments  segments per part
 *   flush         true = send everything finished-and-unsent now, however few
 * Returns an array of parts, each an array of segment names.
 */
export function planParts({ finished, sent, partSegments, flush }) {
  const unsent = finished.filter((f) => !sent.has(f));
  const parts = [];
  if (flush) {
    if (unsent.length) parts.push(unsent);
    return parts;
  }
  for (let i = 0; i + partSegments <= unsent.length; i += partSegments) parts.push(unsent.slice(i, i + partSegments));
  return parts;
}

/** Finished segments of a recording: all but the one ffmpeg is still writing, and none written in the last SETTLE_MS. */
export function finishedSegments(names, { stillRecording, mtimes, now }) {
  const sorted = [...names].filter((n) => SEGMENT_RE.test(n)).sort();
  const candidates = stillRecording ? sorted.slice(0, -1) : sorted;
  return stillRecording ? candidates.filter((n) => now - (mtimes[n] ?? now) >= SETTLE_MS) : candidates;
}

// ---------- filesystem ----------

export function partsDir(recordingDir) {
  return path.join(recordingDir, "parts");
}

/** Existing parts, in order: [{ name, dir, index, segments: [names] }]. */
export function listParts(recordingDir) {
  const dir = partsDir(recordingDir);
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .map((name) => ({ name, m: PART_RE.exec(name) }))
    .filter(({ m }) => m)
    .map(({ name, m }) => {
      const partDir = path.join(dir, name);
      return { name, dir: partDir, index: Number(m[1]), segments: readdirSync(partDir).filter((f) => SEGMENT_RE.test(f)).sort() };
    })
    .sort((a, b) => a.index - b.index);
}

/** Create the next part folder holding `segmentNames` (hard links; a copy if linking isn't possible). */
export function createPart(recordingDir, segmentNames) {
  const existing = listParts(recordingDir);
  const index = (existing.at(-1)?.index ?? 0) + 1;
  const dir = path.join(partsDir(recordingDir), `part-${String(index).padStart(2, "0")}`);
  mkdirSync(dir, { recursive: true });
  for (const name of segmentNames) {
    const src = path.join(recordingDir, name);
    const dst = path.join(dir, name);
    try {
      linkSync(src, dst);
    } catch {
      copyFileSync(src, dst);
    }
  }
  return { name: path.basename(dir), dir, index, segments: segmentNames };
}

/** New parts that are due for this recording (created on disk). */
export function makeDueParts(recordingDir, { stillRecording, partMinutes, flush = false, now = Date.now() }) {
  const names = readdirSync(recordingDir).filter((f) => SEGMENT_RE.test(f));
  const mtimes = Object.fromEntries(names.map((n) => [n, statSync(path.join(recordingDir, n)).mtimeMs]));
  const finished = finishedSegments(names, { stillRecording, mtimes, now });
  const sent = new Set(listParts(recordingDir).flatMap((p) => p.segments));
  const partSegments = Math.max(1, Math.round(partMinutes / SEGMENT_MINUTES));
  return planParts({ finished, sent, partSegments, flush }).map((segs) => createPart(recordingDir, segs));
}

/** Parts whose send never got as far as a console job (no cloud_job/job.json) -- e.g. the console was unreachable. */
export function unsentParts(recordingDir, isRunning) {
  return listParts(recordingDir).filter((p) => !existsSync(path.join(p.dir, "cloud_job", "job.json")) && !isRunning(p.dir));
}

/** A part's session id: distinct per part, or the console treats part 2 as a resend of part 1 and cancels its upload. */
export function partSessionId(cameraLabel, recordingDir, partName) {
  return `${cameraLabel}-${path.basename(recordingDir)}-${partName}`.replace(/[^a-zA-Z0-9._-]+/g, "_");
}

// One pass at a time: the timer, a "send now" press and a stop can all
// arrive together, and a segment must never land in two parts.
let queue = Promise.resolve();
export function serialized(fn) {
  const run = queue.then(fn, fn);
  queue = run.catch(() => {});
  return run;
}

// ---------- the playing session this recording belongs to (ADR-128) ----------

const SESSION_FILE = "session.json";

/** Remember the console-issued session for a recording, from its start command. */
export function writeSessionMeta(recordingDir, params) {
  const recordingSessionId = typeof params?.recording_session_id === "string" ? params.recording_session_id : null;
  const bookingId = typeof params?.schedule_booking_id === "string" ? params.schedule_booking_id : null;
  writeFileSync(path.join(recordingDir, SESSION_FILE), JSON.stringify({ recordingSessionId, bookingId }, null, 2));
}

/** The session saved for a recording, or null (none saved, or unreadable). */
export function readSessionMeta(recordingDir) {
  try {
    return JSON.parse(readFileSync(path.join(recordingDir, SESSION_FILE), "utf8"));
  } catch {
    return null;
  }
}

/**
 * Whether a stop command should end the camera's current recording.
 *
 * A booking's stop names the recording session it belongs to (console,
 * 2026-09-24). "Stop" used to mean "stop whatever this camera is recording",
 * so a booking's stop killed a recording that wasn't the booking's -- at
 * 05:00 that day it killed the next booking's recording six seconds in.
 *
 * Declined only when the current recording positively belongs to a
 * DIFFERENT session. A recording with no session saved (older build, or a
 * failed write) is stopped as before: never stopping it would leave it
 * running, and its parts billing, with nothing to end it.
 */
export function stopTargets(commandParams, currentMeta) {
  const wanted = commandParams?.recording_session_id;
  const current = currentMeta?.recordingSessionId;
  if (!wanted || !current) return true;
  return wanted === current;
}

/**
 * What an upload of `dir` tells the console about its session: the
 * session id, and -- for a part folder (<recording>/parts/part-NN) -- its
 * number and where it starts in the session (its first segment's index x 10
 * minutes). Nothing for a recording that predates sessions or had none.
 */
export function sessionFieldsFor(dir, fileNames) {
  const partMatch = PART_RE.exec(path.basename(dir));
  const isPart = partMatch && path.basename(path.dirname(dir)) === "parts";
  const recordingDir = isPart ? path.dirname(path.dirname(dir)) : dir;
  const recordingSessionId = readSessionMeta(recordingDir)?.recordingSessionId ?? null;
  if (!recordingSessionId) return {};
  if (!isPart) return { recordingSessionId };
  const first = [...fileNames].map((f) => path.basename(f)).filter((f) => SEGMENT_RE.test(f)).sort()[0];
  const segIndex = first ? Number(/\d+/.exec(first)[0]) : 0;
  return { recordingSessionId, partIndex: Number(partMatch[1]), partOffsetSec: segIndex * SEGMENT_MINUTES * 60 };
}
