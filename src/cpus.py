"""How many CPUs a pod really has, and thread pools sized to it (2026-11-12).

Inside a container os.cpu_count() reports the HOST's cores: staging pods saw
48-96 while 5-7 were usable. OpenCV and torch size their thread pools from
the host count and thrash; sizing them to the usable count made ball-model
inference 2-5x faster (EXPERIMENTS 2026-11-12). Used by scripts/pod_infer.py
and cloud_pipeline/pod_driver.py (hit finder, badges).
"""
import os
import sys


def usable_cpus():
    """The affinity set, capped by a cgroup CPU quota (v2, then v1)."""
    n = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    try:
        quota, period = open("/sys/fs/cgroup/cpu.max").read().split()[:2]
        if quota != "max":
            n = min(n, max(1, int(quota) // int(period)))
    except (OSError, ValueError):
        try:
            quota = int(open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read())
            period = int(open("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read())
            if quota > 0:
                n = min(n, max(1, quota // period))
        except (OSError, ValueError):
            pass
    return n


def limit_threads(torch_threads=2):
    """OpenCV's threads = usable CPUs (PIC_VISION_INFER_THREADS overrides); torch's, if
    torch is loaded, at most torch_threads (the models run on the GPU). Returns what was set."""
    import cv2
    n = int(os.environ.get("PIC_VISION_INFER_THREADS") or usable_cpus())
    cv2.setNumThreads(n)
    info = {"host_cpus": os.cpu_count(), "usable_cpus": usable_cpus(), "cv2_threads": n}
    if "torch" in sys.modules:
        import torch
        torch.set_num_threads(min(torch_threads, n))
        info["torch_threads"] = torch.get_num_threads()
    return info
