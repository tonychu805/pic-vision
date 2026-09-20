"""Standalone R2 upload/download helper, copied onto the RunPod pod and run
there. Kept as its own small script (rather than an inline `python3 -c`
one-liner) because nested shell/Python quoting across an SSH command is
fragile and hard to verify -- a real file with normal argparse is not.

Credentials are read from the environment, passed via SSH's command-line
env-var-prefix form (`KEY=value cmd`), never written to a file on the pod.

Usage (on the pod):
    python3 pod_r2_helper.py download BUCKET KEY LOCAL_PATH
    python3 pod_r2_helper.py upload   BUCKET KEY LOCAL_PATH
"""
import os
import sys

import boto3


def main():
    action, bucket, key, local_path = sys.argv[1:5]
    account_id = os.environ["CLOUDFLARE_R2_ACCOUNT_ID"]
    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["CLOUDFLARE_R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["CLOUDFLARE_R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    if action == "download":
        s3.download_file(bucket, key, local_path)
    elif action == "upload":
        s3.upload_file(local_path, bucket, key)
    else:
        raise SystemExit(f"unknown action: {action!r} (expected download/upload)")


if __name__ == "__main__":
    main()
