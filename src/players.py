"""Player position in court coordinates (TECH_SPEC §5.2, ADR-036).

Detection runs off-the-shelf in pixels; each player's position is taken at the
foot point (bottom-centre of the box) and projected into court coordinates
(feet) via the mount's calibration, so all downstream logic works in court
space regardless of camera pose."""

import json

import cv2
import numpy as np


def load_calibration(path):
    """Load a court calibration produced by calibrate.py. Returns the 3x3
    homography that maps image pixels to court coordinates (feet)."""
    with open(path) as f:
        data = json.load(f)
    return np.array(data["homography"], dtype=np.float64)


def foot_point(box):
    """Bottom-centre of a detection box (x1, y1, x2, y2) — the player's contact
    point with the court, which maps cleanly to the ground plane."""
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2.0, float(y2))


def to_court(image_points, homography):
    """Project image-pixel points to court coordinates (feet) through the
    homography. image_points: iterable of (x, y). Returns list of (x_ft, y_ft)."""
    pts = np.array(list(image_points), dtype=np.float64).reshape(-1, 1, 2)
    proj = cv2.perspectiveTransform(pts, homography).reshape(-1, 2)
    return [tuple(map(float, p)) for p in proj]


def frame_step(fps, sample_fps):
    """How many source frames to skip to sample at ~sample_fps (>= 1)."""
    return max(1, round(fps / sample_fps))


def detect_players(video_path, sample_fps=5.0, conf=0.3, imgsz=1280,
                   weights="yolov8n.pt"):
    """Detect people in a video with an off-the-shelf YOLO model, sampled at
    ~sample_fps. Returns a list of (time_sec, boxes), each box (x1, y1, x2, y2)
    in pixels. Only the COCO 'person' class (id 0) is kept.

    ultralytics/torch is imported lazily so the rest of this module stays
    dependency-light and unit-testable without it."""
    from ultralytics import YOLO

    model = YOLO(weights)
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = frame_step(fps, sample_fps)
    out, idx = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step == 0:
            t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            res = model(frame, imgsz=imgsz, conf=conf, classes=[0], verbose=False)[0]
            boxes = [tuple(map(float, b)) for b in res.boxes.xyxy.cpu().numpy()]
            out.append((t, boxes))
        idx += 1
    cap.release()
    return out
