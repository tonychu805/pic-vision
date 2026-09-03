"""Desktop-agent entry point for a cloud pipeline run (PIC-68) -- invoked
as a subprocess by desktop/electron/pipeline.js, one job per process.

Reuses webapp/pipeline.py's run_cloud_job(job_dir)/cancel_job(job_dir)
wholesale -- same status.json/log.txt contract the Flask dashboard already
polls -- rather than reimplementing job tracking here, per ADR-071's
"local agent invokes the existing Python, don't reimplement" directive.
The only new part is running that function on a background thread so a
SIGINT/SIGTERM from the Electron parent (its own "always SIGINT, never a
hard kill" convention -- capture.js, ADR-031) can call cancel_job() from
an ordinary signal handler and have it actually terminate a RunPod pod
that's already been created, not just kill this process and orphan a
billed pod nobody's tracking anymore. Threading it lets the signal
handler call cancel_job() from what is effectively still normal code (the
main thread, blocked in worker.join()) instead of from inside the
job itself -- the same concurrency shape webapp/app.py already relies on
when a Flask request thread calls cancel_job() while run_cloud_job() runs
on its own background thread.

CLI mirrors cloud_pipeline/run_cloud_job.py's own --video/--calib/
--target-sec/--session-id/--out-dir, plus writing job.json first so
webapp.pipeline.run_cloud_job(job_dir) -- built for the Flask dashboard's
job_dir/job.json convention -- can be called unmodified. video_file is
written as an absolute path: os.path.join(job_dir, job["video_file"])
in webapp/pipeline.py discards job_dir entirely when the second argument
is already absolute, so this works regardless of where job_dir lives.
"""
import argparse
import json
import os
import signal
import sys
import threading

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


def main():
    p = argparse.ArgumentParser(description="Run one cloud-pipeline job for the desktop agent")
    p.add_argument("--video", required=True)
    p.add_argument("--calib", required=True)
    p.add_argument("--target-sec", type=float, default=300.0)
    p.add_argument("--session-id", required=True)
    p.add_argument("--out-dir", required=True)
    args = p.parse_args()

    job_dir = args.out_dir
    os.makedirs(job_dir, exist_ok=True)
    with open(os.path.join(job_dir, "job.json"), "w") as f:
        json.dump({
            "video_file": os.path.abspath(args.video),
            "calib_path": os.path.abspath(args.calib),
            "target_sec": args.target_sec,
            "session_id": args.session_id,
        }, f)

    from webapp.pipeline import cancel_job, run_cloud_job

    worker = threading.Thread(target=run_cloud_job, args=(job_dir,), daemon=True)
    worker.start()

    def handle_signal(signum, frame):
        cancel_job(job_dir)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    worker.join()

    with open(os.path.join(job_dir, "status.json")) as f:
        status = json.load(f)
    sys.exit(1 if status.get("stage") in ("error", "cancelled") else 0)


if __name__ == "__main__":
    main()
