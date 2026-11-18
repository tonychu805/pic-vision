"""Operator-side calibration runner (ADR-084, ADR-125).

Polls the cloud console for queued calibration jobs and fits each one
here: the operator clicked 14 points on a snapshot in the console; the
fit is save_calibration.build_calibration(), unchanged, and the result
goes back onto the camera row for every later reel job to use. That's
CPU-only, seconds long, and never needed a pod.

Reel jobs are not this runner's: the Cloudflare orchestrator
(pic-vision-cloud-console/orchestrator-worker, ADR-125) rents the GPU and
watches the pod. This runner's own RunPod path called RunPod's REST v1,
retired 2026-11-15, and was removed with runpod_pod.py (now in archive/).
A reel job claimed here by mistake is refused with that reason.

Needs, from .env: RUNNER_TOKEN (same value set on the console) and the
CLOUDFLARE_R2_* keys. Optional: CONSOLE_URL, RUNNER_WORK_DIR, RUNNER_ID.

    make runner            # or: .venv/bin/python -m cloud_pipeline.job_runner
"""
import concurrent.futures
import os
import shutil
import socket
import sys
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

# Calibrations only: reel jobs run on the Cloudflare orchestrator (ADR-125),
# and calibrations need OpenCV here until the fit is ported into the console.
RUNNER_KINDS = ["calibration"]

POLL_SEC = 5

# Backoff while there is nothing to do (2026-09-20). This loop used to
# poll every POLL_SEC forever: 17,280 calls a day, ~518k a month, against
# a Netlify function, doing nothing. That alone exceeded the account's
# quota and took console/share/marketing down for five days before anyone
# noticed -- the runner's own "claim failed" lines went to journald, which
# is not a place anybody watches.
#
# Backs off to IDLE_MAX_SEC after IDLE_RAMP_AFTER consecutive empty
# claims, and snaps straight back to POLL_SEC the moment a job appears, so
# a busy period still polls tightly. Worst case a job waits IDLE_MAX_SEC
# before being picked up, which is nothing against a ~10 minute reel job --
# but it IS something against a calibration, which a person is watching a
# spinner for (58s observed, 2026-09-20). The console's "may not be running"
# threshold is coupled to this: RUNNER_IDLE_POLL_MS in
# pic-vision-cloud-console/lib/calibrationTiming.ts. Change one, change both.
IDLE_RAMP_AFTER = 3
IDLE_MAX_SEC = 60


def idle_sleep_sec(consecutive_idle_polls):
    """How long to wait after an empty claim.

    Pure, so the ramp is testable without a clock or a console. The first
    few empty polls stay fast -- a job queued moments after the previous
    one finished is the common case, and making that wait a minute would
    be a regression for no saving.
    """
    if consecutive_idle_polls < IDLE_RAMP_AFTER:
        return POLL_SEC
    return IDLE_MAX_SEC

# Several jobs at once: the console's claim_next_job uses FOR UPDATE SKIP
# LOCKED, so concurrent claims can't collide (app/api/runner/jobs/claim/route.ts).
MAX_CONCURRENT_JOBS = 4


def has_capacity(in_flight_count):
    """Whether the runner should claim another job right now. Pure so the
    cap itself is testable without threads, a real claim, or a console."""
    return in_flight_count < MAX_CONCURRENT_JOBS


def _log(msg):
    print(f"[runner {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _headers():
    return {"Authorization": f"Bearer {RUNNER_TOKEN}"}


def claim_job():
    body = {"runnerId": RUNNER_ID}
    if RUNNER_KINDS:
        body["kinds"] = RUNNER_KINDS
    r = requests.post(f"{CONSOLE_URL}/api/runner/jobs/claim",
                      json=body, headers=_headers(), timeout=30)
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
    """Local scratch only. The venue's uploaded segments are not this
    process's to delete anymore (ADR-125).

    The console deletes them when the job is marked `done`, unless that
    venue has agreed to keep its footage for model training
    (pic-vision-cloud-console/lib/footageRetention.ts). A runner deleting
    them here would quietly override that choice -- and this runner is
    being retired, so the decision lives where it outlasts it.

    Every other outcome keeps them, as it has since 2026-09-19 (PIC-157):
    a failed job's footage is what a retry runs on, and the 14-day expiry
    on <venue>/ingest/ (ADR-112) reclaims what is never retried.
    """
    logs = os.path.join(WORK_DIR, "logs")
    os.makedirs(logs, exist_ok=True)
    log_src = os.path.join(job_dir, "log.txt")
    if os.path.exists(log_src):
        shutil.copyfile(log_src, os.path.join(logs, f"{job['id']}.log"))
    shutil.rmtree(job_dir, ignore_errors=True)


def run_one(job):
    kind = job.get("kind", "reel")
    _log(f"claimed {kind} job {job['id']} ({job.get('camera_label') or job.get('camera_id')})")
    job_dir = os.path.join(WORK_DIR, job["id"])
    try:
        if kind != "calibration":
            raise ValueError(f"{kind} jobs run on the Cloudflare orchestrator (ADR-125), not this calibration runner")
        run_calibration_job(job)
        _log(f"job {job['id']} finished")
    except Exception as e:  # noqa: BLE001 - report every failure back, then keep serving
        _log(f"job {job['id']} FAILED: {e}")
        try:
            patch_job(job["id"], error=str(e)[:2000])
        except Exception as report_err:  # noqa: BLE001
            _log(f"job {job['id']}: couldn't report failure: {report_err}")
    finally:
        _cleanup(job, job_dir)


def _report_unexpected_exception(future):
    """run_one() already catches and reports every failure of its own
    (run_one's try/except) -- this only fires if something escaped THAT,
    which should never happen but must not vanish silently into a Future
    nobody ever calls .result() on if it somehow does."""
    exc = future.exception()
    if exc is not None:
        _log(f"a job's thread raised past its own error handling (this is a bug): {exc}")


def main():
    if not RUNNER_TOKEN:
        sys.exit("RUNNER_TOKEN is not set (add it to .env; same value as the console's)")
    os.makedirs(WORK_DIR, exist_ok=True)
    _log(f"polling {CONSOLE_URL} as {RUNNER_ID}, work dir {WORK_DIR}, "
         f"up to {MAX_CONCURRENT_JOBS} job(s) at once, "
         f"kinds: {', '.join(RUNNER_KINDS)}")
    idle_polls = 0
    in_flight = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS) as executor:
        while True:
            in_flight = {f for f in in_flight if not f.done()}
            if not has_capacity(len(in_flight)):
                # Not claimed, not idle-backoff-worthy: this is a busy
                # runner, not an empty queue, so it checks back at the
                # tight cadence, not the ramped-up idle one.
                time.sleep(POLL_SEC)
                continue
            try:
                job = claim_job()
            except Exception as e:  # noqa: BLE001 - console unreachable: wait, don't die
                _log(f"claim failed: {e}")
                # A failing console is also a reason to back off, not to keep
                # hammering it every few seconds -- which is exactly what this
                # loop did for five days straight during the quota outage.
                idle_polls += 1
                time.sleep(max(POLL_SEC * 4, idle_sleep_sec(idle_polls)))
                continue
            if job is None:
                idle_polls += 1
                time.sleep(idle_sleep_sec(idle_polls))
                continue
            idle_polls = 0  # work exists: go back to polling tightly
            _log(f"claimed job {job['id']}, {len(in_flight) + 1} running concurrently")
            future = executor.submit(run_one, job)
            future.add_done_callback(_report_unexpected_exception)
            in_flight.add(future)


if __name__ == "__main__":
    main()
