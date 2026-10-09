// Dual-stream plan Stage 5: for each pending fetch the console's heartbeat
// response offers (Stage 4's pendingHighResFetches -- a rally reel whose
// Stage 3 part_start_sec/part_end_sec are known but whose clip is still
// the proxy-resolution one the pod first cut), locate the matching
// stretch of this camera's local high-res (main-profile) recording, trim
// it, and upload it to replace that reel's clip.
//
// Fire-and-forget relative to the heartbeat that triggers it (cloud.js
// awaits nothing here) -- a trim+encode+upload can run for a while, and a
// heartbeat's own liveness must not wait on it.
import { existsSync, mkdtempSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { FFMPEG } from "./binaries.js";
import { logEvent } from "./activityLog.js";
import { listParts, SEGMENT_RE } from "./autoSplit.js";
import { cameraRecordingsDir, uploadDirFor } from "./capture.js";
import { consoleFetch, uploadFile } from "./consoleApi.js";
import { listCameras } from "./cameras/store.js";

// Guards against the SAME reel being started twice -- the console keeps
// offering a fetch on every heartbeat until this machine's own PATCH
// confirms it (Stage 4), so a slow trim+upload can easily still be running
// when the next heartbeat's list arrives. Not persisted across restarts:
// a restart just means the console offers it again, and redoing an
// already-finished trim/upload is safe (idempotent -- a fresh key every
// time, same as any other presigned upload here), so there's nothing a
// crash could leave half-done that a plain retry doesn't fix on its own.
const inFlight = new Set();

// Which main-profile recording folder has the auto-split part this fetch
// names, and that part's own segment list -- parts live under the
// recording's sub-stream sibling since the Stage 2 upload-direction fix
// (uploadDirFor's doc comment), never under main itself.
export function findRecordingForPart(camera, partIndex) {
  const cameraDir = cameraRecordingsDir(camera);
  if (!existsSync(cameraDir)) return null;
  const partName = `part-${String(partIndex).padStart(2, "0")}`;
  for (const name of readdirSync(cameraDir)) {
    if (name.endsWith("-sub")) continue;
    const mainDir = path.join(cameraDir, name);
    if (!statSync(mainDir).isDirectory()) continue;
    const part = listParts(uploadDirFor(mainDir)).find((p) => p.name === partName);
    if (part) return { mainDir, part };
  }
  return null;
}

// Exactly the shape startRecording's outDir names itself in
// (`new Date().toISOString().replace(/[:.]/g, "-")`), optionally with a
// "-sub" suffix for the sibling -- reversed to get the exact instant this
// recording started. Filesystem-independent, unlike birthtime, which some
// filesystems don't populate reliably; falls back to it anyway for
// anything not in this exact shape (there shouldn't be any folder that
// isn't, but a wrong guess here only ever affects segment 0's start
// boundary, nothing else, and birthtime is at least directionally right).
const DIR_NAME_RE = /^(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})-(\d{3})Z(?:-sub)?$/;
function recordingStartedAt(dir) {
  const m = DIR_NAME_RE.exec(path.basename(dir));
  if (!m) return statSync(dir).birthtime;
  const [, date, HH, mm, ss, sss] = m;
  return new Date(`${date}T${HH}:${mm}:${ss}.${sss}Z`);
}

// Every segment's own real wall-clock [start, end) in `dir`. A segment's
// mtime is roughly when ffmpeg closed it and opened the next one -- so the
// PREVIOUS segment's mtime is THIS one's start, and the recording's own
// start time is segment 0's.
//
// Derived entirely from this one directory's own files: deliberately NOT
// index arithmetic (segIndex * 600s), because main and sub reconnect
// independently (Stage 2) -- a reconnect renumbers only the slot it
// happened to, desyncing "sub's segment N" from "main's segment N" in
// wall-clock terms by however long that stream was actually down. Real
// mtimes don't have that problem: each stream tells its own true story
// regardless of what the other one's reconnect history did.
function segmentWindows(dir) {
  const names = readdirSync(dir).filter((f) => SEGMENT_RE.test(f)).sort();
  let start = recordingStartedAt(dir);
  const windows = [];
  for (const name of names) {
    const end = statSync(path.join(dir, name)).mtime;
    windows.push({ name, start, end });
    start = end;
  }
  return windows;
}

// The real wall-clock window a part covers, read from its own (sub-stream)
// segments' windows -- not assumed contiguous-from-zero, since a part can
// start partway through a recording.
export function partWindow(subDir, part) {
  const byName = new Map(segmentWindows(subDir).map((w) => [w.name, w]));
  const matched = part.segments.map((n) => byName.get(n)).filter(Boolean);
  if (matched.length === 0) return null;
  return { start: matched[0].start, end: matched[matched.length - 1].end };
}

// Main's own segments whose real window overlaps the part's.
export function mainWindowsOverlapping(mainDir, window) {
  if (!existsSync(mainDir)) return [];
  return segmentWindows(mainDir).filter((w) => w.end > window.start && w.start < window.end);
}

// How much earlier main's concatenation (mainWindows, in order) begins
// than the part's own real window -- added to partStartSec/partEndSec
// since segment boundaries between the two streams don't have to line up.
// Null (not clamped to 0) means main cannot produce a correct cut here:
// either no overlap at all, or main's earliest overlapping segment starts
// AFTER the window does -- a coverage gap at the exact moment needed (main
// dropped out right as the rally began, or hadn't started yet). Clamping
// a negative gap to 0 would silently shift the cut by the missing amount
// instead of admitting main can't do this one.
export function leadSecFor(mainWindows, window) {
  if (mainWindows.length === 0) return null;
  const lead = (window.start.getTime() - mainWindows[0].start.getTime()) / 1000;
  return lead < 0 ? null : lead;
}

function run(args) {
  return new Promise((resolve, reject) => {
    const proc = spawn(FFMPEG, args, { stdio: ["ignore", "ignore", "pipe"] });
    let stderrTail = "";
    proc.stderr.on("data", (chunk) => { stderrTail = (stderrTail + chunk.toString()).slice(-4000); });
    proc.on("error", reject);
    proc.on("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(stderrTail.trim().split("\n").pop() || `ffmpeg exited (code ${code})`));
    });
  });
}

// Concatenates main's matching segments (stream copy -- same clips ffmpeg
// already wrote, nothing to re-encode yet) and cuts [startSec, endSec]
// relative to that concatenation's own start, re-encoding for a frame-
// accurate boundary -- same reasoning and the same flags render.py's
// clip_command uses on the cloud side: input-seeking (`-ss` before `-i`)
// is frame-accurate once paired with a re-encode, not with `-c copy`.
export async function trimHighRes(segmentPaths, startSec, endSec, outPath) {
  const workDir = mkdtempSync(path.join(tmpdir(), "pic-vision-highres-"));
  const listFile = path.join(workDir, "concat.txt");
  const concatOut = path.join(workDir, "concat.mkv");
  try {
    writeFileSync(listFile, segmentPaths.map((p) => `file '${p}'\n`).join(""));
    await run(["-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", listFile, "-c", "copy", concatOut]);
    await run([
      "-y", "-v", "error", "-ss", String(startSec), "-i", concatOut, "-t", String(endSec - startSec),
      "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", outPath,
    ]);
  } finally {
    rmSync(workDir, { recursive: true, force: true });
  }
}

async function uploadHighRes(reelId, filePath) {
  const minted = await consoleFetch(`/api/agents/reels/${reelId}/high-res`, { method: "POST" });
  await uploadFile(minted.url, filePath);
  await consoleFetch(`/api/agents/reels/${reelId}/high-res`, { method: "PATCH", body: { key: minted.key } });
}

async function processOne(camera, fetchReq) {
  const { reelId, partIndex, partStartSec, partEndSec } = fetchReq;
  const located = findRecordingForPart(camera, partIndex);
  if (!located) {
    // Not an error worth logging on its own -- the local recording this
    // would trim from is routinely gone before this ever runs (retention,
    // Stage 4's own doc comment on the interaction) or simply belongs to
    // a different machine than the one that recorded it.
    return;
  }
  const { mainDir, part } = located;
  const window = partWindow(uploadDirFor(mainDir), part);
  if (!window) return;
  const mainWindows = mainWindowsOverlapping(mainDir, window);
  // partStartSec/partEndSec are relative to the PART's own concatenation
  // start (what the pod actually fed to inference, i.e. window.start), so
  // leadSec corrects for main's concatenation starting at a different real
  // moment -- see leadSecFor's own comment for when that's unrecoverable
  // (no overlap, or a coverage gap right at the start) rather than just a
  // boundary mismatch to adjust for.
  const leadSec = leadSecFor(mainWindows, window);
  if (leadSec === null) return;

  const outPath = path.join(mkdtempSync(path.join(tmpdir(), "pic-vision-highres-out-")), "clip.mp4");
  try {
    const segmentPaths = mainWindows.map((w) => path.join(mainDir, w.name));
    await trimHighRes(segmentPaths, partStartSec + leadSec, partEndSec + leadSec, outPath);
    await uploadHighRes(reelId, outPath);
    logEvent("high_res_reel_synced", `${camera.label}: sent a sharper version of a rally clip`, reelId);
  } finally {
    rmSync(path.dirname(outPath), { recursive: true, force: true });
  }
}

/** Process every pending fetch the heartbeat just offered -- called from cloud.js, never awaited by it. */
export async function processPendingHighResFetches(fetches) {
  if (fetches.length === 0) return;
  const cameras = listCameras();
  for (const fetchReq of fetches) {
    if (inFlight.has(fetchReq.reelId)) continue;
    const camera = cameras.find((c) => c.id === fetchReq.cameraId);
    if (!camera) continue;
    inFlight.add(fetchReq.reelId);
    try {
      await processOne(camera, fetchReq);
    } catch (err) {
      logEvent("high_res_reel_failed", `${camera.label}: couldn't send a sharper version of a rally clip`, err.message);
    } finally {
      inFlight.delete(fetchReq.reelId);
    }
  }
}
