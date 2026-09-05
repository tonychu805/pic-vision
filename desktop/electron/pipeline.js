// Hands a finished recording to the cloud pipeline -- PIC-68, ADR-071's
// "local agent invokes the existing Python as a subprocess, don't
// reimplement transcode/upload/orchestration in JS" directive. Spawns
// cloud_pipeline/run_desktop_job.py, which itself just calls
// webapp/pipeline.py's run_cloud_job(job_dir) -- the same R2 upload +
// RunPod inference + reel-cut logic the Flask dashboard already runs,
// reused here rather than ported.
//
// Mirrors capture.js's own spawn/track/status shape: module-level Map,
// not per-window state, since a cloud job must survive the renderer
// navigating away from this camera's detail page, same reasoning as a
// recording in progress.
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { PYTHON_BIN } from "./pythonBin.js";
import { getCloudConnection } from "./cloud.js";
import { logEvent } from "./activityLog.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.join(__dirname, "..", "..");
const RUN_DESKTOP_JOB = path.join(REPO_ROOT, "cloud_pipeline", "run_desktop_job.py");

const SEGMENT_RE = /^session-\d+\.mkv$/;

// recordingDir -> { proc, jobDir }. Keyed by the recording's own
// directory (== capture.js's per-session outDir) rather than sessionId
// alone, since that's also where status.json/log.txt end up (in a
// cloud_job/ subdirectory) and where a second "send to cloud" click for
// the same recording needs to be refused.
const active = new Map();

export function isPipelineRunning(recordingDir) {
  return active.has(recordingDir);
}

export function pipelineStatus(jobDir) {
  const statusPath = path.join(jobDir, "status.json");
  if (!existsSync(statusPath)) return { stage: null };
  return JSON.parse(readFileSync(statusPath, "utf8"));
}

// jobDir is deterministic from recordingDir (== `${recordingDir}/cloud_job`,
// same join runCloudJob does), so a renderer that only knows the recording
// can recover an already-running job's status without ever having seen
// runCloudJob's return value -- e.g. after navigating away from the camera
// detail page and back, which otherwise looks exactly like the job
// vanished even though it's still running server-side (real report,
// 2026-09-03: CloudJobRow's `job` state, holding jobDir, was purely
// in-memory and reset to null on remount).
export function pipelineStatusForRecording(recordingDir) {
  return pipelineStatus(path.join(recordingDir, "cloud_job"));
}

// capture.js saves 10-minute segments (ADR-030/032: a crash or Wi-Fi drop
// costs one segment, not the whole session), but the cloud pipeline needs
// one continuous file. Stream-copy concat -- same -c copy capture.js
// already uses, no re-encode -- rather than only supporting a
// single-segment recording.
function concatSegments(recordingDir) {
  const segments = readdirSync(recordingDir).filter((f) => SEGMENT_RE.test(f)).sort();
  if (segments.length === 0) throw new Error(`No recording segments found in ${recordingDir}`);
  if (segments.length === 1) return path.join(recordingDir, segments[0]);

  const listPath = path.join(recordingDir, "concat_list.txt");
  const concatOut = path.join(recordingDir, "session_full.mkv");
  writeFileSync(listPath, segments.map((f) => `file '${f}'`).join("\n") + "\n");
  const result = spawnSync("ffmpeg", [
    "-y", "-f", "concat", "-safe", "0", "-i", listPath, "-c", "copy", concatOut,
  ], { cwd: recordingDir });
  if (result.status !== 0) {
    throw new Error(`ffmpeg concat failed: ${(result.stderr || "").toString().trim().slice(-2000)}`);
  }
  return concatOut;
}

// `videoPath`, when given, skips concatSegments entirely -- a sample-clip
// camera (2026-09-03) already has a single, real video file (no segments
// to join), so main.js passes its path straight through rather than
// looking for session-*.mkv files that were never written.
//
// cameraId/cameraLabel (ADR-074) let run_desktop_job.py report the
// finished reel to the cloud console once the job succeeds -- only
// possible when this agent is actually paired (getCloudConnection()
// returns something); an unpaired desktop still runs the job fine, it
// just has nowhere to report to, same as heartbeat already no-ops
// unpaired (cloud.js's own sendHeartbeat).
export function runCloudJob({ recordingDir, calibPath, targetSec, sessionId, videoPath: explicitVideoPath, cameraId, cameraLabel }) {
  if (active.has(recordingDir)) throw new Error("A cloud job is already running for this recording");
  if (!calibPath || !existsSync(calibPath)) throw new Error(`No calibration file at ${calibPath}`);
  if (explicitVideoPath && !existsSync(explicitVideoPath)) throw new Error(`No video file at ${explicitVideoPath}`);

  const videoPath = explicitVideoPath || concatSegments(recordingDir);
  const jobDir = path.join(recordingDir, "cloud_job");
  mkdirSync(jobDir, { recursive: true });

  const args = [
    RUN_DESKTOP_JOB,
    "--video", videoPath,
    "--calib", calibPath,
    "--target-sec", String(targetSec || 300),
    "--session-id", sessionId,
    "--out-dir", jobDir,
  ];
  if (cameraId) args.push("--camera-id", cameraId);
  if (cameraLabel) args.push("--camera-label", cameraLabel);
  const connection = getCloudConnection();
  if (connection) {
    args.push("--console-url", connection.consoleUrl, "--api-token", connection.apiToken);
  }
  const proc = spawn(PYTHON_BIN, args, { cwd: REPO_ROOT, stdio: "ignore" });
  active.set(recordingDir, { proc, jobDir });
  const label = cameraLabel || "camera";
  logEvent("pipeline_started", `Sent ${label} to the cloud`);
  proc.on("exit", () => {
    active.delete(recordingDir);
    // The process only ever exits after webapp/pipeline.py's run_cloud_job
    // has written a terminal stage to status.json (done/error/cancelled)
    // -- reading it right here, on the job's own exit, is simpler and more
    // immediate than polling it from elsewhere (e.g. the next heartbeat
    // tick), since this event fires the instant the job actually finishes.
    const status = pipelineStatus(jobDir);
    if (status.stage === "done") {
      const full = (status.reels || []).find((r) => r.kind === "full") || (status.reels || [])[0];
      const stats = full?.stats;
      const detail = stats ? `${stats.n_chosen} rallies, ${Math.round(stats.total_duration_sec)}s` : null;
      logEvent("pipeline_done", `${label} reel ready`, detail);
    } else if (status.stage === "cancelled") {
      logEvent("pipeline_failed", `${label} cloud job cancelled`);
    } else {
      // Covers "error" and the unexpected case of exiting with no
      // status.json at all (e.g. a crash before webapp/pipeline.py ever
      // wrote one) -- either way, the job didn't finish, worth a log
      // entry either way rather than silently dropping it.
      logEvent("pipeline_failed", `${label} cloud job failed`, status.message || status.error || null);
    }
  });

  return { jobDir };
}

// SIGINT, matching capture.js's own "never a hard kill" convention --
// run_desktop_job.py's signal handler calls webapp.pipeline.cancel_job(),
// which terminates any RunPod pod already created (stops billing) before
// this process exits, rather than a bare kill that would orphan a pod
// nobody's tracking anymore.
export function cancelCloudJob(recordingDir) {
  const rec = active.get(recordingDir);
  if (!rec) return { cancelled: false };
  rec.proc.kill("SIGINT");
  return { cancelled: true };
}
