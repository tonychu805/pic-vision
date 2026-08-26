# Pre-baked RunPod pod image -- avoids the ~66.5s `pip install
# tensorflow[and-cuda]==2.15.1` tax that run_cloud_job.py pays on every job
# by installing it once here instead (DECISIONS.md ADR-043 final update,
# cloud_pipeline/README.md Status section). Same base image and same exact
# package set as POD_SETUP_CMD in run_cloud_job.py -- if that command
# changes, this file needs the matching change, and vice versa.
#
# Build once, push to a registry, then point runpod_pod.py's DEFAULT_IMAGE
# at it. Pods stay per-job (no session/day-lifetime reuse) -- this only
# removes the redundant install, it doesn't change the isolation model.
FROM runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04

RUN pip install --no-cache-dir boto3 opencv-python-headless 'tensorflow[and-cuda]==2.15.1'
