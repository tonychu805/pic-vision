#!/usr/bin/env python3
"""Uploads one local file to R2 and prints back its public CDN URL --
built for desktop/electron/calibration.js's console-driven calibration
flow (DECISIONS.md ADR-080), which needs to hand a snapshot image (and
later, a finished calib.json backup) to the cloud console without
reimplementing an R2 client in JS (ADR-071's "invoke the existing Python
as a subprocess" convention, same as save_calibration.py's homography
fit). Deliberately thin -- r2_storage.py's upload_file was already
generic enough, nothing camera- or calibration-specific belongs here.

Usage:
    python3 upload_calibration_snapshot.py --local-path snapshot.jpg \\
        --key calibration-snapshots/<uuid>.jpg
"""
import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(REPO_ROOT, ".env"))

from cloud_pipeline import r2_storage

# Same bucket reels already upload to (run_cloud_job.py's BUCKET) -- no new
# bucket needed, just a different key prefix.
BUCKET = os.environ.get("CLOUD_PIPELINE_BUCKET", "test-ingest-runpod")
CDN_DOMAIN = "cdn.picvisionai.com"


def fail(msg):
    print(json.dumps({"error": msg}))
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-path", required=True)
    ap.add_argument("--key", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.local_path):
        fail(f"no such file: {args.local_path}")

    try:
        r2_storage.upload_file(BUCKET, args.local_path, args.key)
    except Exception as e:
        fail(str(e))

    print(json.dumps({"url": f"https://{CDN_DOMAIN}/{args.key}"}))


if __name__ == "__main__":
    main()
