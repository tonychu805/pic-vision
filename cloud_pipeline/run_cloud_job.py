"""Cloud-path job orchestrator: capture -> R2 -> RunPod GPU -> R2 -> local
reel build. The RunPod/R2 counterpart to webapp/pipeline.py's run_job.

Isolation (per the operator's request, 2026-08-26): this module never
imports webapp/, never invokes the local TF2.15 environment, and never
touches this workstation's GPU. It reuses only the detector-agnostic,
already-validated downstream logic (src/drift.py, src/calib.py, src/track.py,
src/ball.py, src/select.py, src/render.py via scripts/rank_and_reel.py's
build_reel) -- pure CPU code with no coupling to how the predictions were
produced. Inference itself runs scripts/pod_infer.py UNMODIFIED, copied onto
a RunPod pod and executed there -- the same already-correct, already
bug-fixed inference code (ADR-064, ADR-065), just on different hardware.

Prerequisites (.env, gitignored): RUNPOD_API_KEY, CLOUDFLARE_R2_ACCESS_KEY_ID,
CLOUDFLARE_R2_SECRET_ACCESS_KEY, CLOUDFLARE_R2_ACCOUNT_ID.

Not yet run end-to-end with real GPU inference -- built and reviewable, but
the live test (installing TF2.15 fresh on a pod, running real inference)
hasn't happened yet. See cloud_pipeline/README.md.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile

from dotenv import load_dotenv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# Same pattern as src/verify.py -- without this, RUNPOD_API_KEY and the
# CLOUDFLARE_R2_* vars are only visible if the caller manually sourced .env
# into the shell first, which is exactly the crash a real run hit
# (KeyError: 'CLOUDFLARE_R2_ACCOUNT_ID') before this was added.
load_dotenv(os.path.join(REPO_ROOT, ".env"))

from src import job_log
from src.drift import find_bumps, drift_span
from scripts.check_drift import measure as drift_measure
from scripts.rank_and_reel import build_reel

from cloud_pipeline import r2_storage
from cloud_pipeline import runpod_pod

BUCKET = os.environ.get("CLOUD_PIPELINE_BUCKET", "test-ingest-runpod")
WEIGHTS_LOCAL = "/mnt/fast_scratch/tracknet_weights/weights_k14_epoch19"
WEIGHTS_R2_KEY = "weights/weights_k14_epoch19.tar"
POD_INFER_SCRIPT = os.path.join(REPO_ROOT, "scripts", "pod_infer.py")
POD_R2_HELPER = os.path.join(REPO_ROOT, "cloud_pipeline", "pod_r2_helper.py")

# Same TF 2.15 pin as the local environment (EXPERIMENTS.md 2026-08-16) --
# the last Keras-2 release, needed to load this project's TF2.11-era
# SavedModel weights at all.
POD_SETUP_CMD = (
    "pip install -q boto3 opencv-python-headless 'tensorflow[and-cuda]==2.15.1' "
    ">/workspace/setup.log 2>&1"
)


# Named stages in call order, shared with webapp/pipeline.py's dashboard
# wrapper so it can render a fixed-step progress indicator instead of one
# open-ended "cloud_running" blob (added 2026-08-26, same day the dashboard
# first ran a real job -- the operator asked for visible progress after
# watching one with no feedback beyond a log tail).
STAGES = [
    ("drift_check", "Checking camera drift"),
    ("convert", "Converting to 30fps CFR"),
    ("r2_upload", "Uploading video to cloud storage"),
    ("pod_create", "Creating RunPod GPU pod"),
    ("pod_install", "Installing dependencies on pod"),
    ("pod_download", "Downloading video onto pod"),
    ("inference", "Running TrackNet inference (RunPod GPU)"),
    ("r2_download", "Uploading results, downloading locally"),
    ("reel", "Detecting rallies, ranking, cutting reel"),
]

# pod_infer.py's own periodic progress line, e.g. "  300/29400  75 fps  ETA 6.5 min".
_PROGRESS_RE = re.compile(r"^\s*(\d+)/(\d+)\s+(\d+)\s*fps\s+ETA\s+([\d.]+)\s*min")


def _log(msg, stage=None):
    print(f"[cloud_pipeline] {msg}", flush=True)


class JobCancelled(Exception):
    """Raised when should_cancel_fn() reports the caller asked to cancel.
    Checked before each stage below, not just relied on the caller being
    able to kill an already-created pod after the fact -- a cancel that
    arrives during drift-check/CFR-convert/R2-upload, or in the gap before
    create_pod() actually succeeds, would otherwise go unnoticed and this
    function would create (and get billed for) a real pod nobody is
    tracking anymore."""


def _check_cancel(should_cancel_fn):
    if should_cancel_fn and should_cancel_fn():
        raise JobCancelled()


def ensure_weights_in_r2(log_fn=None):
    """Uploads the k14 SavedModel to R2 once, if not already there. Every
    job after the first reuses it -- no reason to re-upload 130MB per run."""
    log = log_fn or _log
    if r2_storage.object_exists(BUCKET, WEIGHTS_R2_KEY):
        log("weights already in R2, skipping upload")
        return
    log("weights not in R2 yet -- tarring and uploading once (~130MB)")
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
        tar_path = tmp.name
    with tarfile.open(tar_path, "w") as tar:
        tar.add(WEIGHTS_LOCAL, arcname="weights_k14_epoch19")
    r2_storage.upload_file(BUCKET, tar_path, WEIGHTS_R2_KEY)
    os.remove(tar_path)
    log("weights uploaded to R2")


def run_cloud_job(video_path, calib_path, target_sec, session_id, out_dir,
                   log_fn=None, progress_fn=None, pod_id_fn=None,
                   should_cancel_fn=None):
    # log_fn lets a caller (webapp/pipeline.py's run_cloud_job wrapper)
    # capture progress into its own status.json/log.txt instead of only
    # going to stdout -- added so the web dashboard can show live cloud-job
    # progress the same way it already does for local jobs. Defaults to the
    # plain print() behavior for CLI use (unchanged from before).
    #
    # progress_fn(current, total, eta_sec), when given, is called with real
    # numbers parsed from pod_infer.py's own periodic progress line during
    # the inference stage -- the one stage where a live frame count/ETA is
    # actually known, as opposed to a fabricated percentage for stages this
    # project has never benchmarked at this scale (R2 transfer of a
    # video-sized file, etc.).
    #
    # pod_id_fn(pod_id), when given, is called the moment a pod is created --
    # lets a caller (the dashboard's cancel button) record it somewhere it
    # can terminate the pod directly via the RunPod API even if this
    # function's own thread is stuck blocked inside a long ssh_run call.
    #
    # should_cancel_fn(), when given, is checked before each stage below --
    # covers the window pod_id_fn() can't: before a pod exists at all, a
    # cancel request has nothing to kill, so it has to be caught here
    # instead of relied on being stoppable from the outside.
    log = log_fn or _log
    # Calibration is a one-time, per-venue setup step, not part of this
    # per-session job -- see cloud_pipeline/setup_venue_calibration.py.
    # Corrected 2026-08-26: an earlier version launched calibrate_web.py
    # automatically right here, which conflated a once-per-venue event (the
    # camera physically moving is the only reason to redo it, ADR-049) with
    # the per-session job lifecycle (run every time new footage comes in).
    if not os.path.exists(calib_path):
        raise SystemExit(
            f"no calibration at {calib_path}. This is a one-time setup step, "
            f"not something run_cloud_job.py does per job -- run it once "
            f"with:\n"
            f"  python3 -m cloud_pipeline.setup_venue_calibration "
            f"--video <a recording from this venue> --out {calib_path}\n"
            f"then reuse that same path for every future session here.")

    os.makedirs(out_dir, exist_ok=True)
    cfr_video = os.path.join(out_dir, "video_cfr.mp4")
    csv_path = os.path.join(out_dir, "predictions.csv")
    reel_dir = os.path.join(out_dir, "reel")

    # --- Local, GPU-free steps: identical logic to webapp/pipeline.py's
    # drift check and CFR conversion (same functions, same recipe) ---
    _check_cancel(should_cancel_fn)
    log("checking for camera drift...", stage="drift_check")
    samples, _ = drift_measure(video_path, step_sec=60.0, width=960)
    span_x, span_y = drift_span(samples)
    bumps = find_bumps(samples, min_step_px=5.0)
    if bumps:
        log(f"WARNING: {len(bumps)} camera bump(s) detected, max span "
             f"{max(span_x, span_y):.0f}px (ADR-049) -- continuing anyway")
    else:
        log("camera held still")

    _check_cancel(should_cancel_fn)
    log("converting to 30fps CFR...", stage="convert")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-err_detect", "ignore_err",
                     "-i", video_path, "-c:v", "h264_nvenc", "-preset", "p4",
                     "-cq", "20", "-an", "-fps_mode", "cfr", "-r", "30", cfr_video],
                    check=True)

    # Upload a 720p proxy instead of the full-res video -- less to move over
    # the network both ways -- while build_reel() below still cuts the final
    # reel from the untouched full-res cfr_video. Only safe if calib.json
    # records the resolution it was calibrated at (calibration_resolution):
    # pod_infer.py needs that to keep predictions.csv in the *calibration's*
    # pixel space regardless of what resolution it actually processed. A
    # calib.json from before this field existed can't make that promise, so
    # fall back to uploading the full-res video rather than silently risk
    # every downstream pixel coordinate landing in the wrong scale.
    with open(calib_path) as f:
        _calib_check = json.load(f)
    if _calib_check.get("calibration_resolution"):
        log("creating 720p proxy for cloud upload...", stage="convert")
        upload_video = os.path.join(out_dir, "video_proxy_720p.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", cfr_video,
                         "-vf", "scale=-2:720", "-c:v", "h264_nvenc", "-preset", "p4",
                         "-cq", "20", "-an", upload_video], check=True)
    else:
        log("WARNING: calib.json has no calibration_resolution (calibrated "
            "before this field existed) -- uploading full-res video instead "
            "of a 720p proxy, recalibrate this venue to enable the proxy",
            stage="convert")
        upload_video = cfr_video

    # --- Cloud dispatch: this is the part that's actually new ---
    _check_cancel(should_cancel_fn)
    log("checking cached weights in R2...", stage="r2_upload")
    ensure_weights_in_r2(log_fn=log)

    job_prefix = f"jobs/{session_id}"
    video_key = f"{job_prefix}/video_cfr.mp4"
    calib_key = f"{job_prefix}/calib.json"
    csv_key = f"{job_prefix}/predictions.csv"

    log(f"uploading video + calibration to R2 ({job_prefix})...", stage="r2_upload")
    r2_storage.upload_file(BUCKET, upload_video, video_key)
    r2_storage.upload_file(BUCKET, calib_path, calib_key)

    # Last checkpoint before the one step that actually costs money --
    # everything above is cheap/local or a plain storage upload; create_pod()
    # below is the point a cancel request must not miss.
    _check_cancel(should_cancel_fn)

    key_prefix = os.path.join(out_dir, "runpod_key")
    keyfile, pubkey = runpod_pod.generate_ephemeral_keypair(key_prefix)

    log("creating RunPod pod...", stage="pod_create")
    # FALLBACK_GPU_TYPES (2026-08-26): the pinned RTX 2000 Ada tried first
    # (preserves the same-as-local byte-identical guarantee when available),
    # falling back to other Ada-generation cards on capacity failure rather
    # than hard-failing the job -- an explicit availability-over-certainty
    # trade the operator asked for after hitting exactly this on a live run.
    pod_id, gpu_type = runpod_pod.create_pod(
        name=f"cloud-pipeline-{session_id}", ssh_pubkey=pubkey,
        gpu_type_ids=runpod_pod.FALLBACK_GPU_TYPES)
    if pod_id_fn:
        pod_id_fn(pod_id)
    if gpu_type != runpod_pod.FALLBACK_GPU_TYPES[0]:
        log(f"NOTE: pinned GPU unavailable, fell back to {gpu_type} -- output "
            f"is not verified byte-identical to local on this GPU type "
            f"(ADR-043)", stage="pod_create")
    try:
        log(f"pod {pod_id} created ({gpu_type}), waiting for SSH...", stage="pod_create")
        ip, port = runpod_pod.wait_for_ssh(pod_id)
        log(f"pod reachable at {ip}:{port}")

        log("installing TF2.15 + deps on the pod (a few minutes)...", stage="pod_install")
        runpod_pod.ssh_run(ip, port, keyfile, POD_SETUP_CMD, timeout_sec=900)

        log("copying pod_infer.py and the R2 helper to the pod...", stage="pod_install")
        runpod_pod.scp_to(ip, port, keyfile, POD_INFER_SCRIPT, "/workspace/pod_infer.py")
        runpod_pod.scp_to(ip, port, keyfile, POD_R2_HELPER, "/workspace/pod_r2_helper.py")

        r2_env = (
            f"CLOUDFLARE_R2_ACCESS_KEY_ID={os.environ['CLOUDFLARE_R2_ACCESS_KEY_ID']} "
            f"CLOUDFLARE_R2_SECRET_ACCESS_KEY={os.environ['CLOUDFLARE_R2_SECRET_ACCESS_KEY']} "
            f"CLOUDFLARE_R2_ACCOUNT_ID={os.environ['CLOUDFLARE_R2_ACCOUNT_ID']}"
        )

        def pod_r2(action, key, local_path, timeout_sec=600):
            cmd = (f"cd /workspace && {r2_env} python3 pod_r2_helper.py "
                   f"{action} {BUCKET} {key} {local_path}")
            runpod_pod.ssh_run(ip, port, keyfile, cmd, timeout_sec=timeout_sec)

        log("downloading video/calib/weights onto the pod from R2...", stage="pod_download")
        pod_r2("download", video_key, "/workspace/video_cfr.mp4")
        pod_r2("download", calib_key, "/workspace/calib.json")
        pod_r2("download", WEIGHTS_R2_KEY, "/workspace/weights.tar")
        runpod_pod.ssh_run(ip, port, keyfile,
                            # --no-same-owner: the tarball preserves this machine's
                            # uid/gid (confirmed 2026-08-26 -- without this flag, tar
                            # tries to chown to that uid on the pod and fails outright
                            # as "Operation not permitted" running as root there).
                            "cd /workspace && tar -xf weights.tar --no-same-owner",
                            timeout_sec=120)

        log("running TrackNet inference on the pod...", stage="inference")
        infer_cmd = (
            "cd /workspace && python3 pod_infer.py --video video_cfr.mp4 "
            "--model weights_k14_epoch19 --output predictions.csv --calib calib.json"
        )

        def _on_infer_line(line):
            log(line)
            m = _PROGRESS_RE.match(line)
            if m and progress_fn:
                current, total, _fps, eta_min = m.groups()
                progress_fn(int(current), int(total), float(eta_min) * 60.0)

        runpod_pod.ssh_run(ip, port, keyfile, infer_cmd, timeout_sec=7200,
                            on_line=_on_infer_line)

        log("uploading predictions.csv back to R2...", stage="r2_download")
        pod_r2("upload", csv_key, "/workspace/predictions.csv", timeout_sec=120)
    finally:
        log(f"terminating pod {pod_id}...")
        runpod_pod.terminate_pod(pod_id)

    log("downloading predictions.csv locally...", stage="r2_download")
    r2_storage.download_file(BUCKET, csv_key, csv_path)

    # --- Local, GPU-free again: identical detection/ranking/cutting logic
    # to webapp/pipeline.py, via the same shared build_reel() ---
    log("detecting rallies, ranking, cutting reel...", stage="reel")
    result = build_reel(cfr_video, csv_path, calib_path, reel_dir, target_sec, session_id)
    log(f"done: {result}")
    return result


def main():
    p = argparse.ArgumentParser(description="Run a session through the cloud (R2 + RunPod) path")
    p.add_argument("--video", required=True)
    p.add_argument("--calib", required=True,
                   help="path to an existing calib.json for this venue -- "
                        "produced once via cloud_pipeline.setup_venue_calibration, "
                        "then reused for every session at that venue. Not "
                        "generated by this script.")
    p.add_argument("--target-sec", type=float, default=300.0)
    p.add_argument("--session-id", required=True)
    p.add_argument("--out-dir", required=True)
    args = p.parse_args()

    # Bare CLI use had no persistence at all -- print()-only, lost the
    # moment the terminal closed. Reuses the same log_fn mechanism the
    # dashboard path (webapp/pipeline.py) already relies on, rather than a
    # second logging path.
    def _cli_log(msg, stage=None):
        print(f"[cloud_pipeline] {msg}", flush=True)
        job_log.append(args.out_dir, msg)

    run_cloud_job(args.video, args.calib, args.target_sec, args.session_id,
                  args.out_dir, log_fn=_cli_log)


if __name__ == "__main__":
    main()
