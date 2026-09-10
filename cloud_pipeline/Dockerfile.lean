# Lean rebuild of cloud_pipeline/Dockerfile (17.7GB), built after `docker
# history` on the real image showed ~10.2GB of it was dead weight this
# pipeline never uses:
#   - 4.72GB: the CUDA 11.8 *devel* toolkit (nvcc, nsight-compute, nvprof)
#     -- needed to compile CUDA code, not to run pre-built TF wheels.
#   - 4.65GB: PyTorch + torchvision + torchaudio -- this pipeline is 100%
#     TensorFlow; PyTorch was pure inheritance from the `runpod/pytorch`
#     base image.
#   - ~850MB: SSH daemon + nginx + JupyterLab/notebook extensions -- only
#     present because `runpod/pytorch` bundles them for the interactive-Pod
#     use case (runpod_pod.py's own comment explains that's the ONLY reason
#     that base was chosen). Nothing here needs SSH, nginx, or Jupyter.
#
# The official TensorFlow GPU image already ships a CUDA *runtime* (not
# devel) matched to the TF build inside it, so this doesn't need the
# `[and-cuda]` pip extra's own bundled CUDA wheels on top -- that was only
# there because the old base had no compatible CUDA runtime for pip TF to
# use. Same TF version (2.15.0 vs. the pinned 2.15.1 patch -- verified this
# tag exists on Docker Hub 2026-09-10) as the last Keras-2 release this
# project's SavedModel weights need (EXPERIMENTS.md 2026-08-16).
#
# No SSH daemon here -- this image is meant to be tested standalone
# (RunPod Serverless, or a self-driving Pod that never needs SSH in) rather
# than under runpod_pod.py's SSH-driven orchestration. If it's ever run as
# a raw Pod under that path, sshd + the PUBLIC_KEY startup script need
# adding back explicitly (a few lines, tens of MB -- not the multi-GB cost
# it was riding along with before).
FROM tensorflow/tensorflow:2.15.0-gpu

# numpy pinned explicitly: the base image ships numpy==1.26.2 (checked
# 2026-09-10), matched to TF 2.15's build. Without this pin, installing
# opencv-python-headless here silently upgrades to numpy 2.x (whichever it
# resolves as latest-compatible) and TF fails on import with "_ARRAY_API
# not found" -- a real bug hit while verifying this image, not a
# hypothetical: TF 2.15 was built against NumPy 1.x's C ABI.
RUN pip install --no-cache-dir boto3 opencv-python-headless 'numpy==1.26.2'
