// Hands a finished recording to the cloud for processing (ADR-084).
//
// This used to spawn cloud_pipeline/run_desktop_job.py, which ran the
// whole RunPod orchestration right here on the venue's machine -- which
// meant the operator's R2 and RunPod credentials had to be sitting on
// every venue laptop. That's exactly what STRATEGY.md §5 and PIC-71 ruled
// out for a client shipped to someone else, and it's why this app could
// never be packaged. Now the agent only ever: asks the console for a job,
// uploads the raw recording segments to the presigned URLs it gets back,
// and polls for progress. The pipeline itself runs on the operator's own
// machine (cloud_pipeline/job_runner.py), which is the only place the
// cloud credentials live.
//
// The status.json contract is deliberately unchanged: this still writes
// <recordingDir>/cloud_job/status.json with the same stage/message/
// progress shape webapp/pipeline.py produces, and the console's job row
// mirrors those same fields -- so main.js's pipeline:status handler and
// the renderer's CloudJobRow keep working without knowing any of this
// moved. Two stages are new and local to this file: "upload" (this
// machine sending the video) and "queued" (waiting for a runner).
import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { powerSaveBlocker } from "electron";
import { consoleFetch, requireConnection, uploadFile } from "./consoleApi.js";
import { logEvent } from "./activityLog.js";

const SEGMENT_RE = /^session-\d+\.mkv$/;
const POLL_INTERVAL_MS = 5_000;
const UPLOAD_RETRIES = 3;
const TERMINAL = new Set(["done", "error", "cancelled"]);

// recordingDir -> { jobId, cancelled }. Keyed by the recording's own
// directory (== capture.js's per-session outDir) rather than sessionId
// alone, since that's also where status.json ends up (in a cloud_job/
// subdirectory) and where a second "send to cloud" click for the same
// recording needs to be refused. Same module-level-Map shape capture.js
// uses, and for the same reason: a job must survive the renderer
// navigating away from this camera's detail page.
const active = new Map();

export function isPipelineRunning(recordingDir) {
  return active.has(recordingDir);
}

export function pipelineStatus(jobDir) {
  const statusPath = path.join(jobDir, "status.json");
  if (!existsSync(statusPath)) return { stage: null };
  try {
    return JSON.parse(readFileSync(statusPath, "utf8"));
  } catch {
    // A torn read against writeStatus's rename is not worth surfacing as
    // a job failure -- the next poll tick reads a whole file.
    return { stage: null };
  }
}

export function pipelineStatusForRecording(recordingDir) {
  return pipelineStatus(path.join(recordingDir, "cloud_job"));
}

// Atomic (write + rename), same as webapp/pipeline.py's _set_status: the
// renderer polls this file on its own timer and must never catch a
// half-written one.
function writeStatus(jobDir, fields) {
  const current = pipelineStatus(jobDir);
  const next = { ...current, ...fields };
  const tmp = path.join(jobDir, "status.json.tmp");
  writeFileSync(tmp, JSON.stringify(next, null, 2));
  renameSync(tmp, path.join(jobDir, "status.json"));
  return next;
}

function segmentsIn(recordingDir) {
  return readdirSync(recordingDir)
    .filter((f) => SEGMENT_RE.test(f))
    .sort()
    .map((f) => path.join(recordingDir, f));
}

async function uploadWithRetry(jobId, upload, filePath, onProgress) {
  let url = upload.url;
  for (let attempt = 1; ; attempt++) {
    try {
      return await uploadFile(url, filePath, onProgress);
    } catch (err) {
      // A 403 here is almost always an expired signature rather than a
      // real permission problem -- a venue on slow Wi-Fi can take longer
      // to push a session than the URL's lifetime. Ask for a fresh one
      // before spending a retry on the same dead URL.
      if (err.status === 403) {
        const refreshed = await consoleFetch(`/api/agents/jobs/${jobId}`, {
          method: "PATCH",
          body: { action: "refresh" },
        });
        const match = refreshed.uploads?.find((u) => u.name === upload.name);
        if (match) url = match.url;
      }
      if (attempt >= UPLOAD_RETRIES) throw err;
      await new Promise((r) => setTimeout(r, 2000 * attempt));
    }
  }
}

async function uploadSegments(jobId, uploads, files, jobDir) {
  const sizes = files.map((f) => statSync(f).size);
  const grandTotal = sizes.reduce((a, b) => a + b, 0);
  let done = 0;

  for (let i = 0; i < files.length; i++) {
    const name = path.basename(files[i]);
    const upload = uploads.find((u) => u.name === name);
    if (!upload) throw new Error(`the console didn't issue an upload for ${name}`);
    writeStatus(jobDir, {
      stage: "upload",
      message: `uploading ${name} (${i + 1} of ${files.length})...`,
    });
    await uploadWithRetry(jobId, upload, files[i], (sent) => {
      writeStatus(jobDir, { progress: { current: done + sent, total: grandTotal, eta_sec: null } });
    });
    done += sizes[i];
  }
}

// Mirrors the console's view of the job into the local status.json until
// it reaches a terminal state. Runs detached from the caller (nothing
// awaits it) -- the renderer follows along by polling status.json, the
// same way it followed the Python subprocess before.
async function pollUntilDone(recordingDir, jobDir, jobId, label) {
  for (;;) {
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
    let job;
    try {
      ({ job } = await consoleFetch(`/api/agents/jobs/${jobId}`));
    } catch (err) {
      // Console unreachable: keep the job alive and try again. A venue's
      // internet dropping shouldn't fail a job that's running fine on the
      // operator's machine.
      console.error(`[pipeline] status poll failed: ${err.message}`);
      continue;
    }

    writeStatus(jobDir, {
      stage: job.stage ?? job.status,
      message: job.message ?? null,
      progress: job.progress ?? null,
      error: job.error ?? null,
      done: job.status === "done",
      ...(job.result ?? {}),
    });

    if (!TERMINAL.has(job.status)) continue;

    active.delete(recordingDir);
    if (job.status === "done") {
      const reels = job.result?.reels ?? [];
      const full = reels.find((r) => r.kind === "full") ?? reels[0];
      const stats = full?.stats;
      const detail = stats ? `${stats.n_chosen} rallies, ${Math.round(stats.total_duration_sec)}s` : null;
      logEvent("pipeline_done", `${label} reel ready`, detail);
    } else if (job.status === "cancelled") {
      logEvent("pipeline_failed", `${label} cloud job cancelled`);
    } else {
      logEvent("pipeline_failed", `${label} cloud job failed`, job.error || job.message || null);
    }
    return;
  }
}

// `videoPath`, when given, skips the session-*.mkv lookup -- a sample-clip
// camera (2026-09-03) already has a single, real video file.
//
// No calibPath argument anymore: the camera's calibration lives on its
// console row since ADR-084, and the console attaches it to the job. That
// also means an uncalibrated camera is refused by the console with a real
// message rather than by a local file check.
export async function runCloudJob({ recordingDir, videoPath, targetSec, sessionId, cameraId, cameraLabel }) {
  if (active.has(recordingDir)) throw new Error("A cloud job is already running for this recording");
  const connection = requireConnection();

  const files = videoPath ? [videoPath] : segmentsIn(recordingDir);
  if (files.length === 0) throw new Error(`No recording segments found in ${recordingDir}`);
  for (const f of files) {
    if (!existsSync(f)) throw new Error(`No video file at ${f}`);
  }

  const jobDir = path.join(recordingDir, "cloud_job");
  mkdirSync(jobDir, { recursive: true });
  const label = cameraLabel || "camera";

  writeStatus(jobDir, {
    stage: "upload",
    message: "preparing upload...",
    progress: null,
    error: null,
    done: false,
  });

  const { jobId, uploads } = await consoleFetch("/api/agents/jobs", {
    method: "POST",
    connection,
    body: {
      sessionId,
      cameraId,
      cameraLabel,
      targetSec: targetSec || 180,
      files: files.map((f) => ({ name: path.basename(f), sizeBytes: statSync(f).size })),
    },
  });

  active.set(recordingDir, { jobId });
  writeFileSync(path.join(jobDir, "job.json"), JSON.stringify({ jobId, sessionId }, null, 2));
  logEvent("pipeline_started", `Sent ${label} to the cloud`);

  // Uploading a two-hour session takes a while; without this the Mac can
  // sleep mid-transfer and the job sits half-uploaded until it expires.
  const blocker = powerSaveBlocker.start("prevent-app-suspension");
  try {
    await uploadSegments(jobId, uploads, files, jobDir);
    await consoleFetch(`/api/agents/jobs/${jobId}`, { method: "PATCH", body: { action: "complete" } });
  } catch (err) {
    active.delete(recordingDir);
    writeStatus(jobDir, { stage: "error", message: "upload failed", error: err.message, done: false });
    logEvent("pipeline_failed", `${label} upload failed`, err.message);
    throw err;
  } finally {
    powerSaveBlocker.stop(blocker);
  }

  writeStatus(jobDir, { stage: "queued", message: "waiting for processing", progress: null });
  pollUntilDone(recordingDir, jobDir, jobId, label).catch((err) => {
    active.delete(recordingDir);
    console.error(`[pipeline] polling stopped: ${err.message}`);
  });

  return { jobDir };
}

export function cancelCloudJob(recordingDir) {
  const rec = active.get(recordingDir);
  if (!rec) return { cancelled: false };
  // Fire-and-forget: the console flips a queued job straight to cancelled
  // and, for a running one, asks the runner to terminate its RunPod pod
  // (which is what actually stops the billing). Either way the poll loop
  // above sees the terminal state and cleans up.
  consoleFetch(`/api/agents/jobs/${rec.jobId}`, { method: "PATCH", body: { action: "cancel" } }).catch((err) =>
    console.error(`[pipeline] cancel failed: ${err.message}`),
  );
  return { cancelled: true };
}
