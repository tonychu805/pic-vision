"""The contact sheet Jev judges a rally from (scripts/eval_jev_rally.py's sheet(), validated 2026-10-17, PIC-226):
6 frames evenly spaced over the rally, 2 wide x 3 high in time order, numbered 1-6. Keep the layout identical to
that sheet, because Jev's accuracy was measured on exactly this input.

Each frame is redacted before it leaves the pod (2026-11-15, EXPERIMENTS.md): everything outside the court's
footprint (4 ft past the sidelines, 10 ft past the baselines, plus players' standing height) is blurred, and so
are player heads (pose) and detected faces (YuNet). With this margin Jev's decisions on 123 judged clips were
unchanged; a tighter margin hid the area behind the baselines and cost real rallies."""
import os

import cv2
import numpy as np

TW, TH = 784, 441
MARGIN_SIDE_FT, MARGIN_END_FT, HEAD_FT = 4.0, 10.0, 7.5
YUNET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "face_detection_yunet_2023mar.onnx")
FPS = 30.0


def keep_polygon(calib, w, h):
    """Image polygon of the court footprint (with margins) and the players standing on it, for a w x h frame."""
    cw, ch = calib.get("calibration_resolution") or (w, h)
    inv = np.linalg.inv(np.array(calib["homography"]) @ np.diag([cw / w, ch / h, 1.0]))   # court ft -> frame px

    def px(x, y):
        p = inv @ [x, y, 1.0]
        return p[:2] / p[2]
    mx, my = MARGIN_SIDE_FT, MARGIN_END_FT
    xs, ys = np.arange(-mx, 20 + mx + 0.01, 0.5), np.arange(-my, 44 + my + 0.01, 0.5)
    pts = []
    for x, y in [(x, -my) for x in xs] + [(x, 44 + my) for x in xs] + [(-mx, y) for y in ys] + [(20 + mx, y) for y in ys]:
        foot = px(x, y)
        pts += [foot, foot - [0, HEAD_FT * np.linalg.norm(px(x + 1, y) - foot)]]   # height scaled like width at this depth
    return cv2.convexHull(np.array(pts, np.float32).reshape(-1, 1, 2)).astype(np.int32)


def _soften(img, factor):
    small = cv2.resize(img, (max(1, img.shape[1] // factor), max(1, img.shape[0] // factor)), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR)


def head_boxes(people, w, h):
    """Square boxes over each person's head: face keypoints when visible, else the top of the box."""
    out = []
    for p in people:
        x0, y0, x1, y1 = p["box"]
        bw, bh = x1 - x0, y1 - y0
        if bw <= 0 or bh <= 0:
            continue
        vis = [k for k in p["kp"][:5] if k[2] >= 0.35]
        cx, cy = (np.mean([k[0] for k in vis]), np.mean([k[1] for k in vis])) if vis else ((x0 + x1) / 2, y0 + 0.12 * bh)
        r = max(0.16 * bh, 0.5 * bw, 6)
        out.append((int(max(0, cx - r)), int(max(0, cy - r)), int(min(w, cx + r)), int(min(h, cy + r))))
    return out


def face_boxes(detections, w, h, margin=0.45):
    out = []
    for row in detections if detections is not None else []:
        x, y, bw, bh = map(float, row[:4])
        out.append((int(max(0, x - margin * bw)), int(max(0, y - margin * bh)),
                    int(min(w, x + (1 + margin) * bw)), int(min(h, y + (1 + margin) * bh))))
    return out


def redact(frame, polygon, people, faces):
    """The frame with everything outside `polygon` and every head/face box blurred."""
    h, w = frame.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(mask, [polygon], 255)
    out = np.where(mask[..., None] > 0, frame, _soften(frame, 24))
    for x0, y0, x1, y1 in head_boxes(people, w, h) + faces:
        if x1 > x0 and y1 > y0:
            out[y0:y1, x0:x1] = _soften(out[y0:y1, x0:x1], 8)
    return out


def contact_sheet(video_path, start_sec, end_sec, calib, poses=None, pose_model=None, face_detector=None):
    """JPEG bytes (1568 x 1323) of the rally between start_sec and end_sec, every frame redacted.

    poses: {str(frame): [person]} already computed for this video (the hit finder's, every 2nd frame); each sheet
    frame snaps to the nearest posed frame so the head boxes belong to the frame shown. Without poses for a frame,
    it is posed with pose_model when given. face_detector: a cv2.FaceDetectorYN (one per thread), made if not given."""
    yunet = face_detector or cv2.FaceDetectorYN.create(YUNET, "", (320, 320), 0.35, 0.3, 5000)
    posed = sorted(map(int, poses)) if poses else []
    cap = cv2.VideoCapture(video_path)
    try:
        canvas = np.zeros((3 * TH, 2 * TW, 3), np.uint8)
        polygon = None
        for i in range(6):
            f = round((start_sec + (i + 0.5) / 6 * (end_sec - start_sec)) * FPS)
            if posed:
                f = min(posed, key=lambda p: abs(p - f))
            cap.set(cv2.CAP_PROP_POS_MSEC, 1000 * f / FPS)
            ok, im = cap.read()
            if not ok:
                raise RuntimeError(f"could not decode frame {i + 1} of {video_path}")
            h, w = im.shape[:2]
            if polygon is None:
                polygon = keep_polygon(calib, w, h)
            if poses and str(f) in poses:
                people = poses[str(f)]
            elif pose_model is not None:
                people = [{"box": [float(v) for v in b], "kp": [[float(v) for v in k] for k in kp]} for b, kp in pose_model([im])[0]]
            else:
                people = []
            yunet.setInputSize((w, h))
            _, det = yunet.detect(im)
            tile = cv2.resize(redact(im, polygon, people, face_boxes(det, w, h)), (TW, TH))
            cv2.putText(tile, str(i + 1), (12, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
            canvas[(i // 2) * TH:(i // 2 + 1) * TH, (i % 2) * TW:(i % 2 + 1) * TW] = tile
    finally:
        cap.release()
    ok, buf = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return buf.tobytes()
