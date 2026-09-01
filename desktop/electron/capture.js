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
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import os from "node:os";

const RECORDINGS_ROOT = path.join(os.homedir(), "pic-vision-recordings");

// cameraId -> { proc, outDir, startedAt }. Module-level, not per-window --
// a recording must survive the renderer navigating away from this
// camera's detail page (it's a background process, not tied to any
// particular page being open).
const active = new Map();

function sanitizeForPath(label) {
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
    const timer = setTimeout(() => resolve({ outDir, startedAt }), STARTUP_GRACE_MS);
    proc.on("exit", (code) => {
      // Only clear if this is still the tracked process for this camera --
      // a fast stop-then-restart could otherwise let a late exit event
      // from the OLD process clobber the NEW one's tracked state.
      if (active.get(camera.id) === record) active.delete(camera.id);
      clearTimeout(timer);
      reject(new Error(stderrTail.trim().split("\n").pop() || `ffmpeg exited (code ${code})`));
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
    rec.proc.once("exit", () => resolve({ stopped: true, outDir: rec.outDir }));
    rec.proc.kill("SIGINT");
  });
}

export function stopAllRecordings() {
  return Promise.all([...active.keys()].map(stopRecording));
}
