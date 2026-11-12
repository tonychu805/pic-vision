#!/bin/bash
# Builds the Google Compute Engine image the orchestrator's Google fallback
# boots its spot L4 machines from (image family pic-vision-pod, 2026-11-13).
#
# Google's PyTorch image plus what the pod's start command would otherwise
# install on every boot (boto3, requests, OpenCV), so a machine is ready in
# ~90 s instead of ~2-3 min (EXPERIMENTS.md 2026-11-13). Rebuild when the pod
# start command's packages change (cloud_pipeline/runpod_pod.py _BOOTSTRAP_CMD).
#
# The orchestrator runs that start command from the startup-script as root
# with a startup-script PATH, so the check below runs the same way: the
# python3 it finds there must have torch with CUDA, cv2 and boto3.
#
# Usage: scripts/build_gce_pod_image.sh [project] [zone]
set -euo pipefail
PROJECT=${1:-pic-vision-gpu-test}
ZONE=${2:-asia-east1-a}
GCLOUD=${GCLOUD:-gcloud}
VM=pod-image-build-$(date +%s)
IMAGE=pic-vision-pod-$(date -u +%Y%m%d-%H%M)

cleanup() { "$GCLOUD" compute instances delete "$VM" --project="$PROJECT" --zone="$ZONE" --quiet >/dev/null 2>&1 || true; }
trap cleanup EXIT

"$GCLOUD" compute instances create "$VM" --project="$PROJECT" --zone="$ZONE" \
  --machine-type=g2-standard-8 --provisioning-model=SPOT --instance-termination-action=DELETE --max-run-duration=1h \
  --image-project=deeplearning-platform-release --image-family=pytorch-2-9-cu129-ubuntu-2204-nvidia-580 \
  --boot-disk-size=100GB --boot-disk-type=pd-balanced >/dev/null

for _ in $(seq 1 40); do
  "$GCLOUD" compute ssh "$VM" --project="$PROJECT" --zone="$ZONE" --quiet --command=true 2>/dev/null && break
  sleep 5
done

"$GCLOUD" compute ssh "$VM" --project="$PROJECT" --zone="$ZONE" --quiet --command='sudo env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin bash -c "
  set -e
  python3 -m pip install -q --no-cache-dir boto3==1.35.99 requests==2.32.3
  python3 -m pip install -q --no-cache-dir --no-deps opencv-python-headless==4.10.0.84
  python3 -c \"import torch, cv2, boto3, requests; assert torch.cuda.is_available(); print(\\\"pod python ok:\\\", torch.__version__, cv2.__version__)\"
"'

"$GCLOUD" compute instances stop "$VM" --project="$PROJECT" --zone="$ZONE" --quiet >/dev/null
"$GCLOUD" compute images create "$IMAGE" --project="$PROJECT" --family=pic-vision-pod \
  --source-disk="$VM" --source-disk-zone="$ZONE" >/dev/null
echo "built $IMAGE (family pic-vision-pod)"
