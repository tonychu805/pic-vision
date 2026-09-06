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
import { FFMPEG, FFPROBE } from "./binaries.js";
import { assertUsableFrameRate } from "./cameras/frameRate.js";

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
  const proc = spawn(FFMPEG, args, { stdio: ["ignore", "ignore", "pipe"] });
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
  const result = spawnSync(FFPROBE, [
    "-v", "error", "-show_entries", "format=duration",
    "-of", "default=noprint_wrappers=1:nokey=1", filePath,
  ], { encoding: "utf8" });
  const seconds = parseFloat(result.stdout);
  return Number.isFinite(seconds) ? seconds : 0;
}

// Reads what a stream is actually sending -- codec, resolution, frame rate
// and bitrate -- by sampling a few seconds of it.
//
// Needed because only ONVIF cameras report a profile. An RTSP-added camera
// and a sample clip have no such source, so without this they'd show
// nothing and, worse, skip the frame-rate guard entirely (ADR-087) -- the
// exact gap that lets a venue run at 15fps unnoticed.
//
// rtspProbe.js deliberately avoided decoding because bundling ffmpeg was
// "a real packaging concern for something shipped to venue owners"; that
// stopped being true when binaries.js started shipping it (ADR-084).
//
// Counting packets, never decoding frames: no pixels are read, so it stays
// cheap and can never produce an image (see the standing rule about not
// grabbing live frames from real cameras during testing). Bitrate comes
// from the packet sizes for the same reason -- a live stream usually
// reports no bit_rate in its container metadata at all.
//
// Async, not spawnSync: this holds a live connection for several seconds
// and the main process is single-threaded -- a sync version froze the whole
// UI, window controls included, for the duration.
export function measureStreamProfile(uri, { seconds = 5, timeoutMs = 20_000 } = {}) {
  const isLive = /^rtsps?:\/\//i.test(uri);
  return new Promise((resolve) => {
    const proc = spawn(FFPROBE, [
      "-v", "error",
      // Only meaningful for a live stream. A finished recording or an
      // uploaded sample clip is a plain file -- no transport, and it reads
      // in milliseconds rather than holding a connection open.
      ...(isLive ? ["-rtsp_transport", "tcp"] : []),
      "-i", uri,
      "-select_streams", "v:0",
      "-read_intervals", `%+${seconds}`,
      "-show_entries", "stream=codec_name,width,height:packet=pts_time,size",
      "-of", "json",
    ], { stdio: ["ignore", "pipe", "ignore"] });

    let out = "";
    const timer = setTimeout(() => proc.kill("SIGKILL"), timeoutMs);
    proc.stdout.on("data", (chunk) => { out += chunk.toString(); });
    proc.on("error", () => { clearTimeout(timer); resolve(null); });
    proc.on("close", () => {
      clearTimeout(timer);
      let parsed;
      try {
        parsed = JSON.parse(out);
      } catch {
        return resolve(null);
      }
      const stream = parsed.streams?.[0] ?? {};
      const packets = parsed.packets ?? [];
      const times = packets.map((pk) => Number(pk.pts_time))
        .filter((t) => Number.isFinite(t)).sort((a, b) => a - b);
      if (times.length < 10) return resolve(null); // too little to conclude anything

      const span = times[times.length - 1] - times[0];
      if (span <= 0) return resolve(null);
      const fps = (times.length - 1) / span;
      if (!(1 <= fps && fps <= 240)) return resolve(null);

      const bits = packets.reduce((sum, pk) => sum + (Number(pk.size) || 0), 0) * 8;
      const positive = (v) => (Number.isFinite(v) && v > 0 ? v : null);
      resolve({
        codec: stream.codec_name ? String(stream.codec_name).toUpperCase() : null,
        width: positive(Number(stream.width)),
        height: positive(Number(stream.height)),
        fps: Math.round(fps * 100) / 100,
        bitrateKbps: positive(Math.round(bits / span / 1000)),
      });
    });
  });
}

// Frame rate alone, for callers that only need to re-check that one number
// (a finished recording, or topping up an ONVIF camera that reports
// everything except its rate).
export async function measureStreamFps(uri, opts) {
  return (await measureStreamProfile(uri, opts))?.fps ?? null;
}


// The most recently written segment of a finished session, for measuring
// the frame rate actually captured. Null when nothing landed (a recording
// that failed immediately).
export function newestSegment(outDir) {
  try {
    const segs = readdirSync(outDir).filter((f) => /^session-\d+\.mkv$/.test(f)).sort();
    return segs.length ? path.join(outDir, segs[segs.length - 1]) : null;
  } catch {
    return null;
  }
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
