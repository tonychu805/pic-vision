"""Thin Cloudflare R2 client (S3-compatible API), reached directly via boto3.

Not a RunPod integration -- there isn't one (DECISIONS.md ADR-043 update,
2026-08-26). R2 is reached the same way any external S3-compatible service
would be, from wherever this code runs (local machine or a RunPod pod): a
standard S3 client, R2's own endpoint and credentials, region_name="auto".

Credentials come from the environment (.env, gitignored):
    CLOUDFLARE_R2_ACCESS_KEY_ID
    CLOUDFLARE_R2_SECRET_ACCESS_KEY
    CLOUDFLARE_R2_ACCOUNT_ID
"""
import os

import boto3


def _client():
    account_id = os.environ["CLOUDFLARE_R2_ACCOUNT_ID"]
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["CLOUDFLARE_R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["CLOUDFLARE_R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def upload_file(bucket, local_path, key):
    _client().upload_file(local_path, bucket, key)


def download_file(bucket, key, local_path):
    _client().download_file(bucket, key, local_path)


def object_exists(bucket, key):
    try:
        _client().head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False
