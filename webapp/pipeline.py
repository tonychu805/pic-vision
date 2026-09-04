"""Background pipeline orchestration for the web UI (webapp/app.py).

Runs each job through the same manual sequence this project has used all
along: drift check (informational, ADR-049) -> CFR conversion (the exact
recipe scripts/pod_infer.py's own error message gives) -> TrackNet inference
in the separate TF2.15 GPU env (subprocess) -> detect + rank + cut a reel
(scripts/rank_and_reel.py's build_reel). Progress is written to
<job_dir>/status.json and appended to <job_dir>/log.txt so webapp/app.py's
status endpoint has something to poll and tail.
"""
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src import job_log
from src.drift import find_bumps, drift_span
from scripts.check_drift import measure as drift_measure
from scripts.rank_and_reel import build_reel

TF215_PY = "/mnt/fast_scratch/tf215_env/venv/bin/python"
TF215_NVIDIA_LIB_GLOB = ("/mnt/fast_scratch/tf215_env/venv/lib/"
                          "python3.11/site-packages/nvidia/*/lib")
TRACKNET_MODEL = "/mnt/fast_scratch/tracknet_weights/weights_k14_epoch19"

LOCAL_STAGES = [
    ("drift_check", "Checking camera drift"),
    ("convert", "Converting to 30fps CFR"),
    ("inference", "Running TrackNet inference (local GPU)"),
    ("reel", "Detecting rallies, ranking, cutting reel"),
]

# Mirrors cloud_pipeline.run_cloud_job.STAGES -- imported when available (the
# common case) so there's one source of truth; falls back to a literal copy
# so a missing boto3/paramiko install (cloud_pipeline's own dependencies)
# can't break the local route or the webapp's own startup. Keep in sync by
# hand if cloud_pipeline.run_cloud_job.STAGES changes (same convention this
# project already uses for cloud_pipeline/Dockerfile vs. POD_SETUP_CMD).
try:
    from cloud_pipeline.run_cloud_job import STAGES as CLOUD_STAGES
except ImportError:
    CLOUD_STAGES = [
        ("drift_check", "Checking camera drift"),
        ("convert", "Converting to 30fps CFR"),
        ("proxy", "Creating 1080p upload proxy"),
        ("r2_upload", "Uploading video to cloud storage"),
        ("pod_create", "Creating RunPod GPU pod"),
        ("pod_install", "Installing dependencies on pod"),
        ("pod_download", "Downloading video onto pod"),
        ("inference", "Running TrackNet inference (RunPod GPU)"),
        ("cut", "Detecting rallies, ranking, cutting reel (on pod)"),
        ("r2_download", "Uploading finished reel to cloud storage"),
    ]

# pod_infer.py's own periodic progress line, e.g. "  300/29400  75 fps  ETA 6.5 min".
_PROGRESS_RE = re.compile(r"^\s*(\d+)/(\d+)\s+(\d+)\s*fps\s+ETA\s+([\d.]+)\s*min")

# job_id -> {"proc": Popen|None, "pod_id": str|None} for whatever real
# resource (local subprocess or RunPod pod) a running job currently holds --
# lets cancel_job() actually stop billing/GPU usage from a separate request,
# not just mark the job done and leave the resource running unattended.
_handles_lock = threading.Lock()
_job_handles = {}

# job_ids the operator has asked to cancel. Killing a registered proc/pod is
# not enough on its own -- drift-check, CFR-conversion, R2 upload, and the
# window before create_pod() succeeds all run with no handle registered yet,
# so a cancel during any of those previously did nothing but flip the UI's
# busy flag: the background thread kept going, unaware, and would still
# reach create_pod() moments later and spin up a real, billed pod nobody was
# tracking anymore. Checked cooperatively at each stage boundary instead of
# relied on being able to kill something after the fact.
_cancel_requested = set()


class _Cancelled(Exception):
    """Raised internally when a stage boundary notices cancel_job() was
    called. Caught by run_job()/run_cloud_job()'s existing except handler,
    which already knows not to stomp the "cancelled" status cancel_job()
    wrote."""


def _register_proc(job_id, proc):
    with _handles_lock:
        _job_handles.setdefault(job_id, {})["proc"] = proc


def _register_pod(job_id, pod_id):
    with _handles_lock:
        _job_handles.setdefault(job_id, {})["pod_id"] = pod_id


def _clear_handle(job_id):
    with _handles_lock:
        _job_handles.pop(job_id, None)
        _cancel_requested.discard(job_id)


def _is_cancelled(job_id):
    with _handles_lock:
        return job_id in _cancel_requested


def _check_cancel(job_id):
    if _is_cancelled(job_id):
        raise _Cancelled()


def _log(job_dir, msg):
    job_log.append(job_dir, msg)


def _set_status(job_dir, **fields):
    """Merge fields into status.json (atomic write via rename, so the status
    endpoint never reads a half-written file mid-poll)."""
    path = os.path.join(job_dir, "status.json")
    current = {}
    if os.path.exists(path):
        with open(path) as f:
            current = json.load(f)
    current.update(fields)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(current, f, indent=2)
    os.replace(tmp, path)


def _current_stage(job_dir):
    path = os.path.join(job_dir, "status.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f).get("stage")


def cancel_job(job_dir):
    """Best-effort cancellation: stops whatever real resource (local
    subprocess or RunPod pod) this job currently holds, then marks it done
    so a new job can start immediately. For the cloud route the pod
    termination is the part that actually matters (stops billing) -- the
    background thread itself may take a while longer to unwind if it's
    stuck inside a blocking ssh call whose connection hasn't yet noticed the
    remote pod is gone, but that's harmless once the pod is dead and the job
    is marked done: run_job()/run_cloud_job()'s except handlers check for
    stage=="cancelled" before overwriting this status, so the eventual
    exception from the killed process/dropped connection won't stomp it.

    Also flags the job as cancelled *before* touching any handle -- if
    nothing is registered yet (still in drift-check/convert/upload, or
    mid-create_pod()), there's nothing to kill here, but the running thread
    will hit its own _check_cancel() at the next stage boundary and stop
    itself before reaching create_pod() or local inference, rather than
    continuing unattended in the background."""
    job_id = os.path.basename(job_dir.rstrip("/"))
    with _handles_lock:
        _cancel_requested.add(job_id)
        handle = _job_handles.pop(job_id, {})
    proc = handle.get("proc")
    pod_id = handle.get("pod_id")

    # Write the terminal status BEFORE doing any potentially slow work below
    # (terminate_pod() is a real network call) -- otherwise a background
    # thread that hits _check_cancel() in that window would raise, see
    # stage != "cancelled" yet, and get misreported as a genuine error
    # instead of a clean cancellation.
    _set_status(job_dir, stage="cancelled", message="cancelled by operator",
                done=True, error="cancelled by operator")

    stopped = []
    if proc is not None and proc.poll() is None:
        proc.terminate()
        stopped.append("local inference process")
    if pod_id:
        from cloud_pipeline import runpod_pod
        runpod_pod.terminate_pod(pod_id)
        stopped.append(f"RunPod pod {pod_id}")

    if stopped:
        msg = f"cancelled by operator ({', '.join(stopped)} stopped)"
    else:
        msg = "cancelled by operator (no running process/pod recorded yet)"
    _log(job_dir, f"[cancel] {msg}")
    _set_status(job_dir, message=msg, error=msg)


def _run_drift_check(job_dir, video_path):
    _set_status(job_dir, stage="drift_check", stage_started_at=time.time(),
                message="checking for camera movement...", progress=None)
    samples, _duration = drift_measure(video_path, step_sec=60.0, width=960)
    span_x, span_y = drift_span(samples)
    bumps = find_bumps(samples, min_step_px=5.0)
    if bumps:
        msg = (f"camera drift detected ({len(bumps)} bump(s), max span "
               f"{max(span_x, span_y):.0f}px) -- calibration may only be valid in "
               f"part of this video (ADR-049). Continuing anyway (warn-only).")
    elif max(span_x, span_y) > 5.0:
        msg = f"camera crept {max(span_x, span_y):.0f}px over the recording, no clean bump"
    else:
        msg = "camera held still -- one calibration covers the whole recording"
    _log(job_dir, f"[drift] {msg}")


def _convert_cfr(job_dir, src_video, out_video):
    _set_status(job_dir, stage="convert", stage_started_at=time.time(),
                message="converting to 30fps CFR...", progress=None)
    cmd = ["ffmpeg", "-y", "-v", "error", "-err_detect", "ignore_err",
           "-i", src_video, "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20",
           "-an", "-fps_mode", "cfr", "-r", "30", out_video]
    _log(job_dir, f"[convert] {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def _run_inference(job_dir, cfr_video, calib_path, csv_path, job_id):
    _set_status(job_dir, stage="inference", stage_started_at=time.time(),
                message="running TrackNet inference...", progress=None)
    nvidia_libs = glob.glob(TF215_NVIDIA_LIB_GLOB)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = ":".join(nvidia_libs)
    cmd = [TF215_PY, os.path.join(REPO_ROOT, "scripts", "pod_infer.py"),
           "--video", cfr_video, "--model", TRACKNET_MODEL,
           "--output", csv_path, "--calib", calib_path]
    _log(job_dir, f"[inference] {' '.join(cmd)}")

    # Streamed (not subprocess.run) so pod_infer.py's own periodic progress
    # lines ("300/29400 75 fps ETA 6.5 min") can feed a live progress bar,
    # and so the Popen handle can be registered for cancel_job() to
    # terminate on request.
    proc = subprocess.Popen(cmd, env=env, cwd=REPO_ROOT, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, bufsize=1)
    _register_proc(job_id, proc)
    try:
        with open(os.path.join(job_dir, "log.txt"), "a") as logf:
            for line in proc.stdout:
                logf.write(line)
                m = _PROGRESS_RE.match(line)
                if m:
                    current, total, _fps, eta_min = m.groups()
                    _set_status(job_dir, progress={"current": int(current),
                                                    "total": int(total),
                                                    "eta_sec": float(eta_min) * 60.0})
        returncode = proc.wait()
    finally:
        if proc.stdout:
            proc.stdout.close()
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, cmd)


def run_job(job_dir):
    """Entry point for the background thread webapp/app.py starts once
    calibration is saved. Runs to completion or writes stage="error"."""
    job_id = os.path.basename(job_dir.rstrip("/"))
    try:
        with open(os.path.join(job_dir, "job.json")) as f:
            job = json.load(f)
        video_path = os.path.join(job_dir, job["video_file"])
        calib_path = os.path.join(job_dir, "calib.json")
        cfr_video = os.path.join(job_dir, "video_cfr.mp4")
        csv_path = os.path.join(job_dir, "predictions.csv")
        reel_dir = os.path.join(job_dir, "reel")

        _set_status(job_dir, stages=LOCAL_STAGES)
        _check_cancel(job_id)
        _run_drift_check(job_dir, video_path)
        _check_cancel(job_id)
        _convert_cfr(job_dir, video_path, cfr_video)
        _check_cancel(job_id)
        _run_inference(job_dir, cfr_video, calib_path, csv_path, job_id)

        _set_status(job_dir, stage="reel", stage_started_at=time.time(), progress=None,
                    message="detecting rallies, ranking, cutting reel...")
        result = build_reel(cfr_video, csv_path, calib_path, reel_dir,
                             job["target_sec"], job["session_id"],
                             log_path=os.path.join(job_dir, "log.txt"))

        _set_status(job_dir, stage="done", message="done", done=True, progress=None,
                    reel_chronological=result["chronological"],
                    reel_ranked=result["ranked"], stats=result["stats"])
    except Exception as e:
        if _current_stage(job_dir) == "cancelled":
            return  # cancel_job() already wrote the terminal status -- don't stomp it
        _log(job_dir, "[error] " + "".join(
            traceback.format_exception(type(e), e, e.__traceback__)))
        _set_status(job_dir, stage="error", message=str(e), done=True, error=str(e))
    finally:
        _clear_handle(job_id)


def run_cloud_job(job_dir):
    """Cloud-path counterpart to run_job(): same job_dir/status.json/log.txt
    contract webapp/app.py's status page already polls, but dispatches
    inference to RunPod+R2 (cloud_pipeline.run_cloud_job) instead of the
    local TF2.15 subprocess. job.json must carry "calib_path" pointing at an
    existing per-venue calib.json (cloud_pipeline/venues/<name>/calib.json)
    -- unlike the local route, this never calibrates per job (see
    cloud_pipeline/run_cloud_job.py's own guard against that mistake).
    Imports cloud_pipeline lazily so a missing boto3/paramiko install only
    breaks the cloud route, not the whole webapp at startup."""
    from cloud_pipeline.run_cloud_job import run_cloud_job as _cloud_run
    job_id = os.path.basename(job_dir.rstrip("/"))
    stage_tracker = {"current": None}
    try:
        with open(os.path.join(job_dir, "job.json")) as f:
            job = json.load(f)
        video_path = os.path.join(job_dir, job["video_file"])
        calib_path = job["calib_path"]

        def log(msg, stage=None):
            fields = {"message": msg}
            if stage and stage != stage_tracker["current"]:
                fields["stage"] = stage
                fields["stage_started_at"] = time.time()
                fields["progress"] = None  # stale progress from the previous stage
                stage_tracker["current"] = stage
            _set_status(job_dir, **fields)
            _log(job_dir, msg)

        def progress(current, total, eta_sec):
            _set_status(job_dir, progress={"current": current, "total": total,
                                            "eta_sec": eta_sec})

        def on_pod_id(pod_id):
            _register_pod(job_id, pod_id)
            _log(job_dir, f"[pod] tracking pod {pod_id} (cancellable)")

        _set_status(job_dir, stages=CLOUD_STAGES)
        log("starting cloud pipeline run...", stage="drift_check")
        result = _cloud_run(video_path, calib_path, job["target_sec"],
                             job["session_id"], job_dir, log_fn=log,
                             progress_fn=progress, pod_id_fn=on_pod_id,
                             should_cancel_fn=lambda: _is_cancelled(job_id))

        # Cloud path returns R2 keys, not local file paths (ADR-074 -- the
        # reel is cut on the pod, never downloaded here) -- a different
        # result shape from run_job()'s local reel_chronological/reel_ranked
        # file paths above, so this reports bucket/key fields instead.
        _set_status(job_dir, stage="done", message="done", done=True, progress=None,
                    reel_bucket=result["bucket"],
                    reel_ranked_key=result["ranked_key"], reel_id=result["reel_id"],
                    stats=result["stats"])
    # (Exception, SystemExit), not just Exception -- cloud_pipeline.run_cloud_job's
    # own missing-calibration guard raises SystemExit (fine for its bare-CLI
    # use, where an uncaught SystemExit just prints one clean line and exits),
    # but that isn't an Exception subclass, so a plain `except Exception` here
    # let it escape uncaught: this function's own thread died silently and
    # status.json was left stuck at whatever stage was last set (drift_check)
    # forever instead of ever reaching stage="error" -- found 2026-09-02 while
    # adding PIC-68's desktop-agent caller, but this path is shared with the
    # Flask dashboard's cloud-job route too, so it was a live bug there
    # already, not something new to this caller.
    except (Exception, SystemExit) as e:
        if _current_stage(job_dir) == "cancelled":
            return  # cancel_job() already wrote the terminal status -- don't stomp it
        _log(job_dir, "[error] " + "".join(
            traceback.format_exception(type(e), e, e.__traceback__)))
        _set_status(job_dir, stage="error", message=str(e), done=True, error=str(e))
    finally:
        _clear_handle(job_id)
