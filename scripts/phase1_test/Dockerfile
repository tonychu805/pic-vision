# Phase-1 pose endpoint image (RunPod serverless). Mirrors the versions validated locally (ultralytics 8.4.120).
# Build + push, then point a NEW RunPod serverless endpoint at it (NOT the TrackNet endpoint).
#
#   docker build -t <registry>/pic-pose:phase1 scripts/phase1_test
#   docker push  <registry>/pic-pose:phase1
#
# Adjust the base tag to a RunPod PyTorch image that exists for your account/region if this one 404s.
FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "ultralytics==8.4.120" "runpod>=1.6"

# Bake the pose weights into the image so cold start does NOT include a download.
RUN python -c "from ultralytics import YOLO; YOLO('yolov8x-pose.pt')" && \
    cp /root/.config/Ultralytics/../*/yolov8x-pose.pt /yolov8x-pose.pt 2>/dev/null || \
    python -c "from ultralytics import YOLO; m=YOLO('yolov8x-pose.pt'); import shutil; shutil.copy(m.ckpt_path,'/yolov8x-pose.pt')"

WORKDIR /
COPY pose_handler.py /pose_handler.py
# handler loads 'yolov8x-pose.pt' from the working dir; keep it next to the handler.
CMD ["python", "-u", "/pose_handler.py"]
