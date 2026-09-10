"""ADR-093, decision items 1+2: the pod runs itself.

Everything `cloud_pipeline/run_cloud_job.py` used to do by SSH'ing into a
pod step-by-step from the operator's own workstation (and, before that
script even started, the CFR-convert + proxy encode `run_cloud_job.py` did
*locally* with the operator's own NVIDIA card) happens here instead, as one
process running ON the rented pod. Run via the base image's own
`/start.sh` -> `/post_start.sh` hook (Dockerfile.selfdriving deliberately
does NOT make this the container's CMD -- see that file for why: doing so
made every real RunPod pod hang at container start, differential-tested
against the unmodified base image). Nothing SSHes in, and the operator's
workstation never touches a video byte or a GPU cycle for a job that runs
this way.

Reads its whole job from environment variables (set at pod-creation time,
`runpod_pod.create_selfdriving_pod`) rather than a command line, since
that's the one interface RunPod's own pod-creation API gives a caller:

    JOB_ID              -- the console's job row id
    BUCKET               R2 bucket name
    SEGMENT_KEYS_JSON     JSON list of R2 keys, the venue's raw recording
                           segments (already uploaded by the desktop app --
                           this is the actual "delete the operator's
                           machine from the data path" fix: those bytes go
                           venue -> R2 -> pod directly now, never through
                           the operator's own uplink)
    CALIB_JSON            the venue's calib.json, inline (small, no need
                           for its own R2 round trip)
    TARGET_SEC            reel length target
    SESSION_ID
    CONSOLE_URL, RUNNER_TOKEN  same console API job_runner.py already
                           uses (PATCH /api/runner/jobs/<id>) -- reused
                           as-is rather than inventing a second reporting
                           path. Known, accepted gap (ADR-093's own open
                           risks list): this is the operator's
                           account-wide runner token, not a token scoped
                           to this one job. Scoping that is real future
                           work, not done here.
    CLOUDFLARE_R2_*        same R2 creds the operator's workstation
                           already has -- same gap as above, not scoped.
    RUNPOD_API_KEY         so this pod can delete itself when done. Same
                           gap: this is the full account key, not scoped
                           to "delete only this pod."

Reuses, unmodified: `scripts/pod_infer.py` (subprocess -- the ADR-064/065
byte-identical-output guarantee is pinned to not touching this code), and
`build_reel`/`build_burst_reel` (imported directly, no reason to subprocess
these now that this runs as one process instead of over SSH).

Progress reporting doubles as the cancellation channel: every PATCH to the
console is answered with whether the operator asked to cancel (same
`cancelRequested` mechanic `job_runner.py`'s own `patch_job` already uses)
-- checked between stages, same as `run_cloud_job.py`'s `_check_cancel`.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

import boto3
import requests

REPO_ROOT = "/workspace"
sys.path.insert(0, REPO_ROOT)

from scripts.check_drift import measure as drift_measure  # noqa: E402
from scripts.rank_and_reel import WEIGHTS, build_reel  # noqa: E402
from scripts.burst_moment_reel import build_burst_reel  # noqa: E402
from src.drift import drift_span, find_bumps  # noqa: E402
from src.video_quality import BLOCK_BELOW_FPS, check_video  # noqa: E402

WORKDIR = "/workspace/job"
WEIGHTS_R2_KEY = "weights/weights_k14_epoch19.tar"
WEIGHTS_LOCAL = "/workspace/weights_k14_epoch19"
BURST_TARGET_SEC = 30.0  # matches pod_cut.py's own pin, same reasoning

# pod_infer.py's own periodic progress line, e.g. "  300/29400  75 fps  ETA 6.5 min"
# -- printed every 300 frames (~5s at typical throughput), same regex
# run_cloud_job.py's SSH-streaming path already used.
_PROGRESS_RE = re.compile(r"^\s*(\d+)/(\d+)\s+(\d+)\s*fps\s+ETA\s+([\d.]+)\s*min")

# A status PATCH every 5s would be ~700 requests over a long session's
# inference stage -- fine for the console, but no reason to be that
# chatty. This also doubles as the heartbeat that keeps
# claim_next_job's stale-runner rule from reclaiming a job mid-inference
# (job.kind's PATCH route bumps updated_at on every call) -- inference on
# a full session can run far longer than that staleness window, so
# something has to report in periodically for its whole duration, not
# just at stage boundaries.
PROGRESS_PATCH_INTERVAL_SEC = 20

CONSOLE_URL = os.environ.get("CONSOLE_URL", "https://console.picvisionai.com").rstrip("/")
RUNNER_TOKEN = os.environ["RUNNER_TOKEN"]
JOB_ID = os.environ["JOB_ID"]
BUCKET = os.environ["BUCKET"]


def _log(msg):
    print(f"[pod-driver {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _r2_client():
    account_id = os.environ["CLOUDFLARE_R2_ACCOUNT_ID"]
    return boto3.client(
        "s3", endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["CLOUDFLARE_R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["CLOUDFLARE_R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def patch_job(**fields):
    """Same contract as job_runner.py's patch_job: True means the console
    wants this job stopped (operator cancelled, or the row moved on
    without us) -- checked by the caller before every stage."""
    try:
        r = requests.patch(f"{CONSOLE_URL}/api/runner/jobs/{JOB_ID}",
                           json=fields, headers={"Authorization": f"Bearer {RUNNER_TOKEN}"},
                           timeout=30)
        if r.status_code == 409:
            return True
        r.raise_for_status()
        return bool(r.json().get("cancelRequested"))
    except requests.RequestException as e:
        # The console being briefly unreachable isn't itself a reason to
        # abandon a job already running on a GPU we're paying for -- log
        # and keep going, same as a dropped SSH connection wouldn't have
        # stopped the pod under the old design either.
        _log(f"WARNING: status report failed ({e}), continuing")
        return False


class Cancelled(Exception):
    pass


def _check_cancel(stage, message):
    # progress=None deliberately included here (unlike the inference
    # heartbeat below): this always marks a real stage change, and the
    # console route only clears the old stage's progress reading when the
    # field is present -- an omitted field would leave the previous
    # stage's frame count showing against this stage's name.
    if patch_job(stage=stage, message=message, progress=None):
        raise Cancelled()


INFERENCE_TIMEOUT_SEC = 7200  # same ceiling run_cloud_job.py's ssh_run(infer_cmd) used


def _run_inference_streaming(cmd):
    """Runs pod_infer.py, patching the console with real progress every
    PROGRESS_PATCH_INTERVAL_SEC -- not just at stage start/end. Without
    this, inference (which can run far longer than the console's
    stale-runner reclaim window) would report in exactly once before going
    silent for the whole run, risking another runner claiming this job out
    from under a pod that's still working on it, and leaving the progress
    bar frozen the whole time. Also the one place a cancel mid-inference
    actually has to kill a live process, not just stop before the next
    stage -- inference is the single longest step by far.

    A plain `for line in proc.stdout` blocks on the read syscall itself
    with no timeout -- a stall with zero output (e.g. GPU init hanging
    before the first progress line) would never trip a heartbeat, the
    exact failure mode runpod_pod.py's ssh_run() already documented and
    fixed with a reader thread + queue. Same fix here, so a heartbeat and
    a cancel-check both still happen even if pod_infer.py goes quiet."""
    import queue
    import threading

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1)
    line_q = queue.Queue()

    def _read_lines():
        try:
            for line in proc.stdout:
                line_q.put(line.rstrip("\n"))
        finally:
            line_q.put(None)

    reader = threading.Thread(target=_read_lines, daemon=True)
    reader.start()

    deadline = time.time() + INFERENCE_TIMEOUT_SEC
    last_patch_at = 0.0
    try:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                proc.kill()
                raise TimeoutError(f"inference exceeded {INFERENCE_TIMEOUT_SEC}s")
            try:
                line = line_q.get(timeout=min(remaining, PROGRESS_PATCH_INTERVAL_SEC))
            except queue.Empty:
                line = None  # no output this interval -- still due for a heartbeat below
            else:
                if line is None:  # sentinel: process's stdout closed, it's finished
                    break
                _log(line)

            due = time.time() - last_patch_at >= PROGRESS_PATCH_INTERVAL_SEC
            if not due:
                continue
            m = _PROGRESS_RE.match(line) if line else None
            # Only include progress when this tick actually has a fresh
            # value -- omitting the field (not sending progress=None) on a
            # plain heartbeat leaves the console's last real reading in
            # place instead of flickering it to blank every
            # PROGRESS_PATCH_INTERVAL_SEC.
            fields = {"stage": "inference"}
            if m:
                current, total, _fps, eta_min = m.groups()
                fields["progress"] = {"current": int(current), "total": int(total), "eta_sec": float(eta_min) * 60.0}
            cancel = patch_job(**fields)
            last_patch_at = time.time()
            if cancel:
                proc.terminate()
                proc.wait(timeout=10)
                raise Cancelled()
        returncode = proc.wait(timeout=max(0.0, deadline - time.time()))
    finally:
        if proc.stdout:
            proc.stdout.close()
        reader.join(timeout=5.0)
        if proc.poll() is None:
            proc.kill()
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, cmd)


def _self_terminate(pod_id):
    key = os.environ.get("RUNPOD_API_KEY")
    if not (key and pod_id):
        _log("no RUNPOD_API_KEY/pod id available -- cannot self-terminate, "
             "an external sweep must catch this (ADR-093 open risk)")
        return
    try:
        requests.delete(f"https://rest.runpod.io/v1/pods/{pod_id}",
                        headers={"Authorization": f"Bearer {key}"}, timeout=30)
        _log(f"self-terminated pod {pod_id}")
    except requests.RequestException as e:
        _log(f"WARNING: self-terminate failed ({e}) -- an external sweep must catch this")


def run():
    s3 = _r2_client()
    os.makedirs(WORKDIR, exist_ok=True)

    segment_keys = json.loads(os.environ["SEGMENT_KEYS_JSON"])
    calib = json.loads(os.environ["CALIB_JSON"])
    target_sec = float(os.environ.get("TARGET_SEC", "300"))
    session_id = os.environ.get("SESSION_ID", JOB_ID)

    calib_path = os.path.join(WORKDIR, "calib.json")
    with open(calib_path, "w") as f:
        json.dump(calib, f)

    # --- Pull the venue's own raw segments straight from R2. This is the
    # actual fix: under the old design the operator's workstation
    # downloaded these, converted them, and re-uploaded a proxy -- two
    # hops through the operator's own uplink for bytes that never needed
    # to go anywhere near it. ---
    _check_cancel("download", f"downloading {len(segment_keys)} recording segment(s)...")
    seg_dir = os.path.join(WORKDIR, "segments")
    os.makedirs(seg_dir, exist_ok=True)
    local_segments = []
    for key in segment_keys:
        local = os.path.join(seg_dir, os.path.basename(key))
        s3.download_file(BUCKET, key, local)
        local_segments.append(local)

    if len(local_segments) == 1:
        raw_video = local_segments[0]
    else:
        list_path = os.path.join(WORKDIR, "concat_list.txt")
        raw_video = os.path.join(WORKDIR, "session_full.mkv")
        with open(list_path, "w") as f:
            for p in sorted(local_segments):
                f.write(f"file '{p}'\n")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", list_path, "-c", "copy", raw_video], check=True)

    # --- Same input gate run_cloud_job.py ran locally before spending
    # anything on this session -- cheapest check, still first. ---
    _check_cancel("input_check", "checking the recording's frame rate...")
    quality = check_video(raw_video)
    if not quality["passes"]:
        patch_job(error=f"This recording can't be processed: {quality['reason']}")
        return

    _check_cancel("drift_check", "checking for camera drift...")
    samples, _ = drift_measure(raw_video, step_sec=60.0, width=960)
    bumps = find_bumps(samples, min_step_px=5.0)
    if bumps:
        span_x, span_y = drift_span(samples)
        _log(f"WARNING: {len(bumps)} camera bump(s), max span "
             f"{max(span_x, span_y):.0f}px (ADR-049) -- continuing anyway")

    # --- The step that used to need the operator's own NVIDIA card
    # (ADR-093 reason 1). Identical ffmpeg invocation to run_cloud_job.py's
    # old local version -- only WHERE it runs changed. ---
    _check_cancel("convert", "converting to 30fps CFR...")
    cfr_video = os.path.join(WORKDIR, "video_cfr.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-err_detect", "ignore_err",
                     "-i", raw_video, "-c:v", "h264_nvenc", "-preset", "p4",
                     "-cq", "20", "-an", "-fps_mode", "cfr", "-r", "30", cfr_video],
                    check=True)

    _check_cancel("proxy", "preparing the inference/upload resolution...")
    if not calib.get("calibration_resolution"):
        _log("WARNING: calib.json has no calibration_resolution -- using full-res")
        proxy_video = cfr_video
    else:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=height", "-of", "csv=p=0", cfr_video],
            capture_output=True, text=True, check=True)
        native_height = int(probe.stdout.strip())
        if native_height <= 1080:
            proxy_video = cfr_video
        else:
            proxy_video = os.path.join(WORKDIR, "video_proxy_1080p.mp4")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", cfr_video,
                             "-vf", "scale=-2:1080", "-c:v", "h264_nvenc", "-preset", "p4",
                             "-cq", "20", "-an", proxy_video], check=True)

    # --- Weights: same R2-cached tarball every pod-based run already used. ---
    _check_cancel("inference", "fetching model weights...")
    if not os.path.exists(WEIGHTS_LOCAL):
        weights_tar = os.path.join(WORKDIR, "weights.tar")
        s3.download_file(BUCKET, WEIGHTS_R2_KEY, weights_tar)
        subprocess.run(["tar", "-xf", weights_tar, "-C", "/workspace", "--no-same-owner"],
                       check=True)

    _log("running TrackNet inference...")
    csv_path = os.path.join(WORKDIR, "predictions.csv")
    infer_cmd = ["python3", os.path.join(REPO_ROOT, "scripts", "pod_infer.py"),
                 "--video", proxy_video, "--model", WEIGHTS_LOCAL,
                 "--output", csv_path, "--calib", calib_path]
    _run_inference_streaming(infer_cmd)

    # --- Cut, same as pod_cut.py did over SSH -- called directly now,
    # same functions, no subprocess/SSH round trip needed for something
    # already running in-process. ---
    _check_cancel("cut", "detecting rallies, ranking, cutting reel...")
    reel_dir = os.path.join(WORKDIR, "reel")
    full_result = build_reel(proxy_video, csv_path, calib_path, os.path.join(reel_dir, "full"),
                              target_sec, session_id, weights=WEIGHTS, include_chronological=False)
    burst_result = build_burst_reel(proxy_video, csv_path, calib_path, os.path.join(reel_dir, "burst"),
                                     BURST_TARGET_SEC, session_id)
    has_burst = burst_result["chronological"] is not None
    stats = {"full": full_result["stats"], "burst": burst_result["stats"] if has_burst else None}

    _check_cancel("r2_download", "uploading finished reel(s) to R2...")
    reel_id = os.environ.get("REEL_ID")
    burst_reel_id = os.environ.get("BURST_REEL_ID")
    ranked_key = f"reels/{reel_id}.mp4"
    s3.upload_file(os.path.join(reel_dir, "full", "highlight_by_rank.mp4"), BUCKET, ranked_key)
    reels = [{"kind": "full", "reel_id": reel_id, "key": ranked_key, "stats": stats["full"]}]
    if has_burst:
        burst_key = f"reels/{burst_reel_id}.mp4"
        s3.upload_file(os.path.join(reel_dir, "burst", "highlight.mp4"), BUCKET, burst_key)
        reels.append({"kind": "burst", "reel_id": burst_reel_id, "key": burst_key, "stats": stats["burst"]})

    patch_job(done=True, stage="done", message="done", progress=None, result={
        "share_id": os.environ.get("SHARE_ID"), "reel_bucket": BUCKET,
        "reels": reels, "stats": stats,
    })
    _log(f"done: {reels}")


def main():
    pod_id = os.environ.get("RUNPOD_POD_ID")  # RunPod sets this itself, every pod
    try:
        run()
    except Cancelled:
        _log("cancelled by operator")
        patch_job(cancelled=True, message="cancelled")
    except Exception as e:  # noqa: BLE001 -- report every failure, this pod is billed either way
        _log(f"FAILED: {e}")
        try:
            patch_job(error=str(e)[:2000])
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        _self_terminate(pod_id)


if __name__ == "__main__":
    main()
