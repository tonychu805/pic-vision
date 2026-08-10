"""v1 rally signal: ball net-crossing counter (ADR-039, ADR-028).

The ball flies above the ground plane, so the court homography mis-locates it
(parallax). Instead we work in image space: in a behind-baseline view the ball's
vertical pixel position (image-y) tells us which side of the net it's on — near
= bottom (large y), far = top (small y). A net-crossing is the ball's image-y
crossing the net line, with a hysteresis band so jitter near the net doesn't
inflate the count. Missing/ambiguous frames are skipped.

Ball detection (YOLO 'sports ball' + false-positive filters) and the net line
from calibration are separate slices; this is the testable core."""

import cv2
import numpy as np


def net_image_y(homography, x_ft=10.0, net_y_ft=22.0):
    """Image-y (pixels) of the net line, from the image->court homography
    (calibrate.py output). Projects a court point on the net back into image
    space — the reference line the ball crosses."""
    h_inv = np.linalg.inv(np.array(homography, dtype=np.float64))
    pt = cv2.perspectiveTransform(
        np.array([[[x_ft, net_y_ft]]], dtype=np.float32), h_inv)
    return float(pt[0, 0, 1])


def ball_box_ok(box, max_dim_px, max_aspect=2.0):
    """True if a detection box is ball-shaped: not larger than max_dim_px on its
    long side (drops heads/bodies) and roughly square (drops elongated limbs).
    box = (x1, y1, x2, y2). max_dim_px must be calibrated to the ball's pixel
    size on the actual footage — see detect_ball's max_ball_px."""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    long, short = max(w, h), max(min(w, h), 1)
    return long <= max_dim_px and long / short <= max_aspect


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
        cands = []
        for j in range(len(xyxy)):
            if max_ball_px is not None and not ball_box_ok(xyxy[j], max_ball_px):
                continue
            x1, y1, x2, y2 = xyxy[j]
            cands.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0, float(confs[j])))
        out.append((t, cands))
    cap.release()
    return out


def net_line_y(calib):
    """Net line image-y from a calibration dict. Prefers a hand-marked net
    (calib['net_image_points'], from calibrate.py) — the reliable source when
    the camera is fixed — and falls back to projecting it through the homography
    when no net was marked. Marking removes the derived-line error we hit on
    zoomed footage (EXPERIMENTS.md 2026-08-10)."""
    pts = calib.get("net_image_points")
    if pts:
        return sum(p[1] for p in pts) / len(pts)
    return net_image_y(calib["homography"])


def detect_ball(video_path, start=0.0, end=None, conf=0.10, imgsz=1280,
                weights="yolov8x.pt", sample_fps=None, max_ball_px=None):
    """Best 'sports ball' image-y per sampled frame between start and end (sec).
    Returns [(time_sec, y or None)]. sample_fps=None runs every frame (dense,
    for exact crossing counts); set it lower (e.g. 10) to scan a whole clip
    affordably. Default weights are yolov8x — the large model detects the real
    ball at high confidence and pushes false positives to low confidence
    (evidence: EXPERIMENTS.md 2026-08-10). max_ball_px, when set, drops boxes
    too big/elongated to be a ball (heads, bodies); leave None until it's
    calibrated to the ball's pixel size on clean footage. Takes the
    highest-confidence surviving detection per frame."""
    from ultralytics import YOLO

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
            continue  # skip YOLO on non-sampled frames (decode is cheap, YOLO isn't)
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


def crossing_times(track, net_y, band=0.0):
    """Timestamps where the ball crosses the net. track = [(time, y or None)].
    Same side logic as count_crossings, but returns the times so bursts can be
    located and clustered into rallies."""
    times = []
    last_side = None
    for t, y in track:
        if y is None:
            continue
        if y > net_y + band:
            side = "near"
        elif y < net_y - band:
            side = "far"
        else:
            continue
        if last_side is not None and side != last_side:
            times.append(t)
        last_side = side
    return times


def cluster_crossings(times, gap_sec, min_crossings=2):
    """Group dense bursts of crossing times into rally segments. Consecutive
    crossings within gap_sec belong to the same rally; a burst is kept only if
    it has >= min_crossings (an exchange, not a stray). Returns
    [{start, end, crossings}] — the auto-annotated rallies."""
    if not times:
        return []
    clusters = [[times[0]]]
    for t in times[1:]:
        if t - clusters[-1][-1] <= gap_sec:
            clusters[-1].append(t)
        else:
            clusters.append([t])
    return [{"start": c[0], "end": c[-1], "crossings": len(c)}
            for c in clusters if len(c) >= min_crossings]


def count_crossings(ball_ys, net_y, band=0.0):
    """Count net-crossings from a ball's per-frame image-y positions.

    ball_ys: list of image-y (pixels) or None where the ball wasn't detected.
    A frame's side is 'near' if y > net_y + band, 'far' if y < net_y - band, and
    ambiguous (skipped) within the band. A crossing is counted each time the
    definite side flips."""
    crossings = 0
    last_side = None
    for y in ball_ys:
        if y is None:
            continue
        if y > net_y + band:
            side = "near"
        elif y < net_y - band:
            side = "far"
        else:
            continue  # inside the band: too close to the net to call a side
        if last_side is not None and side != last_side:
            crossings += 1
        last_side = side
    return crossings
