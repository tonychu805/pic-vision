"""RunPod Serverless handler -- spike only, not wired into any real job yet.

Exists to answer one question before committing engineering to either this
path or ADR-093's self-driving-Pod path: does invoking this exact baked
image (cloud_pipeline/Dockerfile, tf215-cuda118, 17.7GB) through a
Serverless endpoint actually start faster than the raw-Pod route measured
2026-08-26 (79.6s cold, ~52.7s cached-but-only-tested-within-15-minutes)?
FlashBoot is RunPod's own caching mechanism for exactly this image-size
problem and was never tried against this image -- only Pod-level Docker
layer caching was.

Deliberately does real GPU/TF work rather than returning immediately: a
fast no-op would only prove the container booted, not that this image is
actually ready to run inference -- same standard the 08-26 pod timing test
held itself to ("verified TF actually loaded correctly too... rather than
trust a suspiciously fast number blindly").

Built into an image via Dockerfile.serverless, which layers this and the
`runpod` package on top of the existing baked image -- see that file for
why this doesn't touch cloud_pipeline/Dockerfile itself (that image is
also used, unmodified, by the raw-Pod path this is being compared against).
"""
import time

import runpod

_container_started_at = time.time()


def handler(job):
    import tensorflow as tf

    gpus = tf.config.list_physical_devices("GPU")
    return {
        "container_uptime_sec": round(time.time() - _container_started_at, 2),
        "tf_version": tf.__version__,
        "gpu_detected": bool(gpus),
        "gpu_devices": [g.name for g in gpus],
    }


runpod.serverless.start({"handler": handler})
