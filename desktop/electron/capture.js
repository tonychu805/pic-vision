// Manual start/stop recording from a configured camera's RTSP stream --
// PIC-66, the first real piece of STRATEGY.md §5's "Local stream/footage
// management" bullet. Command shape is exactly TECH_SPEC.md §1.2's spec,
// not reinvented: `-c copy` (stream copy, no re-encode -- nearly free on
// CPU, and avoids PIC-67's GPU-encoder question entirely for this step),
// 10-minute segments (`-f segment -segment_time 600` -- a crash or Wi-Fi
// drop costs one segment, not the whole recording, per the real frame-
// drop testing in ADR-030/032), and `-use_wallclock_as_timestamps 1`
// (the camera's own RTP timestamps are unreliable/non-monotonic, same
// ADR).
//
// Trigger is a manual Start/Stop button (operator's call, 2026-09-01) --
// not tied to the Schedule feature's booked sessions yet. That's a real
// next step (the Schedule page's own copy already says "each booking
// becomes its own highlight reel once automatic capture is built"), just
// not this one -- a manual button is simpler to get right first.
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, unlinkSync } from "node:fs";
import path from "node:path";
import os from "node:os";
import { logEvent } from "./activityLog.js";

export const RECORDINGS_ROOT = path.join(os.homedir(), "pic-vision-recordings");

// cameraId -> { proc, outDir, startedAt }. Module-level, not per-window --
// a recording must survive the renderer navigating away from this
// camera's detail page (it's a background process, not tied to any
// particular page being open).
const active = new Map();

// Exported for calibration.js: a calib.json lives at the same per-camera
// directory level as this camera's recordings
// (RECORDINGS_ROOT/sanitizeForPath(label)/), not inside one particular
// recording's timestamped subfolder, since a calibration outlives any one
// session.
export function sanitizeForPath(label) {
  return label.replace(/[^a-zA-Z0-9._-]+/g, "_").replace(/^_+|_+$/g, "") || "camera";
}

// A camera added via ONVIF (`GetStreamUri`) reports its stream URL
// without embedded credentials -- ONVIF's response just doesn't include
// them, auth happens separately at the RTSP layer. A camera added via
// the RTSP fallback already has them embedded (store.js builds that URL
// by hand). ffmpeg needs them in the URL either way, so this fills them
// in when missing rather than assuming every stored streamUri already
// has what it needs.
export function authenticatedStreamUri(camera) {
  const url = new URL(camera.streamUri);
  if (!url.username) url.username = encodeURIComponent(camera.username);
  if (!url.password) url.password = encodeURIComponent(camera.password);
  return url.toString();
}

// Grabs one still frame from the *live* stream for calibration.js's
// take-a-snapshot-and-click-points flow -- deliberately not a frame pulled
// from a past recording, since the point is to calibrate against what the
// camera sees right now. `-frames:v 1` exits ffmpeg on its own the instant
// it has a frame; the timeout below only matters if the RTSP connect
// itself hangs (bad credentials, camera offline), and SIGKILLing that is
// safe -- unlike stopRecording's SIGINT requirement, there's no in-progress
// container to corrupt, just a single already-complete-or-nonexistent PNG.
const SNAPSHOT_TIMEOUT_MS = 10000;

// Every calibration snapshot currently sitting in the OS tmpdir,
// undiscarded -- tracked so app quit can sweep them up (see
// discardAllSnapshots, called from main.js's before-quit). Real gap found
// 2026-09-03: a snapshot from a real, live (and, that day, non-court-
// facing) camera was left behind when its calibration modal was closed
// without Save or Cancel actually running -- normally harmless leftover
// temp-file clutter, but a live camera snapshot can be a real, private
// frame, not just disposable data, so this shouldn't wait for the OS to
// eventually clean /tmp on its own.
const outstandingSnapshots = new Set();

export function grabSnapshot(camera) {
  const url = authenticatedStreamUri(camera);
  const outPath = path.join(os.tmpdir(), `pic-vision-snapshot-${camera.id}-${Date.now()}.png`);
  const args = ["-y", "-rtsp_transport", "tcp", "-i", url, "-frames:v", "1", "-f", "image2", outPath];
  const proc = spawn("ffmpeg", args, { stdio: ["ignore", "ignore", "pipe"] });
  let stderrTail = "";
  proc.stderr.on("data", (chunk) => {
    stderrTail = (stderrTail + chunk.toString()).slice(-4000);
  });

  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => proc.kill("SIGKILL"), SNAPSHOT_TIMEOUT_MS);
    proc.on("exit", (code) => {
      clearTimeout(timer);
      if (code !== 0 || !existsSync(outPath)) {
        reject(new Error(stderrTail.trim().split("\n").pop() || "Could not get a snapshot from the camera (timed out or offline)"));
        return;
      }
      outstandingSnapshots.add(outPath);
      resolve({ path: outPath, base64: readFileSync(outPath).toString("base64") });
    });
  });
}

export function discardSnapshot(snapshotPath) {
  outstandingSnapshots.delete(snapshotPath);
  try {
    if (snapshotPath) unlinkSync(snapshotPath);
  } catch {
    // best-effort cleanup of a tmpdir file -- not worth failing over
  }
}

// Called from main.js's before-quit, alongside stopAllRecordings -- a
// calibration snapshot abandoned mid-flow (window closed without Save or
// Cancel) shouldn't linger in /tmp indefinitely, especially one pulled
// from a real, live camera.
export function discardAllSnapshots() {
  for (const p of outstandingSnapshots) discardSnapshot(p);
}

// Sample-clip cameras (2026-09-03, ManualAddDialog's "sample clip" source
// type -- a real camera pointed at a real court hasn't reliably been
// available, see the day's progress notes) stand in for a live camera
// with a single uploaded video file. Calibration needs a frame from *that*
// file instead of a live RTSP pull -- `-ss` seeks before decoding (fast,
// no need to read the whole file), same `-frames:v 1` grab as
// grabSnapshot, same tmpdir output convention.
export function probeDuration(filePath) {
  const result = spawnSync("ffprobe", [
    "-v", "error", "-show_entries", "format=duration",
    "-of", "default=noprint_wrappers=1:nokey=1", filePath,
  ], { encoding: "utf8" });
  const seconds = parseFloat(result.stdout);
  return Number.isFinite(seconds) ? seconds : 0;
}

export function grabFrameFromFile(filePath, atSec) {
  const outPath = path.join(os.tmpdir(), `pic-vision-snapshot-${Date.now()}.png`);
  const args = ["-y", "-ss", String(atSec), "-i", filePath, "-frames:v", "1", "-f", "image2", outPath];
  const result = spawnSync("ffmpeg", args, { encoding: "utf8" });
  if (result.status !== 0 || !existsSync(outPath)) {
    const stderrTail = (result.stderr || "").trim().split("\n").pop();
    throw new Error(stderrTail || `Could not read a frame at ${atSec}s from ${path.basename(filePath)}`);
  }
  outstandingSnapshots.add(outPath);
  return { path: outPath, base64: readFileSync(outPath).toString("base64"), atSec };
}

export function isRecording(cameraId) {
  return active.has(cameraId);
}

export function recordingStatus(cameraId) {
  const rec = active.get(cameraId);
  return rec ? { recording: true, outDir: rec.outDir, startedAt: rec.startedAt } : { recording: false };
}

// How long to wait before trusting a start actually worked. Real gap
// found and fixed 2026-09-01: this used to return immediately after
// spawning, so a fast failure (wrong codec/container, bad auth, camera
// offline) reported "recording started" to the UI and then silently
// reverted to "Start recording" seconds later with no explanation once
// ffmpeg actually exited -- confusing, looked like a UI bug rather than
// a real, diagnosable ffmpeg error. Caught by testing against a real
// failure (the pcm_alaw/MP4 bug above), not assumed.
const STARTUP_GRACE_MS = 2000;

export function startRecording(camera) {
  if (active.has(camera.id)) throw new Error("Already recording this camera");

  const outDir = path.join(RECORDINGS_ROOT, sanitizeForPath(camera.label), new Date().toISOString().replace(/[:.]/g, "-"));
  mkdirSync(outDir, { recursive: true });

  const url = authenticatedStreamUri(camera);
  // .mkv, not TECH_SPEC.md §1.2's literal .mp4 -- real bug caught by
  // actually running this against a real camera (2026-09-01), not by
  // copying the spec's example verbatim: the Tapo C200 streams pcm_alaw
  // audio, and MP4 has no codec tag for that (ffmpeg: "Could not find
  // tag for codec pcm_alaw in stream #1... Could not write header").
  // TECH_SPEC.md's own prose already says pcm_alaw requires MKV -- its
  // filename in the example command just didn't reflect that. Confirmed
  // fixed against this exact camera: real 1080p h264+pcm_alaw file,
  // ffprobe-valid, before this was trusted.
  const args = [
    "-rtsp_transport", "tcp",
    "-i", url,
    "-use_wallclock_as_timestamps", "1",
    "-c", "copy",
    "-f", "segment",
    "-segment_time", "600",
    "-reset_timestamps", "1",
    path.join(outDir, "session-%03d.mkv"),
  ];

  const proc = spawn("ffmpeg", args, { stdio: ["ignore", "ignore", "pipe"] });
  const startedAt = new Date().toISOString();
  let stderrTail = "";
  proc.stderr.on("data", (chunk) => {
    stderrTail = (stderrTail + chunk.toString()).slice(-4000); // last ~4KB, enough for a real error
  });

  const record = { proc, outDir, startedAt, stderrTail: () => stderrTail };
  active.set(camera.id, record);

  return new Promise((resolve, reject) => {
    let started = false;
    const timer = setTimeout(() => {
      started = true;
      logEvent("recording_started", `Started recording ${camera.label}`, outDir);
      resolve({ outDir, startedAt });
    }, STARTUP_GRACE_MS);
    proc.on("exit", (code) => {
      // Only clear if this is still the tracked process for this camera --
      // a fast stop-then-restart could otherwise let a late exit event
      // from the OLD process clobber the NEW one's tracked state.
      if (active.get(camera.id) === record) active.delete(camera.id);
      clearTimeout(timer);
      // An exit after the grace period is stopRecording's own SIGINT --
      // expected, already logged there, not a failure. Only an exit
      // *before* the grace period ever resolved is a real start failure.
      if (started) return;
      const reason = stderrTail.trim().split("\n").pop() || `ffmpeg exited (code ${code})`;
      logEvent("recording_failed", `${camera.label} recording failed to start`, reason);
      reject(new Error(reason));
    });
  });
}

// Clean stop only -- SIGINT, never SIGKILL (ADR-031: a hard kill was
// observed to corrupt the output container). ffmpeg finalizes the
// current segment on SIGINT and exits on its own; this resolves once
// that actually happens rather than assuming it did.
export function stopRecording(cameraId) {
  const rec = active.get(cameraId);
  if (!rec) return Promise.resolve({ stopped: false });
  return new Promise((resolve) => {
    rec.proc.once("exit", () => {
      logEvent("recording_stopped", "Stopped recording", rec.outDir);
      resolve({ stopped: true, outDir: rec.outDir });
    });
    rec.proc.kill("SIGINT");
  });
}

export function stopAllRecordings() {
  return Promise.all([...active.keys()].map(stopRecording));
}

// Every past (and current) recording session for a camera -- PIC-68's
// cloud-pipeline trigger needs something to list and pick from, since
// nothing before this tracked recordings anywhere but the filesystem
// itself. One entry per outDir this module has ever created for this
// camera (sanitizeForPath(camera.label)/<ISO timestamp>/), newest first.
export function listRecordings(camera) {
  // A sample-clip camera (2026-09-03) has exactly one "recording": the
  // file it was added with. No segments, nothing to concatenate -- the
  // cloud-pipeline row's "dir" is just where cloud_job/ output lands
  // alongside it.
  if (camera.connectionType === "sampleClip") {
    if (!camera.sampleClipPath || !existsSync(camera.sampleClipPath)) return [];
    return [{
      name: path.basename(camera.sampleClipPath),
      dir: path.dirname(camera.sampleClipPath),
      segments: 1,
      recording: false,
    }];
  }

  const cameraDir = path.join(RECORDINGS_ROOT, sanitizeForPath(camera.label));
  if (!existsSync(cameraDir)) return [];
  const activeOutDir = active.get(camera.id)?.outDir;
  return readdirSync(cameraDir)
    .filter((name) => statSync(path.join(cameraDir, name)).isDirectory())
    .map((name) => {
      const dir = path.join(cameraDir, name);
      const segments = readdirSync(dir).filter((f) => /^session-\d+\.mkv$/.test(f));
      return { name, dir, segments: segments.length, recording: dir === activeOutDir };
    })
    .sort((a, b) => b.name.localeCompare(a.name));
}
