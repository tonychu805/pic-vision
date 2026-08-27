"""Single, shared implementation of "append one timestamped line to a job's
log.txt" -- used by both the dashboard route (webapp/pipeline.py) and the
cloud pipeline's standalone CLI (cloud_pipeline/run_cloud_job.py's main())
so a log.txt line looks identical no matter which path produced it."""
import os
import time


def append(job_dir, msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg.rstrip(chr(10))}"
    with open(os.path.join(job_dir, "log.txt"), "a") as f:
        f.write(line + "\n")
