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
import subprocess
import sys
import traceback

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.drift import find_bumps, drift_span
from scripts.check_drift import measure as drift_measure
from scripts.rank_and_reel import build_reel

TF215_PY = "/mnt/fast_scratch/tf215_env/venv/bin/python"
TF215_NVIDIA_LIB_GLOB = ("/mnt/fast_scratch/tf215_env/venv/lib/"
                          "python3.11/site-packages/nvidia/*/lib")
TRACKNET_MODEL = "/mnt/fast_scratch/tracknet_weights/weights_k14_epoch19"


def _log(job_dir, msg):
    with open(os.path.join(job_dir, "log.txt"), "a") as f:
        f.write(msg.rstrip("\n") + "\n")


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


def _run_drift_check(job_dir, video_path):
    _set_status(job_dir, stage="drift_check", message="checking for camera movement...")
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
    _set_status(job_dir, stage="convert", message="converting to 30fps CFR...")
    cmd = ["ffmpeg", "-y", "-v", "error", "-err_detect", "ignore_err",
           "-i", src_video, "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20",
           "-an", "-fps_mode", "cfr", "-r", "30", out_video]
    _log(job_dir, f"[convert] {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def _run_inference(job_dir, cfr_video, calib_path, csv_path):
    _set_status(job_dir, stage="inference",
                message="running TrackNet inference (~20-30 min for a full session)...")
    nvidia_libs = glob.glob(TF215_NVIDIA_LIB_GLOB)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = ":".join(nvidia_libs)
    cmd = [TF215_PY, os.path.join(REPO_ROOT, "scripts", "pod_infer.py"),
           "--video", cfr_video, "--model", TRACKNET_MODEL,
           "--output", csv_path, "--calib", calib_path]
    _log(job_dir, f"[inference] {' '.join(cmd)}")
    with open(os.path.join(job_dir, "log.txt"), "a") as logf:
        subprocess.run(cmd, env=env, cwd=REPO_ROOT, stdout=logf,
                        stderr=subprocess.STDOUT, check=True)


def run_job(job_dir):
    """Entry point for the background thread webapp/app.py starts once
    calibration is saved. Runs to completion or writes stage="error"."""
    try:
        with open(os.path.join(job_dir, "job.json")) as f:
            job = json.load(f)
        video_path = os.path.join(job_dir, job["video_file"])
        calib_path = os.path.join(job_dir, "calib.json")
        cfr_video = os.path.join(job_dir, "video_cfr.mp4")
        csv_path = os.path.join(job_dir, "predictions.csv")
        reel_dir = os.path.join(job_dir, "reel")

        _run_drift_check(job_dir, video_path)
        _convert_cfr(job_dir, video_path, cfr_video)
        _run_inference(job_dir, cfr_video, calib_path, csv_path)

        _set_status(job_dir, stage="reel", message="detecting rallies, ranking, cutting reel...")
        result = build_reel(cfr_video, csv_path, calib_path, reel_dir,
                             job["target_sec"], job["session_id"],
                             log_path=os.path.join(job_dir, "log.txt"))

        _set_status(job_dir, stage="done", message="done", done=True,
                    reel_chronological=result["chronological"],
                    reel_ranked=result["ranked"], stats=result["stats"])
    except Exception as e:
        _log(job_dir, "[error] " + "".join(
            traceback.format_exception(type(e), e, e.__traceback__)))
        _set_status(job_dir, stage="error", message=str(e), done=True, error=str(e))
