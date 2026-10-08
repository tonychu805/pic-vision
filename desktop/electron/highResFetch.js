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
import { listParts, SEGMENT_RE, SEGMENT_MINUTES } from "./autoSplit.js";
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

function segmentIndex(name) {
  const m = /^session-(\d+)\.mkv$/.exec(name);
  return m ? Number(m[1]) : null;
}

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

// The part's own elapsed-time range, read from the sub-stream's segment
// indices (whichever one of its segments ended up in this part) -- not
// assumed to be contiguous-from-zero, since a part can start partway
// through a recording.
//
// Translating this into main's matching segments by elapsed time, not by
// reusing these exact index numbers, matters only if main and sub have
// drifted apart -- each slot reconnects independently (Stage 2), and a
// reconnect renumbers only the slot it happened to. In the common case
// (no reconnect on either side) the numbers are identical anyway, since
// both started in the same synchronous call at the same segment length;
// this is the plan file's documented, accepted limitation, not something
// this function tries to fully correct.
export function partElapsedRange(part) {
  const indices = part.segments.map(segmentIndex).filter((n) => n != null).sort((a, b) => a - b);
  const firstIndex = indices[0];
  const lastIndex = indices[indices.length - 1];
  return { startSec: firstIndex * SEGMENT_MINUTES * 60, endSec: (lastIndex + 1) * SEGMENT_MINUTES * 60 };
}

// Main's own segments whose elapsed-time index falls in [firstIndex, lastIndex].
export function mainSegmentsForRange(mainDir, startSec, endSec) {
  if (!existsSync(mainDir)) return [];
  const span = SEGMENT_MINUTES * 60;
  const firstIndex = Math.floor(startSec / span);
  const lastIndex = Math.ceil(endSec / span) - 1;
  return readdirSync(mainDir)
    .filter((f) => SEGMENT_RE.test(f))
    .filter((f) => {
      const i = segmentIndex(f);
      return i != null && i >= firstIndex && i <= lastIndex;
    })
    .sort();
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
  const { startSec, endSec } = partElapsedRange(part);
  const segmentNames = mainSegmentsForRange(mainDir, startSec, endSec);
  if (segmentNames.length === 0) return;

  const outPath = path.join(mkdtempSync(path.join(tmpdir(), "pic-vision-highres-out-")), "clip.mp4");
  try {
    // partStartSec/partEndSec are relative to the PART's own concatenation
    // (what the pod actually fed to inference), which starts at startSec
    // into main's segments too -- so the cut below is relative to the
    // concatenation trimHighRes just built, not to startSec a second time.
    await trimHighRes(segmentNames.map((n) => path.join(mainDir, n)), partStartSec, partEndSec, outPath);
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
