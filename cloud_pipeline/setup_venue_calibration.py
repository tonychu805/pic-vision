"""One-time, per-venue calibration setup — NOT part of the per-session job
pipeline (cloud_pipeline/run_cloud_job.py).

Corrected 2026-08-26: an earlier version of run_cloud_job.py auto-launched
calibrate_web.py per job, which conflated a once-per-venue setup step with
the per-session job lifecycle. Calibration only changes when the camera
physically moves (ADR-049) — the same way this project's own committed
calib/*.json files are each produced once and reused across every session
scored on that camera since. Run this once when a camera is first mounted
at a venue; the calib.json it produces gets reused for every future session
there. run_cloud_job.py just consumes an existing calib.json — it has no
calibration logic of its own anymore.

Usage:
    python3 -m cloud_pipeline.setup_venue_calibration \
        --video first-session.mp4 --out venues/my-venue/calib.json
"""
import argparse
import os
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALIBRATE_WEB_SCRIPT = os.path.join(REPO_ROOT, "calibrate_web.py")


def run_calibration(video_path, out_path, at_sec=60.0, port=8765, poll_sec=2.0):
    """Launches calibrate_web.py (the existing standalone browser-click tool,
    unmodified) and waits for the operator to save a calibration, instead of
    requiring a separate manual Ctrl+C once they're done. calibrate_web.py
    blocks forever by design (server.serve_forever()) with no clean exit
    signal, so this polls for the output file to appear instead of waiting
    on the process to exit."""
    if os.path.exists(out_path):
        raise SystemExit(
            f"{out_path} already exists -- this is a one-time-per-venue step, "
            f"not something to redo per session. Delete it first if you "
            f"really need to re-calibrate (e.g. the camera physically moved).")

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    print(f"launching calibrate_web.py against {video_path}...")
    proc = subprocess.Popen(
        [sys.executable, CALIBRATE_WEB_SCRIPT, video_path,
         "--at", str(at_sec), "--out", out_path, "--port", str(port)])
    print(f"open http://<this-machine>:{port}/ in a browser, click the 12 "
          f"court points + 2 net-tape points, then Save")
    print("waiting for calibration to be saved...")
    try:
        while not os.path.exists(out_path):
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
    print(f"calibration saved to {out_path}")
    print("reuse this exact path for every future session at this venue -- "
          "pass it to run_cloud_job.py's --calib. Don't regenerate it per job.")


def main():
    p = argparse.ArgumentParser(
        description="One-time per-venue calibration setup (not part of the per-session job pipeline)")
    p.add_argument("--video", required=True, help="any representative recording from this venue's camera")
    p.add_argument("--out", required=True,
                    help="where to save calib.json -- reuse this exact path for every future session at this venue")
    p.add_argument("--at", type=float, default=60.0,
                    help="seconds into the video to grab the calibration frame from")
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()
    run_calibration(args.video, args.out, at_sec=args.at, port=args.port)


if __name__ == "__main__":
    main()
