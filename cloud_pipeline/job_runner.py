"""Operator-side job runner (ADR-084, thin agent).

Polls the cloud console for queued jobs. Reel jobs (ADR-093) are handed
straight to a self-driving RunPod pod (cloud_pipeline/pod_driver.py): this
process packages pod_driver.py + its dependency closure as a tarball,
uploads it to R2, creates the pod against the stock, unmodified
DEFAULT_IMAGE with a `dockerStartCmd` that fetches and runs that tarball
(runpod_pod.py's create_selfdriving_pod), and then just waits for the pod
to disappear (self-terminate) or hit a deadline -- it never downloads a
video, runs ffmpeg, or holds an SSH connection anymore. The pod reports
its own progress to the console over HTTPS (PATCH /api/runner/jobs/<id>)
and inserts the finished `reels` rows itself via that same route; this
process never sees a video byte for a reel job.

Deliberately NOT a custom baked image (tried first, abandoned 2026-09-10):
see runpod_pod.py's create_selfdriving_pod for why -- a derived image
reliably hung at container start on RunPod across 8 real attempts, for a
reason never identified, despite working perfectly in local Docker every
time.

Calibration fits still run right here (kind = "calibration"): the operator
clicked 14 points on a snapshot in the console; the fit is
save_calibration.build_calibration(), unchanged, and the result goes back
onto the camera row for every later reel job to use. That's CPU-only,
seconds long, and never needed a pod in the first place.

Needs, from .env: RUNNER_TOKEN (same value set on the console), the
CLOUDFLARE_R2_* keys and RUNPOD_API_KEY the pipeline already needs.
Optional: CONSOLE_URL, RUNNER_WORK_DIR, RUNNER_ID.

    make runner            # or: .venv/bin/python -m cloud_pipeline.job_runner
"""
import json
import os
import shutil
import socket
import sys
import tarfile
import tempfile
import time
import uuid

import requests
from dotenv import load_dotenv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
load_dotenv(os.path.join(REPO_ROOT, ".env"))

from cloud_pipeline import r2_storage, runpod_pod  # noqa: E402
from cloud_pipeline.save_calibration import build_calibration  # noqa: E402

CONSOLE_URL = os.environ.get("CONSOLE_URL", "https://console.picvisionai.com").rstrip("/")
RUNNER_TOKEN = os.environ.get("RUNNER_TOKEN")
WORK_DIR = os.environ.get("RUNNER_WORK_DIR", os.path.join(REPO_ROOT, "cloud_pipeline", "jobs", "runner"))
RUNNER_ID = os.environ.get("RUNNER_ID", socket.gethostname())

POLL_SEC = 5
TERMINAL_STAGES = ("done", "error", "cancelled")

# How often to ask RunPod whether the pod is still there, and how long to
# wait before deciding it's stuck rather than just slow. 15s is cheap
# against RunPod's own API (unlike the old MIRROR_SEC=3, which was reading
# a local file); 3 hours covers convert+proxy+inference+cut on the
# longest realistic session with real margin -- pod_driver.py's own
# inference step alone is capped at 7200s (2h), and every step before or
# after it is minutes, not hours. A pod that hasn't self-terminated by
# then almost certainly hit something pod_driver.py's own exception
# handling didn't catch (a host failure, an OOM kill) -- ADR-093's still-
# open "who kills an orphaned pod" risk, covered here rather than left to
# an operator noticing a stuck billing pod by hand.
POD_POLL_SEC = 15
JOB_DEADLINE_SEC = 3 * 3600

# ADR-101 documented a real, previously-unexplained RunPod failure mode:
# a pod that gets created but never reports any progress at all -- stuck
# retrying its own container start on a bad host, confirmed there via
# manual observation (repeated "start container: begin" with no further
# output), root cause never identified. Every real successful cold start
# measured for this same image landed under ~160s; 8 minutes is generous
# margin above that and comfortably under claim_next_job's own 15-minute
# stale-'running' reclaim window, so this fires well before that RPC
# could reclaim the same job out from under this still-live wait loop.
# This does not explain *why* a pod gets stuck -- nothing here can, since
# the container never runs any of this project's own code -- it only
# stops the operator from waiting up to JOB_DEADLINE_SEC to find out.
FIRST_CHECKIN_TIMEOUT_SEC = 8 * 60


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


def get_job_updated_at(job_id):
    """Best-effort read of a job's current updated_at -- None on any
    failure (network hiccup, 404), so a transient read error is never
    mistaken for "no progress" the way a genuinely stuck pod would be;
    the caller only acts once this returns the same value repeatedly
    across a real time window, not on a single failed read."""
    try:
        r = requests.get(f"{CONSOLE_URL}/api/runner/jobs/{job_id}", headers=_headers(), timeout=30)
        r.raise_for_status()
        return r.json().get("updated_at")
    except Exception:  # noqa: BLE001 - a failed status check must not crash the wait loop
        return None


# pod_driver.py's own dependency closure -- same explicit-file-list
# reasoning as run_cloud_job.py's old POD_REEL_DEPS comment (a new
# unrelated src/ module shouldn't silently ride along), just tarred at
# job time instead of baked into an image (see runpod_pod.py's
# create_selfdriving_pod for why: baking it into an image was tried and
# reliably broke container start on RunPod, for a reason never found).
POD_DEPS_FILES = [
    "src/__init__.py", "src/job_log.py", "src/calib.py", "src/ball.py",
    "src/track.py", "src/select.py", "src/tracknet.py", "src/render.py",
    "src/drift.py", "src/video_quality.py",
    "scripts/check_drift.py", "scripts/rank_and_reel.py",
    "scripts/burst_moment_reel.py", "scripts/top_rallies_reel.py",
    "scripts/pod_infer.py",
]
POD_DEPS_KEY = "pipeline/pod_deps.tar"


def _upload_pod_deps(bucket):
    """Fresh every job, not cached like ensure_weights_in_r2() -- this
    tarball is source code, and a stale copy would silently run old code
    on the pod. It's a few hundred KB of Python, not 130MB of weights;
    the upload cost of never risking staleness is negligible."""
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
        tar_path = tmp.name
    try:
        with tarfile.open(tar_path, "w") as tar:
            tar.add(os.path.join(REPO_ROOT, "cloud_pipeline", "pod_driver.py"), arcname="pod_driver.py")
            for rel in POD_DEPS_FILES:
                tar.add(os.path.join(REPO_ROOT, rel), arcname=rel)
        r2_storage.upload_file(bucket, tar_path, POD_DEPS_KEY)
    finally:
        os.remove(tar_path)
    return r2_storage.generate_presigned_url(bucket, POD_DEPS_KEY, expires_in=3600)


def run_reel_job(job):
    """ADR-093: hand the whole job to a self-driving pod and wait for it to
    disappear. Everything past this function -- downloading the venue's
    segments, converting, running inference, cutting, uploading, and
    telling the console about all of it -- happens on the pod
    (cloud_pipeline/pod_driver.py), not here. This process holds no video,
    runs no ffmpeg, and opens no SSH connection for a reel job anymore."""
    job_id = job["id"]
    segment_keys = job.get("segment_keys") or []
    if not segment_keys:
        raise RuntimeError("job has no recording segments")

    bootstrap_url = _upload_pod_deps(job["bucket"])

    # Minted here, not on the pod: the console needs these ids to exist
    # (in the pod's final result) as soon as the pod reports done, and
    # there's no coordination reason they can't just be handed to the pod
    # instead of round-tripped through it.
    env = {
        "JOB_ID": job_id,
        "BUCKET": job["bucket"],
        "BOOTSTRAP_URL": bootstrap_url,
        "SEGMENT_KEYS_JSON": json.dumps(segment_keys),
        "CALIB_JSON": json.dumps(job["calib"]),
        "TARGET_SEC": str(job.get("target_sec") or 180),
        "SESSION_ID": job.get("session_id") or job_id,
        "REEL_ID": str(uuid.uuid4()),
        "BURST_REEL_ID": str(uuid.uuid4()),
        "SHARE_ID": str(uuid.uuid4()),
        "CONSOLE_URL": CONSOLE_URL,
        "RUNNER_TOKEN": RUNNER_TOKEN,
        "CLOUDFLARE_R2_ACCESS_KEY_ID": os.environ["CLOUDFLARE_R2_ACCESS_KEY_ID"],
        "CLOUDFLARE_R2_SECRET_ACCESS_KEY": os.environ["CLOUDFLARE_R2_SECRET_ACCESS_KEY"],
        "CLOUDFLARE_R2_ACCOUNT_ID": os.environ["CLOUDFLARE_R2_ACCOUNT_ID"],
        "RUNPOD_API_KEY": os.environ["RUNPOD_API_KEY"],
    }

    # Captured before pod creation, from the row's own state as of the
    # claim (claim_next_job's own UPDATE sets updated_at=now() as part of
    # claiming it) -- the baseline the first-checkin check below compares
    # against. Nothing in this wait loop itself ever PATCHes the job, so
    # any change at all can only mean pod_driver.py actually started and
    # ran its own first _check_cancel() call.
    baseline_updated_at = job.get("updated_at")
    first_checkin_seen = False

    _log(f"job {job_id}: creating self-driving pod...")
    pod_id, gpu_type = runpod_pod.create_selfdriving_pod(
        name=f"cloud-pipeline-{env['SESSION_ID']}", env=env,
        gpu_type_ids=runpod_pod.FALLBACK_GPU_TYPES)
    _log(f"job {job_id}: pod {pod_id} created ({gpu_type}), waiting for it to finish "
         f"(it reports its own progress to the console from here)")

    pod_created_at = time.monotonic()
    deadline = time.monotonic() + JOB_DEADLINE_SEC
    while time.monotonic() < deadline:
        time.sleep(POD_POLL_SEC)

        if not first_checkin_seen:
            current_updated_at = get_job_updated_at(job_id)
            # None means this particular check failed (network hiccup,
            # console blip) -- inconclusive, not evidence of a stuck pod,
            # so it's left to the next poll rather than counted toward
            # the timeout below. Only a CONFIRMED read showing no change
            # counts.
            if current_updated_at is not None and current_updated_at != baseline_updated_at:
                first_checkin_seen = True
            elif current_updated_at is not None and \
                    time.monotonic() - pod_created_at > FIRST_CHECKIN_TIMEOUT_SEC:
                # No progress signal at all, well past every successful
                # cold start measured for this image (ADR-101: ~160s
                # worst case) -- the known "stuck at container start"
                # pattern, not a job that's just running slowly. Fails
                # fast rather than waiting out JOB_DEADLINE_SEC; does not
                # auto-retry, matching the deadline path below -- a human
                # decides whether to try again, same as every other
                # reel-job failure.
                _log(f"job {job_id}: pod {pod_id} reported no progress within "
                     f"{FIRST_CHECKIN_TIMEOUT_SEC}s of being created -- likely "
                     f"stuck at container start (ADR-101), terminating")
                runpod_pod.terminate_pod(pod_id)
                patch_job(job_id, error=(
                    f"pod reported no progress within {FIRST_CHECKIN_TIMEOUT_SEC // 60} "
                    "minutes of being created -- terminated as a likely stuck "
                    "container start (see DECISIONS.md ADR-101); click Retry"))
                return

        if not runpod_pod.pod_exists(pod_id):
            # A pod that disappeared having genuinely finished already put
            # the job into a terminal state (done/error/cancelled) via its
            # own PATCH -- this call then hits the console's own
            # status != 'running' guard and does nothing (409, silently
            # ignored here). But "the pod is gone" and "the pod told the
            # console how it ended" are NOT the same fact: a crash, an
            # OOM kill, or the pod being torn down by anything other than
            # its own `finally` (confirmed for real, 2026-09-10 -- a pod
            # killed out from under this exact loop left its job stuck at
            # status='running' forever, because nothing here checked)
            # skips pod_driver.py's own reporting entirely. This call is
            # what turns that into an actual error instead of a job that
            # silently never finishes.
            patch_job(job_id, error="pod disappeared without reporting a final status")
            _log(f"job {job_id}: pod {pod_id} finished")
            return

    # Nothing but a hung/crashed pod gets here: pod_driver.py reports its
    # own terminal status (done/error/cancelled) and self-terminates
    # before this deadline in every path its own exception handling can
    # catch. This is the backstop for what it can't -- a host failure, an
    # OOM kill, anything that takes the process out before its own
    # `finally` runs -- so the job doesn't sit "running" forever and the
    # pod doesn't keep billing for nothing.
    _log(f"job {job_id}: pod {pod_id} exceeded {JOB_DEADLINE_SEC}s without finishing -- "
         f"terminating and marking errored")
    runpod_pod.terminate_pod(pod_id)
    patch_job(job_id, error=f"job exceeded {JOB_DEADLINE_SEC // 60} minutes without finishing")


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
