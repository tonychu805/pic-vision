"""Operator-side job runner (ADR-084, thin agent).

Polls the cloud console for queued jobs and runs them on this machine with
the unchanged pipeline: a venue's desktop app uploads its recording
segments to R2 and enqueues a job; this runner downloads them, joins them,
and calls webapp.pipeline.run_cloud_job(job_dir) exactly the way
run_desktop_job.py did when the desktop still ran Python itself. The
console learns progress through PATCH /api/runner/jobs/<id> (a mirror of
status.json) and creates the `reels` rows itself when a job finishes --
this process never holds a venue agent's token.

Calibration fits arrive the same way (kind = "calibration"): the operator
clicked 14 points on a snapshot in the console; the fit is
save_calibration.build_calibration(), unchanged, and the result goes back
onto the camera row for every later reel job to use.

Needs, from .env: RUNNER_TOKEN (same value set on the console), the
CLOUDFLARE_R2_* keys and RUNPOD_API_KEY the pipeline already needs.
Optional: CONSOLE_URL, RUNNER_WORK_DIR, RUNNER_ID.

    make runner            # or: .venv/bin/python -m cloud_pipeline.job_runner
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

import requests
from dotenv import load_dotenv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
load_dotenv(os.path.join(REPO_ROOT, ".env"))

from cloud_pipeline import r2_storage  # noqa: E402
from cloud_pipeline.save_calibration import build_calibration  # noqa: E402

CONSOLE_URL = os.environ.get("CONSOLE_URL", "https://console.picvisionai.com").rstrip("/")
RUNNER_TOKEN = os.environ.get("RUNNER_TOKEN")
WORK_DIR = os.environ.get("RUNNER_WORK_DIR", os.path.join(REPO_ROOT, "cloud_pipeline", "jobs", "runner"))
RUNNER_ID = os.environ.get("RUNNER_ID", socket.gethostname())

POLL_SEC = 5
MIRROR_SEC = 3
HEARTBEAT_SEC = 60
TERMINAL_STAGES = ("done", "error", "cancelled")


def _log(msg):
    print(f"[runner {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _headers():
    return {"Authorization": f"Bearer {RUNNER_TOKEN}"}


def claim_job():
    r = requests.post(f"{CONSOLE_URL}/api/runner/jobs/claim",
                      json={"runnerId": RUNNER_ID}, headers=_headers(), timeout=30)
    if r.status_code == 204:
        return None
    r.raise_for_status()
    return r.json()["job"]


def patch_job(job_id, **fields):
    """Mirror fields onto the console's job row. Returns True when the
    console wants this job cancelled -- either because the operator asked,
    or because the row is no longer `running` (409: reclaimed by another
    runner after we went quiet, or cancelled outright) and anything we do
    from here on is wasted."""
    r = requests.patch(f"{CONSOLE_URL}/api/runner/jobs/{job_id}",
                       json=fields, headers=_headers(), timeout=30)
    if r.status_code == 409:
        return True
    r.raise_for_status()
    return bool(r.json().get("cancelRequested"))


def _read_status(job_dir):
    path = os.path.join(job_dir, "status.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _download_segments(job, job_dir):
    keys = job.get("segment_keys") or []
    if not keys:
        raise RuntimeError("job has no recording segments")
    seg_dir = os.path.join(job_dir, "segments")
    os.makedirs(seg_dir, exist_ok=True)
    patch_job(job["id"], stage="download", message=f"downloading {len(keys)} segment(s)...",
              progress={"current": 0, "total": len(keys), "eta_sec": None})
    local_paths = []
    for i, key in enumerate(keys):
        local = os.path.join(seg_dir, os.path.basename(key))
        r2_storage.download_file(job["bucket"], key, local)
        local_paths.append(local)
        if patch_job(job["id"], progress={"current": i + 1, "total": len(keys), "eta_sec": None}):
            raise _Cancelled()
    return local_paths


def _concat(job_dir, segments):
    """Same stream-copy join desktop/electron/pipeline.js used to do locally
    (ADR-030/032 segments, one continuous file for the pipeline)."""
    if len(segments) == 1:
        return segments[0]
    list_path = os.path.join(job_dir, "concat_list.txt")
    out = os.path.join(job_dir, "session_full.mkv")
    with open(list_path, "w") as f:
        for p in sorted(segments):
            f.write(f"file '{p}'\n")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", list_path, "-c", "copy", out], check=True)
    return out


class _Cancelled(Exception):
    pass


def run_reel_job(job):
    from webapp.pipeline import cancel_job, run_cloud_job

    job_id = job["id"]
    job_dir = os.path.join(WORK_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    segments = _download_segments(job, job_dir)
    video_path = _concat(job_dir, segments)

    calib_path = os.path.join(job_dir, "calib.json")
    with open(calib_path, "w") as f:
        json.dump(job["calib"], f, indent=2)
    with open(os.path.join(job_dir, "job.json"), "w") as f:
        json.dump({
            "video_file": os.path.abspath(video_path),
            "calib_path": os.path.abspath(calib_path),
            "target_sec": float(job.get("target_sec") or 300),
            "session_id": job.get("session_id") or job_id,
        }, f)

    worker = threading.Thread(target=run_cloud_job, args=(job_dir,), daemon=True)
    worker.start()

    last_sent = None
    last_patch_at = time.monotonic()
    cancel_sent = False
    while worker.is_alive():
        time.sleep(MIRROR_SEC)
        status = _read_status(job_dir)
        snapshot = json.dumps({k: status.get(k) for k in ("stage", "message", "progress")}, sort_keys=True)
        due = time.monotonic() - last_patch_at >= HEARTBEAT_SEC
        if snapshot == last_sent and not due:
            continue
        # progress is sent even when it's None: webapp/pipeline.py clears it
        # on every stage change, and dropping the null would leave the
        # console showing the previous stage's frame count against the new
        # stage's name. stage/message are only sent when actually set, so a
        # partially-written status.json can't blank them.
        fields = {k: v for k, v in (("stage", status.get("stage")), ("message", status.get("message")))
                  if v is not None}
        fields["progress"] = status.get("progress")
        cancel = patch_job(job_id, **fields)
        last_sent, last_patch_at = snapshot, time.monotonic()
        if cancel and not cancel_sent:
            _log(f"job {job_id}: cancel requested, stopping (pod terminated if any)")
            cancel_job(job_dir)
            cancel_sent = True

    status = _read_status(job_dir)
    stage = status.get("stage")
    if stage == "done":
        patch_job(job_id, done=True, stage="done", message="done", progress=None, result={
            "share_id": status.get("share_id"),
            "reel_bucket": status.get("reel_bucket"),
            "reels": status.get("reels") or [],
            "stats": status.get("stats"),
        })
    elif stage == "cancelled" or cancel_sent:
        patch_job(job_id, cancelled=True, message="cancelled")
    else:
        patch_job(job_id, error=str(status.get("error") or status.get("message") or "job failed"))
    return job_dir


def run_calibration_job(job):
    job_id = job["id"]
    params = job.get("params") or {}
    job_dir = os.path.join(WORK_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    snapshot_key = params.get("snapshotKey")
    points = params.get("points") or []
    if not snapshot_key or not points:
        raise ValueError("calibration job is missing its snapshot or points")

    patch_job(job_id, stage="calibrate", message="fitting the court homography...")
    snapshot_path = os.path.join(job_dir, "snapshot.png")
    r2_storage.download_file(job["bucket"], snapshot_key, snapshot_path)
    calib, rmse_ft, worst = build_calibration(points, snapshot_path)
    patch_job(job_id, done=True, stage="done",
              message=f"calibrated, reprojection error {rmse_ft:.3f} ft",
              result={"calib": calib, "rmse_ft": rmse_ft, "worst": worst})
    return job_dir


def _cleanup(job, job_dir):
    logs = os.path.join(WORK_DIR, "logs")
    os.makedirs(logs, exist_ok=True)
    log_src = os.path.join(job_dir, "log.txt")
    if os.path.exists(log_src):
        shutil.copyfile(log_src, os.path.join(logs, f"{job['id']}.log"))
    shutil.rmtree(job_dir, ignore_errors=True)
    for key in job.get("segment_keys") or []:
        try:
            r2_storage.delete_object(job["bucket"], key)
        except Exception as e:  # noqa: BLE001 - cleanup is best-effort
            _log(f"job {job['id']}: couldn't delete {key}: {e}")


def run_one(job):
    kind = job.get("kind", "reel")
    _log(f"claimed {kind} job {job['id']} ({job.get('camera_label') or job.get('camera_id')})")
    job_dir = os.path.join(WORK_DIR, job["id"])
    try:
        if kind == "calibration":
            run_calibration_job(job)
        else:
            run_reel_job(job)
        _log(f"job {job['id']} finished")
    except _Cancelled:
        _log(f"job {job['id']} cancelled during download")
        patch_job(job["id"], cancelled=True, message="cancelled")
    except Exception as e:  # noqa: BLE001 - report every failure back, then keep serving
        _log(f"job {job['id']} FAILED: {e}")
        try:
            patch_job(job["id"], error=str(e)[:2000])
        except Exception as report_err:  # noqa: BLE001
            _log(f"job {job['id']}: couldn't report failure: {report_err}")
    finally:
        _cleanup(job, job_dir)


def main():
    if not RUNNER_TOKEN:
        sys.exit("RUNNER_TOKEN is not set (add it to .env; same value as the console's)")
    os.makedirs(WORK_DIR, exist_ok=True)
    _log(f"polling {CONSOLE_URL} as {RUNNER_ID}, work dir {WORK_DIR}")
    while True:
        try:
            job = claim_job()
        except Exception as e:  # noqa: BLE001 - console unreachable: wait, don't die
            _log(f"claim failed: {e}")
            time.sleep(POLL_SEC * 4)
            continue
        if job is None:
            time.sleep(POLL_SEC)
            continue
        run_one(job)


if __name__ == "__main__":
    main()
