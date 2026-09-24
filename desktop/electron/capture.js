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
import { listParts } from "./autoSplit.js";
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

// Only the legacy layout below still needs this -- kept exported for
// store.js's one-time migration off it.
export function sanitizeForPath(label) {
  return label.replace(/[^a-zA-Z0-9._-]+/g, "_").replace(/^_+|_+$/g, "") || "camera";
}

// Where one camera's recordings live: RECORDINGS_ROOT/<camera id>/<ISO
// timestamp>/.
//
// Keyed by id since 2026-09-18. It was keyed by sanitizeForPath(label),
// which meant a rename silently pointed both startRecording and
// listRecordings at a directory that did not exist yet: every past
// recording disappeared from the camera's page, taking its "Send to cloud"
// row with it, while the files sat on disk under the old name with nothing
// saying so. Two cameras sharing a label also shared one directory, which
// had already caused a real bug once (the Court 3 sample clip).
//
// The label is what an operator recognises, so this trades some
// browsing-the-disk legibility for a path that survives a rename. The app
// shows the real path on the camera's own page; store.js's
// migrateRecordingDirsToCameraIds() moves directories created under the old
// layout across, once, at startup.
export function cameraRecordingsDir(camera) {
  return path.join(RECORDINGS_ROOT, camera.id);
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

// How many frames actually arrived per second, from raw packet timestamps.
//
// Replaces a median-of-gaps estimate (`fps = 1 / median(gap)`) that was
// chosen to solve one real problem and turned out to create a worse one.
//
// The problem it solved: an RTSP stream ramps up, so the first second
// carries fewer packets while the connection settles. Averaging naively
// over that (frames / total span) under-read a genuine 30fps camera as
// 24.9 -- reported to a venue as "your network is dropping frames" when
// nothing was wrong. The median ignores that slow start, since it only
// cares which gap is typical, not how many outliers surround it.
//
// The problem it created: a median is blind to a BIMODAL gap pattern, and
// picks whichever gap is more common rather than the true average. A
// stream whose packet spacing genuinely alternates -- 20ms, 47ms, 20ms,
// 47ms, averaging 33.3ms per frame, a true ~30fps -- has its median sitting
// on the 20ms side, reading ~50fps. Found live: Diagnostics measured the
// same physical camera (declaring 30fps the entire time) at 51.55fps one
// heartbeat and 49fps a few hours later, on a camera nothing else suggests
// is actually running that fast (PIC-150, 2026-09-18).
//
// The fix keeps the slow-start correction but gets it from trimming a
// warm-up window off the front, not from picking a "typical" gap: discard
// the packets within WARMUP_SEC of the very first one, then take frames
// over the remaining span. Frames-over-span is immune to the ORDER of
// gaps -- an alternating 20/47ms pattern and a steady 33.3ms pattern give
// the same answer, because both spend the same total time on the same
// number of frames. Only trims when there's enough left to be confident;
// a short probe isn't crippled by discarding a whole second of it.
//
// A genuine stall in the middle of the sample (not at the start) still
// pulls the reading down under this method, where a median would have
// hidden it entirely -- treated as correct behaviour, not a regression:
// frames that didn't arrive are exactly what this number exists to catch.
const WARMUP_SEC = 1.0;
const MIN_TRIMMED_SPAN_SEC = 2.0;
const MIN_TRIMMED_PACKETS = 10;

export function estimateFpsFromPacketTimes(times) {
  if (!Array.isArray(times) || times.length < 10) return null;
  const sorted = [...times].sort((a, b) => a - b);
  const totalSpan = sorted[sorted.length - 1] - sorted[0];
  if (!(totalSpan > 0)) return null;

  const warmupCutoff = sorted[0] + WARMUP_SEC;
  const trimmed = sorted.filter((t) => t >= warmupCutoff);
  const trimmedSpan = trimmed.length ? trimmed[trimmed.length - 1] - trimmed[0] : 0;
  const useTrimmed = trimmed.length >= MIN_TRIMMED_PACKETS && trimmedSpan >= MIN_TRIMMED_SPAN_SEC;

  const sample = useTrimmed ? trimmed : sorted;
  const span = useTrimmed ? trimmedSpan : totalSpan;
  if (!(span > 0)) return null;

  const fps = (sample.length - 1) / span;
  return 1 <= fps && fps <= 240 ? fps : null;
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

      // See estimateFpsFromPacketTimes's own comment for why this isn't a
      // median-of-gaps anymore (PIC-150): that estimate read a steady
      // ~30fps camera as high as 51.55fps when its packet spacing happened
      // to alternate rather than stay even.
      const fps = estimateFpsFromPacketTimes(times);
      if (fps == null) return resolve(null);

      const bits = packets.reduce((sum, pk) => sum + (Number(pk.size) || 0), 0) * 8;
      // The window those bits arrived over. Restored 2026-09-19: PIC-150
      // moved the fps maths into estimateFpsFromPacketTimes and deleted
      // this line with the old estimator, but the bitrate below still
      // referenced it -- so every call threw `ReferenceError: span is not
      // defined` from inside the ffprobe close handler, where nothing
      // catches it, and the packaged app died on launch with an uncaught
      // exception dialog.
      //
      // Deliberately the TOTAL span, not the trimmed one the fps estimate
      // uses: `bits` counts every packet, so pairing it with a window that
      // drops the first second would over-report the rate.
      const span = times[times.length - 1] - times[0];
      const positive = (v) => (Number.isFinite(v) && v > 0 ? v : null);
      resolve({
        codec: stream.codec_name ? String(stream.codec_name).toUpperCase() : null,
        width: positive(Number(stream.width)),
        height: positive(Number(stream.height)),
        fps: Math.round(fps * 100) / 100,
        // A zero-length span drops the bitrate alone rather than the whole
        // profile. The old code bailed out of the entire measurement on
        // `span <= 0`, taking codec/resolution/fps with it; those are
        // perfectly good without it, and fps has its own guard now.
        bitrateKbps: span > 0 ? positive(Math.round(bits / span / 1000)) : null,
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


export function grabFrameFromFile(filePath, atSec) {
  const outPath = path.join(os.tmpdir(), `pic-vision-snapshot-${Date.now()}.png`);
  const args = ["-y", "-ss", String(atSec), "-i", filePath, "-frames:v", "1", "-f", "image2", outPath];
  const result = spawnSync(FFMPEG, args, { encoding: "utf8" });
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

// A camera stream that drops mid-game (Wi-Fi blip, router or camera
// restart) used to end the recording for good: ffmpeg exited, nothing
// restarted it, nothing said so, and the rest of the game was lost
// (found 2026-09-24). Now the recording reconnects on its own, into the
// same folder, numbering on from the last piece, so the game keeps its one
// session and one link; it keeps trying until the recording is stopped.
export const RECONNECT_DELAYS_MS = [5_000, 10_000, 20_000, 30_000]; // then every 30s
// Treated as reconnected once a restarted ffmpeg has run this long.
const RECONNECTED_AFTER_MS = 10_000;
// ffmpeg gives up on a stream that goes silent after this, instead of
// hanging forever on a dead TCP connection (rtsp demuxer -timeout, in
// microseconds; ffmpeg 5+).
const STREAM_TIMEOUT_US = 15_000_000;

export function reconnectDelayMs(attempt) {
  return RECONNECT_DELAYS_MS[Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)];
}

/** The number the next piece of a recording should get: one after the highest there. */
export function nextSegmentNumber(fileNames) {
  let max = -1;
  for (const f of fileNames) {
    const m = /^session-(\d+)\.mkv$/.exec(f);
    if (m) max = Math.max(max, Number(m[1]));
  }
  return max + 1;
}

function spawnSegmenter(camera, record) {
  const url = authenticatedStreamUri(camera);
  const start = nextSegmentNumber(existsSync(record.outDir) ? readdirSync(record.outDir) : []);
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
    "-timeout", String(STREAM_TIMEOUT_US),
    "-i", url,
    "-use_wallclock_as_timestamps", "1",
    "-c", "copy",
    "-f", "segment",
    "-segment_time", "600",
    "-segment_start_number", String(start),
    "-reset_timestamps", "1",
    path.join(record.outDir, "session-%03d.mkv"),
  ];
  const proc = spawn(FFMPEG, args, { stdio: ["ignore", "ignore", "pipe"] });
  record.proc = proc;
  record.stderrTail = "";
  proc.stderr.on("data", (chunk) => {
    record.stderrTail = (record.stderrTail + chunk.toString()).slice(-4000); // last ~4KB, enough for a real error
  });
  return proc;
}

function lastError(record, code) {
  return record.stderrTail.trim().split("\n").pop() || `ffmpeg exited (code ${code})`;
}

// The stream dropped after the recording had started: log it once, then
// retry until it comes back or the recording is stopped.
function reconnect(camera, record, reason, attempt = 0) {
  if (record.stopping) return;
  if (attempt === 0) {
    record.interruptions += 1;
    logEvent("recording_interrupted", `${camera.label} lost its camera stream -- reconnecting`, reason);
  }
  record.proc = null;
  record.retryTimer = setTimeout(() => {
    record.retryTimer = null;
    if (record.stopping) return;
    const proc = spawnSegmenter(camera, record);
    const healthy = setTimeout(() => {
      if (record.proc === proc && !record.stopping) {
        logEvent("recording_resumed", `${camera.label} is recording again`, record.outDir);
      }
    }, RECONNECTED_AFTER_MS);
    const startedAt = Date.now();
    proc.on("exit", (code) => {
      clearTimeout(healthy);
      if (record.proc !== proc || record.stopping) return;
      // Ran a while, then dropped again: a new interruption. Died straight
      // away: the camera still isn't there -- keep trying, a bit slower.
      if (Date.now() - startedAt >= RECONNECTED_AFTER_MS) reconnect(camera, record, lastError(record, code), 0);
      else reconnect(camera, record, lastError(record, code), attempt + 1);
    });
  }, reconnectDelayMs(attempt));
}

export function startRecording(camera) {
  if (active.has(camera.id)) throw new Error("Already recording this camera");
  // Refuse rather than record footage the pipeline can't get rallies out
  // of -- a low frame rate halves detection and would otherwise fail
  // silently, hours later, as a thin reel with no explanation.
  assertUsableFrameRate(camera);

  const outDir = path.join(cameraRecordingsDir(camera), new Date().toISOString().replace(/[:.]/g, "-"));
  mkdirSync(outDir, { recursive: true });

  const startedAt = new Date().toISOString();
  const record = { proc: null, outDir, startedAt, stderrTail: "", stopping: false, retryTimer: null, interruptions: 0 };
  const proc = spawnSegmenter(camera, record);
  active.set(camera.id, record);

  return new Promise((resolve, reject) => {
    let started = false;
    const timer = setTimeout(() => {
      started = true;
      logEvent("recording_started", `Started recording ${camera.label}`, outDir);
      resolve({ outDir, startedAt });
    }, STARTUP_GRACE_MS);
    proc.on("exit", (code) => {
      clearTimeout(timer);
      if (record.proc !== proc || record.stopping) return; // stopRecording's own SIGINT, or already replaced
      if (started) {
        // Dropped mid-recording: reconnect, same folder, same session.
        reconnect(camera, record, lastError(record, code));
        return;
      }
      // Died before the grace period: a real start failure (bad address,
      // wrong password, camera offline) -- say so rather than retry.
      if (active.get(camera.id) === record) active.delete(camera.id);
      const reason = lastError(record, code);
      logEvent("recording_failed", `${camera.label} recording failed to start`, reason);
      reject(new Error(reason));
    });
  });
}

// Clean stop only -- SIGINT, never SIGKILL (ADR-031: a hard kill was
// observed to corrupt the output container). ffmpeg finalizes the
// current segment on SIGINT and exits on its own; this resolves once
// that actually happens rather than assuming it did. A recording that is
// between reconnect attempts has no ffmpeg running: it just stops trying.
export function stopRecording(cameraId) {
  const rec = active.get(cameraId);
  if (!rec) return Promise.resolve({ stopped: false });
  rec.stopping = true;
  if (rec.retryTimer) clearTimeout(rec.retryTimer);
  const finish = () => {
    if (active.get(cameraId) === rec) active.delete(cameraId);
    logEvent("recording_stopped", "Stopped recording", rec.outDir);
    // Free, and better evidence than probing the live stream: this is
    // exactly what got captured and what the pipeline will be given. Also
    // how an RTSP camera's rate stays current after someone changes it in
    // the camera's own settings -- nothing else would ever notice.
    return { stopped: true, outDir: rec.outDir, measureFrom: newestSegment(rec.outDir) };
  };
  const proc = rec.proc;
  if (!proc || proc.exitCode !== null || proc.signalCode !== null) return Promise.resolve(finish());
  return new Promise((resolve) => {
    proc.once("exit", () => resolve(finish()));
    proc.kill("SIGINT");
  });
}

/** Where a camera is recording right now, or null. */
export function activeOutDir(cameraId) {
  return active.get(cameraId)?.outDir ?? null;
}

export function stopAllRecordings() {
  return Promise.all([...active.keys()].map(stopRecording));
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
// camera (cameraRecordingsDir(camera)/<ISO timestamp>/), newest first.
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

  const cameraDir = cameraRecordingsDir(camera);
  if (!existsSync(cameraDir)) return [];
  const activeOutDir = active.get(camera.id)?.outDir;
  return readdirSync(cameraDir)
    .filter((name) => statSync(path.join(cameraDir, name)).isDirectory())
    .map((name) => {
      const dir = path.join(cameraDir, name);
      const segments = readdirSync(dir).filter((f) => /^session-\d+\.mkv$/.test(f));
      // Parts auto-split has already sent (autoSplit.js): each is its own
      // cloud job, so the screen shows one row per part instead of the
      // whole recording's single Send button.
      const parts = listParts(dir).map((p) => ({ name: p.name, dir: p.dir, segments: p.segments.length, recording: false }));
      return { name, dir, segments: segments.length, recording: dir === activeOutDir, parts };
    })
    .sort((a, b) => b.name.localeCompare(a.name));
}
