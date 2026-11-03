"""Pose inference handler for the Phase-1 serve-gate test — runs ON a RunPod serverless worker (or pod).

ISOLATION: this is a NEW endpoint, separate from the TrackNet production endpoint. It touches no production
surface — it only reads a video (given a path on the pod or a presigned R2 URL) and returns per-window player
depths + timing. It writes nothing back, delivers nothing.

Like scripts/pod_infer.py, this is standalone: it imports nothing from src/ (homography projection inlined) so it
can be baked into a minimal image. The production TrackNet endpoint is untouched.

INPUT (event["input"] for serverless; --input JSON for CLI):
  { "video_url": "<presigned R2 url>"  OR  "video_path": "/workspace/game.mp4",
    "homography": [[...],[...],[...]],        # calib['homography'], image->court
    "windows":   [[lo,hi], ...],              # frame ranges to pose (serve windows for the gate)
    "imgsz": 960, "net": 22.0, "conf": 0.25 }
OUTPUT:
  { "results": [{"window":[lo,hi], "depth": <max |court_y-net| over players/frames>, "frames": <n>}, ...],
    "timing": {"model_load_s":_, "download_s":_, "decode_s":_, "infer_s":_, "total_s":_},
    "cold": <true on this worker's first call>, "device": "cuda"|"cpu" }

The serve gate's keep/drop (depth >= 18 ft) is applied by the CALLER from `depth`, so this handler stays a pure
measurement surface. Cold start is measured CLIENT-side (first runsync latency); `cold` just flags the first call.

Deploy (operator): image with `pip install ultralytics runpod`, weights yolov8x-pose.pt baked in, GPU constrained
to the $0.50 cap (same as TrackNet) so throughput reflects production. Entry: `python -u pose_handler.py` (serverless).
CLI self-test on a pod:  python pose_handler.py --input req.json
"""
import os, sys, json, time, urllib.request

_t0 = time.time()
import numpy as np
import cv2
from ultralytics import YOLO

_MODEL = YOLO("yolov8x-pose.pt")
try:
    import torch
    _DEV = 0 if torch.cuda.is_available() else "cpu"
except Exception:
    _DEV = 0
_MODEL_LOAD_S = time.time() - _t0   # import + weights load (part of cold start)
_FIRST = {"v": True}


def _project(H, x, y):
    v = np.array(H, float) @ np.array([x, y, 1.0])
    return v[0] / v[2], v[1] / v[2]


def _fetch(video_url, dest="/tmp/_pose_in.mp4"):
    t = time.time()
    urllib.request.urlretrieve(video_url, dest)
    return dest, time.time() - t


def run(inp):
    cold = _FIRST["v"]; _FIRST["v"] = False
    H = inp["homography"]; imgsz = int(inp.get("imgsz", 960))
    net = float(inp.get("net", 22.0)); conf = float(inp.get("conf", 0.25))
    dl = 0.0
    if inp.get("video_url"):
        path, dl = _fetch(inp["video_url"])
    else:
        path = inp["video_path"]
    cap = cv2.VideoCapture(path)
    results = []; dec = 0.0; inf = 0.0
    for lo, hi in inp["windows"]:
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(lo)))
        best = 0.0; n = 0
        for _ in range(max(0, int(lo)), int(hi) + 1):
            td = time.time(); ok, im = cap.read(); dec += time.time() - td
            if not ok:
                break
            n += 1
            ti = time.time()
            r = _MODEL.predict(im, imgsz=imgsz, classes=[0], device=_DEV, verbose=False)[0]
            inf += time.time() - ti
            for b in r.boxes.xyxy.cpu().numpy():
                cx, cy = _project(H, (b[0] + b[2]) / 2, b[3])
                if -2 <= cx <= 22 and -6 <= cy <= 50:
                    best = max(best, abs(cy - net))
        results.append({"window": [int(lo), int(hi)], "depth": round(float(best), 2), "frames": n})
    cap.release()
    return {"results": results, "cold": cold, "device": str(_DEV),
            "timing": {"model_load_s": round(_MODEL_LOAD_S, 2) if cold else 0.0,
                       "download_s": round(dl, 2), "decode_s": round(dec, 2),
                       "infer_s": round(inf, 2), "total_s": round(dl + dec + inf, 2)}}


def handler(event):          # RunPod serverless entrypoint
    return run(event["input"])


if __name__ == "__main__":
    if "--input" in sys.argv:                      # CLI self-test on a pod
        inp = json.load(open(sys.argv[sys.argv.index("--input") + 1]))
        print(json.dumps(run(inp), indent=2))
    else:                                           # serverless
        import runpod
        runpod.serverless.start({"handler": handler})
