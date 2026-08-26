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
import os
import subprocess
import sys
import tarfile
import tempfile
import time

from dotenv import load_dotenv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# Same pattern as src/verify.py -- without this, RUNPOD_API_KEY and the
# CLOUDFLARE_R2_* vars are only visible if the caller manually sourced .env
# into the shell first, which is exactly the crash a real run hit
# (KeyError: 'CLOUDFLARE_R2_ACCOUNT_ID') before this was added.
load_dotenv(os.path.join(REPO_ROOT, ".env"))

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
CALIBRATE_WEB_SCRIPT = os.path.join(REPO_ROOT, "calibrate_web.py")

# Same TF 2.15 pin as the local environment (EXPERIMENTS.md 2026-08-16) --
# the last Keras-2 release, needed to load this project's TF2.11-era
# SavedModel weights at all.
POD_SETUP_CMD = (
    "pip install -q boto3 opencv-python-headless 'tensorflow[and-cuda]==2.15.1' "
    ">/workspace/setup.log 2>&1"
)


def _log(msg):
    print(f"[cloud_pipeline] {msg}", flush=True)


def ensure_weights_in_r2():
    """Uploads the k14 SavedModel to R2 once, if not already there. Every
    job after the first reuses it -- no reason to re-upload 130MB per run."""
    if r2_storage.object_exists(BUCKET, WEIGHTS_R2_KEY):
        _log("weights already in R2, skipping upload")
        return
    _log("weights not in R2 yet -- tarring and uploading once (~130MB)")
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
        tar_path = tmp.name
    with tarfile.open(tar_path, "w") as tar:
        tar.add(WEIGHTS_LOCAL, arcname="weights_k14_epoch19")
    r2_storage.upload_file(BUCKET, tar_path, WEIGHTS_R2_KEY)
    os.remove(tar_path)
    _log("weights uploaded to R2")


def ensure_calibration(video_path, calib_path, at_sec=60.0, port=8765, poll_sec=2.0):
    """Closes the gap this route had vs. webapp/app.py: that one collects
    calibration in-browser per job; this one, until now, just required a
    calib.json to already exist. Reuses calibrate_web.py -- the existing
    standalone browser-click tool, already independent of webapp/, so this
    doesn't reintroduce the coupling the isolation design avoided.

    calibrate_web.py blocks forever (server.serve_forever()) and expects a
    human to Ctrl+C once they see "saved ..." -- there's no clean exit signal
    to wait on. So this launches it as a subprocess and polls for calib_path
    to appear instead, then terminates it -- the operator still does the
    actual clicking, but the orchestrator no longer needs a second manual
    step run separately beforehand.
    """
    if os.path.exists(calib_path):
        _log(f"calibration already exists at {calib_path}, skipping")
        return

    _log("no calibration found -- launching calibrate_web.py")
    proc = subprocess.Popen(
        [sys.executable, CALIBRATE_WEB_SCRIPT, video_path,
         "--at", str(at_sec), "--out", calib_path, "--port", str(port)])
    _log(f"open http://<this-machine>:{port}/ in a browser, click the 12 court "
         f"points + 2 net-tape points, then Save")
    _log("waiting for calibration to be saved...")
    try:
        while not os.path.exists(calib_path):
            if proc.poll() is not None:
                raise RuntimeError(
                    "calibrate_web.py exited before a calibration was saved "
                    f"(exit code {proc.returncode})")
            time.sleep(poll_sec)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    _log(f"calibration saved to {calib_path}")


def run_cloud_job(video_path, calib_path, target_sec, session_id, out_dir,
                   calib_at_sec=60.0, calib_port=8765):
    os.makedirs(out_dir, exist_ok=True)
    cfr_video = os.path.join(out_dir, "video_cfr.mp4")
    csv_path = os.path.join(out_dir, "predictions.csv")
    reel_dir = os.path.join(out_dir, "reel")

    ensure_calibration(video_path, calib_path, at_sec=calib_at_sec, port=calib_port)

    # --- Local, GPU-free steps: identical logic to webapp/pipeline.py's
    # drift check and CFR conversion (same functions, same recipe) ---
    _log("checking for camera drift...")
    samples, _ = drift_measure(video_path, step_sec=60.0, width=960)
    span_x, span_y = drift_span(samples)
    bumps = find_bumps(samples, min_step_px=5.0)
    if bumps:
        _log(f"WARNING: {len(bumps)} camera bump(s) detected, max span "
             f"{max(span_x, span_y):.0f}px (ADR-049) -- continuing anyway")
    else:
        _log("camera held still")

    _log("converting to 30fps CFR...")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-err_detect", "ignore_err",
                     "-i", video_path, "-c:v", "h264_nvenc", "-preset", "p4",
                     "-cq", "20", "-an", "-fps_mode", "cfr", "-r", "30", cfr_video],
                    check=True)

    # --- Cloud dispatch: this is the part that's actually new ---
    ensure_weights_in_r2()

    job_prefix = f"jobs/{session_id}"
    video_key = f"{job_prefix}/video_cfr.mp4"
    calib_key = f"{job_prefix}/calib.json"
    csv_key = f"{job_prefix}/predictions.csv"

    _log(f"uploading CFR video + calibration to R2 ({job_prefix})...")
    r2_storage.upload_file(BUCKET, cfr_video, video_key)
    r2_storage.upload_file(BUCKET, calib_path, calib_key)

    key_prefix = os.path.join(out_dir, "runpod_key")
    keyfile, pubkey = runpod_pod.generate_ephemeral_keypair(key_prefix)

    _log("creating RunPod pod...")
    pod_id = runpod_pod.create_pod(name=f"cloud-pipeline-{session_id}", ssh_pubkey=pubkey)
    try:
        _log(f"pod {pod_id} created, waiting for SSH...")
        ip, port = runpod_pod.wait_for_ssh(pod_id)
        _log(f"pod reachable at {ip}:{port}")

        _log("installing TF2.15 + deps on the pod (a few minutes)...")
        runpod_pod.ssh_run(ip, port, keyfile, POD_SETUP_CMD, timeout_sec=900)

        _log("copying pod_infer.py and the R2 helper to the pod...")
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

        _log("downloading video/calib/weights onto the pod from R2...")
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

        _log("running TrackNet inference on the pod...")
        infer_cmd = (
            "cd /workspace && python3 pod_infer.py --video video_cfr.mp4 "
            "--model weights_k14_epoch19 --output predictions.csv --calib calib.json"
        )
        runpod_pod.ssh_run(ip, port, keyfile, infer_cmd, timeout_sec=7200)

        _log("uploading predictions.csv back to R2...")
        pod_r2("upload", csv_key, "/workspace/predictions.csv", timeout_sec=120)
    finally:
        _log(f"terminating pod {pod_id}...")
        runpod_pod.terminate_pod(pod_id)

    _log("downloading predictions.csv locally...")
    r2_storage.download_file(BUCKET, csv_key, csv_path)

    # --- Local, GPU-free again: identical detection/ranking/cutting logic
    # to webapp/pipeline.py, via the same shared build_reel() ---
    _log("detecting rallies, ranking, cutting reel...")
    result = build_reel(cfr_video, csv_path, calib_path, reel_dir, target_sec, session_id)
    _log(f"done: {result}")
    return result


def main():
    p = argparse.ArgumentParser(description="Run a session through the cloud (R2 + RunPod) path")
    p.add_argument("--video", required=True)
    p.add_argument("--calib", default=None,
                   help="path to calib.json -- reused if it already exists; "
                        "otherwise calibrate_web.py is launched to create it "
                        "there (default: <out-dir>/calib.json)")
    p.add_argument("--calib-at", type=float, default=60.0,
                   help="seconds into the video to grab the calibration frame from")
    p.add_argument("--calib-port", type=int, default=8765)
    p.add_argument("--target-sec", type=float, default=300.0)
    p.add_argument("--session-id", required=True)
    p.add_argument("--out-dir", required=True)
    args = p.parse_args()
    calib_path = args.calib or os.path.join(args.out_dir, "calib.json")
    os.makedirs(args.out_dir, exist_ok=True)
    run_cloud_job(args.video, calib_path, args.target_sec, args.session_id, args.out_dir,
                  calib_at_sec=args.calib_at, calib_port=args.calib_port)


if __name__ == "__main__":
    main()
