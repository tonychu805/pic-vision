"""Archived YOLO ball detection — retired 2026-08-12 (ADR-046).

detect_ball and detect_candidates: YOLO 'sports ball' detector.
Replaced by TrackNet inference on RunPod GPU (src/tracknet.py + scripts/pod_infer.py).
TrackNet finds 5× more net-crossings on the same footage (EXPERIMENTS.md 2026-08-12).
"""

import cv2
import numpy as np
from tqdm import tqdm


def detect_candidates(video_path, start=0.0, end=None, conf=0.10, imgsz=1280,
                      weights="yolov8x.pt", sample_fps=None, max_ball_px=None):
    """Like detect_ball but keeps ALL surviving 'sports ball' candidates per
    frame as (x_center, y_center, conf) — the input the tracker needs to choose
    the in-play ball by continuity instead of by confidence. Returns
    [(time_sec, [(x, y, conf), ...])]."""
    from ultralytics import YOLO

    model = YOLO(weights)
    cap = cv2.VideoCapture(video_path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    stride = 1 if not sample_fps else max(1, round(src_fps / sample_fps))
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    total_sampled = total_frames // stride
    out = []
    i = -1
    with tqdm(total=total_sampled, unit="frame", desc="detecting") as bar:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            i += 1
            t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if end is not None and t > end:
                break
            if i % stride:
                continue
            from src.ball import ball_box_ok
            b = model(frame, imgsz=imgsz, conf=conf, classes=[32], verbose=False)[0].boxes
            confs = b.conf.cpu().numpy()
            xyxy = b.xyxy.cpu().numpy()
            cands = []
            for j in range(len(xyxy)):
                if max_ball_px is not None and not ball_box_ok(xyxy[j], max_ball_px):
                    continue
                x1, y1, x2, y2 = xyxy[j]
                cands.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0, float(confs[j])))
            out.append((t, cands))
            bar.update(1)
    cap.release()
    return out


def detect_ball(video_path, start=0.0, end=None, conf=0.10, imgsz=1280,
                weights="yolov8x.pt", sample_fps=None, max_ball_px=None):
    """Best 'sports ball' image-y per sampled frame between start and end (sec).
    Returns [(time_sec, y or None)]."""
    from ultralytics import YOLO
    from src.ball import ball_box_ok

    model = YOLO(weights)
    cap = cv2.VideoCapture(video_path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    stride = 1 if not sample_fps else max(1, round(src_fps / sample_fps))
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    out = []
    i = -1
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        i += 1
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if end is not None and t > end:
            break
        if i % stride:
            continue
        b = model(frame, imgsz=imgsz, conf=conf, classes=[32], verbose=False)[0].boxes
        confs = b.conf.cpu().numpy()
        xyxy = b.xyxy.cpu().numpy()
        idx = [j for j in range(len(xyxy))
               if max_ball_px is None or ball_box_ok(xyxy[j], max_ball_px)]
        if idx:
            best = max(idx, key=lambda j: confs[j])
            x1, y1, x2, y2 = xyxy[best]
            out.append((t, float((y1 + y2) / 2.0)))
        else:
            out.append((t, None))
    cap.release()
    return out
