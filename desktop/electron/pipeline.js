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
import { sessionFieldsFor } from "./autoSplit.js";
import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { powerSaveBlocker } from "electron";
import { consoleFetch, requireConnection, uploadFile } from "./consoleApi.js";
import { logEvent } from "./activityLog.js";

const SEGMENT_RE = /^session-\d+\.mkv$/;
// Overridable only so a test can watch several polls without waiting a
// minute; nothing else sets it. Same seam auth.js and cloud.js already have
// for their endpoints.
const POLL_INTERVAL_MS = Number(process.env.PIC_VISION_POLL_INTERVAL_MS) || 5_000;
const UPLOAD_RETRIES = 3;
const TERMINAL = new Set(["done", "error", "cancelled"]);

// recordingDir -> { jobId, label, cancelled, abort }. Keyed by the recording's own
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
  const status = pipelineStatus(path.join(recordingDir, "cloud_job"));
  resumeFollowing(recordingDir, status);
  return status;
}

// Make sure a job that is still alive in the cloud is being FOLLOWED.
//
// status.json is only ever advanced by pollUntilDone, and pollUntilDone was
// started from exactly two places: the moment an upload finished, and the
// moment Cancel was clicked. Nothing restarted it when the app launched. So
// if the app was closed or restarted after a job was sent, the file froze
// at whatever it last said -- and for a cancel that was "Stopping…", with
// the Cancel button hidden and no Retry, permanently (reported 2026-09-20).
// The console had long since said `cancelled`; nothing was asking.
//
// It lives on the READ path because the renderer already asks for this
// every 2 seconds for every visible row, so a row that matters is
// re-examined without a startup scan that would have to know which rows
// those are. It also covers a poll loop that died for any other reason.
//
// What it will not resume:
//   - a terminal status: finished, nothing to follow.
//   - "upload": the transfer died with the process that was doing it, so
//     following the console would mirror a job that can never advance. That
//     is a real problem of its own and not this one.
//   - a recording with no job.json: nothing to follow.
function resumeFollowing(recordingDir, status) {
  if (!status.stage || TERMINAL.has(status.stage) || status.stage === "upload") return;
  if (active.has(recordingDir)) return;
  const rec = recoverJobRecord(recordingDir);
  if (!rec) return;
  active.set(recordingDir, rec);
  pollUntilDone(recordingDir, path.join(recordingDir, "cloud_job"), rec.jobId, rec.label).catch((err) => {
    active.delete(recordingDir);
    console.error(`[pipeline] polling stopped: ${err.message}`);
  });
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

async function uploadWithRetry(jobId, upload, filePath, onProgress, rec) {
  let url = upload.url;
  for (let attempt = 1; ; attempt++) {
    try {
      return await uploadFile(url, filePath, onProgress, rec?.abort?.signal);
    } catch (err) {
      // A cancel is not a transport failure. Without this the retry loop
      // would helpfully start the very transfer the operator just stopped,
      // twice, and the `refresh` below would 409 on the now-cancelled job.
      if (err.aborted || rec?.cancelled) throw err;
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

async function uploadSegments(jobId, uploads, files, jobDir, rec) {
  const sizes = files.map((f) => statSync(f).size);
  const grandTotal = sizes.reduce((a, b) => a + b, 0);
  let done = 0;

  for (let i = 0; i < files.length; i++) {
    // Checked per segment as well as mid-transfer (the abort signal
    // below): a cancel that lands in the gap between two segments has no
    // in-flight request to tear down, and used to sail straight into the
    // next one.
    if (rec?.cancelled) throw cancelledError();
    const name = path.basename(files[i]);
    const upload = uploads.find((u) => u.name === name);
    if (!upload) throw new Error(`the console didn't issue an upload for ${name}`);
    writeStatus(jobDir, {
      stage: "upload",
      message: `uploading ${name} (${i + 1} of ${files.length})...`,
    });
    await uploadWithRetry(jobId, upload, files[i], (sent) => {
      writeStatus(jobDir, { progress: { current: done + sent, total: grandTotal, eta_sec: null } });
    }, rec);
    done += sizes[i];
  }
}

function cancelledError() {
  return Object.assign(new Error("upload cancelled"), { aborted: true });
}

// Serializes the actual byte transfer across DIFFERENT recordings/cameras
// on this machine (2026-09-22) -- `active`'s per-recordingDir guard above
// only ever stopped the SAME recording being sent twice. A venue's uplink
// is one shared, often thin pipe (ADR-092 measured it bimodal, roughly 3.5
// vs. 30 Mbps), and running two uploads on it at once was tested to slow
// both down rather than add real throughput -- the machine sits otherwise
// idle during an upload anyway, so there is nothing to gain by racing them.
// Only uploadSegments() itself queues: creating the job on the console
// (the fetch just above) and the post-upload wait for the runner/pod are
// unaffected, so a second camera's job still exists and starts moving the
// moment its turn at the wire comes up, not after the first job's entire
// pipeline finishes.
let uploadQueueLength = 0;
let uploadQueueTail = Promise.resolve();

export function withUploadSlot(fn, onWaiting) {
  uploadQueueLength++;
  if (uploadQueueLength > 1) onWaiting?.();
  const ahead = uploadQueueTail;
  const run = ahead.then(fn, fn);
  // The chain's own tail must settle regardless of this upload's outcome --
  // otherwise one failed upload would permanently wedge every later one
  // behind a rejected promise. `run` itself, returned below, is what a
  // caller awaits for its OWN real result/rejection; this is a second,
  // separate consumer of it, not a `.finally()` (whose own returned
  // promise would go unhandled if the caller never happens to check it,
  // which is exactly the shape of "unhandled rejection" this queue must
  // never itself cause).
  uploadQueueTail = run.then(
    () => { uploadQueueLength--; },
    () => { uploadQueueLength--; },
  );
  return run;
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
      // The console says this job does not exist -- for THIS agent, which
      // also covers a machine moved to another venue (ADR-094). Nothing
      // will ever change that, so polling on would just burn a cloud
      // function call every few seconds forever, per row, for a job that
      // is not there. Only a 404 ends it: a 5xx or a dropped connection
      // says nothing about the job, and a venue's internet dropping
      // shouldn't fail a job that's running fine.
      if (err.status === 404) {
        active.delete(recordingDir);
        writeStatus(jobDir, {
          stage: "error",
          message: "this job no longer exists on the console",
          error: err.message,
          progress: null,
          done: false,
        });
        logEvent("pipeline_failed", `${label} cloud job not found on the console`);
        return;
      }
      // Console unreachable: keep the job alive and try again.
      console.error(`[pipeline] status poll failed: ${err.message}`);
      continue;
    }

    // A pod that has been asked to stop keeps reporting whatever stage it
    // is on until it actually stops, so mirroring that verbatim would
    // replace "Stopping..." with "Running TrackNet inference" one tick
    // after the operator hit Cancel -- looking, again, like the button did
    // nothing. The console's own cancel_requested flag is the honest thing
    // to show until a terminal state arrives.
    const stopping = job.cancel_requested && !TERMINAL.has(job.status);
    writeStatus(jobDir, {
      stage: stopping ? "cancelling" : job.stage ?? job.status,
      message: stopping ? "stopping..." : job.message ?? null,
      progress: stopping ? null : job.progress ?? null,
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
      // The playing session and part this upload belongs to (ADR-128), so
      // the console puts every part's reels on one share page. Empty for a
      // recording without a console-issued session.
      ...sessionFieldsFor(recordingDir, files),
    },
  });

  const rec = { jobId, label, cancelled: false, abort: new AbortController() };
  active.set(recordingDir, rec);
  writeFileSync(path.join(jobDir, "job.json"), JSON.stringify({ jobId, sessionId, label }, null, 2));
  logEvent("pipeline_started", `Sent ${label} to the cloud`);

  // Uploading a two-hour session takes a while; without this the Mac can
  // sleep mid-transfer and the job sits half-uploaded until it expires.
  const blocker = powerSaveBlocker.start("prevent-app-suspension");
  try {
    await withUploadSlot(
      () => uploadSegments(jobId, uploads, files, jobDir, rec),
      () => writeStatus(jobDir, { message: "waiting for another upload to finish..." }),
    );
    // A cancel landing in the gap between the last segment and this call
    // would otherwise ask the console to queue a job it has already
    // cancelled -- which answers 409, and used to surface as "upload
    // failed" several minutes after the operator pressed Cancel.
    if (rec.cancelled) throw cancelledError();
    await consoleFetch(`/api/agents/jobs/${jobId}`, { method: "PATCH", body: { action: "complete" } });
  } catch (err) {
    active.delete(recordingDir);
    // A stop the operator asked for is not a failure and must not be
    // reported as one. Nothing else will write this: pollUntilDone (the
    // only other writer of a terminal state) doesn't start until the
    // upload has finished, which is exactly what just didn't happen.
    if (rec.cancelled || err.aborted) {
      writeStatus(jobDir, { stage: "cancelled", message: "cancelled", progress: null, error: null, done: false });
      logEvent("pipeline_failed", `${label} cloud job cancelled`);
      return { jobDir, cancelled: true };
    }
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

/**
 * The job id for a recording whose upload this process isn't running --
 * after a restart, `active` is empty but the job is still very much alive
 * in the cloud. job.json has held the id on disk all along; nothing read
 * it back, so Cancel silently did nothing in exactly the situation where
 * the operator has least other recourse.
 */
function recoverJobRecord(recordingDir) {
  const jobPath = path.join(recordingDir, "cloud_job", "job.json");
  if (!existsSync(jobPath)) return null;
  try {
    const { jobId, label } = JSON.parse(readFileSync(jobPath, "utf8"));
    return jobId ? { jobId, label: label || "camera" } : null;
  } catch {
    return null;
  }
}

/**
 * Stop a job, locally and in the cloud, in that order.
 *
 * Local first, deliberately. The upload is the half that spends the
 * venue's uplink, and until 2026-09-19 nothing stopped it: Cancel told the
 * console (which did cancel the row, correctly) and then the agent
 * uploaded every remaining segment anyway, several gigabytes of them, and
 * finally reported "upload failed" when `complete` 409'd against the
 * cancelled job. From the operator's side the button did nothing for
 * minutes and then lied about why it stopped.
 *
 * Awaited rather than fire-and-forget so the answer can be acted on: a job
 * already running on a pod only gets a cancel *request* (the pod reports
 * the real terminal state back), while anything earlier is cancelled
 * outright -- and those two deserve different words on screen.
 */
export async function cancelCloudJob(recordingDir) {
  const jobDir = path.join(recordingDir, "cloud_job");
  const rec = active.get(recordingDir) ?? recoverJobRecord(recordingDir);
  if (!rec?.jobId) return { cancelled: false };

  rec.cancelled = true;
  rec.abort?.abort(); // tears down the segment currently in flight

  // Immediately, before the network call: the operator pressed a button
  // and has to see it take. Not "cancelled" yet -- a job on a pod hasn't
  // actually stopped until the pod says so, and claiming otherwise is the
  // same confident-wrong-status this file's poll loop exists to avoid.
  writeStatus(jobDir, { stage: "cancelling", message: "stopping...", progress: null, error: null });

  try {
    const result = await consoleFetch(`/api/agents/jobs/${rec.jobId}`, {
      method: "PATCH",
      body: { action: "cancel" },
    });
    // Cancelled outright. Write the terminal state here rather than wait
    // for a poll loop, because in two of the three cases there isn't one:
    // during an upload it hasn't started, and after a restart it never
    // will. Harmlessly idempotent where there is one.
    if (result?.status === "cancelled") {
      writeStatus(jobDir, { stage: "cancelled", message: "cancelled", progress: null, error: null, done: false });
      return { cancelled: true, stopped: true };
    }
    // Still running on a pod: the runner sees cancel_requested on its next
    // status report and terminates it, which is what actually stops the
    // GPU billing. pollUntilDone writes the terminal state when it lands.
    //
    // Unless nothing is following this job -- the restarted-app case,
    // where `active` is empty and no poll loop exists. Start one, or
    // "Stopping..." is where this row stays forever.
    if (!active.has(recordingDir)) {
      active.set(recordingDir, rec);
      pollUntilDone(recordingDir, jobDir, rec.jobId, rec.label).catch((err) => {
        active.delete(recordingDir);
        console.error(`[pipeline] polling stopped: ${err.message}`);
      });
    }
    return { cancelled: true, stopped: false };
  } catch (err) {
    // The local upload really has stopped, so saying nothing happened
    // would be wrong -- but so would claiming a clean cancel the console
    // never confirmed. Terminal either way, so Retry becomes available.
    console.error(`[pipeline] cancel failed: ${err.message}`);
    writeStatus(jobDir, {
      stage: "error",
      message: "stopped here, but the cloud console didn't confirm",
      error: err.message,
      progress: null,
      done: false,
    });
    return { cancelled: true, stopped: false, consoleError: err.message };
  }
}
