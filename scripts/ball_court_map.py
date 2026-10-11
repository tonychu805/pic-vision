"""Side-by-side clip: the real video on the left, a top-down 2D court on the
right with the ball's recent path traced on it (PIC-205, Court Moments
Stage 1).

The ball positions are the same gated TrackNet detections as
scripts/ball_trail_overlay.py (inside the court wedge, optional --min-conf),
joined only across adjacent frames and small jumps -- a gap breaks the trace,
nothing is interpolated.

IMPORTANT, read before trusting a position: this projects the ball's *image*
point onto the court FLOOR with the calibration homography. A ball in the air
is not on the floor, so its drawn position is displaced from where it truly is
(further away from the camera the higher it is). Treat the map as "where the
ball appears to be over the court", not a measured 3D position. Floor-contact
bounces are the only points that are geometrically exact.

Court frame (calib): x 0..20 ft left-right, y 0..44 ft with y=0 the NEAR
(camera-side) baseline, net at y=22, kitchen lines at y=15 and y=29. Drawn with
the near baseline at the bottom, like the camera sees it.

Usage:
    python3 scripts/ball_court_map.py --video videos/brickwall_30fps.mp4 \
        --csv cache/brickwall_30fps_predictions_k14.csv \
        --calib calib/brickwall_30fps_calib.json \
        --labels eval/labels/brickwall_30fps.jsonl --rally 24 \
        --out clips/brickwall_map_r24.mp4
"""
import argparse
import json
import subprocess
import sys

sys.path.insert(0, ".")

import numpy as np

from scripts.ball_trail_overlay import FPS, gated_points, resolve_window, trail_segments
from src.calib import court_wedge
from src.players import to_court
from src.tracknet import load_predictions

COURT_W, COURT_H, NET_Y = 20.0, 44.0, 22.0
KITCHEN = (15.0, 29.0)
MARGIN_FT = 6.0          # drawn run-off around the court; points beyond are dropped

BG = (28, 28, 28)
LINE = (210, 210, 210)
KITCHEN_FILL = (45, 60, 45)
TRAIL = (60, 220, 60)
HEAD = (255, 255, 255)


def court_to_px(x_ft, y_ft, scale, pad):
    """Court feet -> panel pixels, near baseline (y=0) at the bottom."""
    px = pad + (x_ft + MARGIN_FT) * scale
    py = pad + (COURT_H + MARGIN_FT - y_ft) * scale
    return px, py


def project_points(points, homography):
    """Per-frame image (x, y) or None -> court-feet (x, y) or None. Points
    that land further than MARGIN_FT outside the court are dropped (they are
    projection artefacts, not shots we can draw)."""
    idx = [i for i, p in enumerate(points) if p is not None]
    out = [None] * len(points)
    if not idx:
        return out
    proj = to_court([points[i] for i in idx], np.array(homography, dtype=np.float64))
    for i, (x, y) in zip(idx, proj):
        if -MARGIN_FT <= x <= COURT_W + MARGIN_FT and -MARGIN_FT <= y <= COURT_H + MARGIN_FT:
            out[i] = (x, y)
    return out


def draw_court(scale, pad, size):
    import cv2
    w, h = size
    img = np.full((h, w, 3), BG, dtype=np.uint8)

    def P(x, y):
        px, py = court_to_px(x, y, scale, pad)
        return int(round(px)), int(round(py))

    # kitchen zones (both sides of the net), then lines
    for y0, y1 in ((KITCHEN[0], NET_Y), (NET_Y, KITCHEN[1])):
        cv2.rectangle(img, P(0, y1), P(COURT_W, y0), KITCHEN_FILL, -1)
    cv2.rectangle(img, P(0, COURT_H), P(COURT_W, 0), LINE, 2)
    for y in KITCHEN:
        cv2.line(img, P(0, y), P(COURT_W, y), LINE, 1)
    cv2.line(img, P(0, NET_Y), P(COURT_W, NET_Y), (255, 0, 255), 3)   # net
    cv2.line(img, P(COURT_W / 2, 0), P(COURT_W / 2, KITCHEN[0]), LINE, 1)
    cv2.line(img, P(COURT_W / 2, KITCHEN[1]), P(COURT_W / 2, COURT_H), LINE, 1)
    cv2.putText(img, "NEAR (camera)", (pad, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, LINE, 1)
    cv2.putText(img, "FAR", (pad, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, LINE, 1)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--calib", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--labels")
    ap.add_argument("--rally", type=int)
    ap.add_argument("--start-sec", type=float)
    ap.add_argument("--end-sec", type=float)
    ap.add_argument("--pad-sec", type=float, default=1.0)
    ap.add_argument("--trail-sec", type=float, default=1.5)
    ap.add_argument("--min-conf", type=float, default=0.0)
    ap.add_argument("--max-jump", type=float, default=150.0, help="pixels, in the image")
    ap.add_argument("--max-gap-frames", type=int, default=1)
    args = ap.parse_args()

    import cv2

    start, end = resolve_window(args)
    with open(args.calib) as f:
        calib = json.load(f)
    track = load_predictions(args.csv, FPS)
    img_pts = gated_points(track, court_wedge(calib), args.min_conf)
    court_pts = project_points(img_pts, calib["homography"])
    # connectivity rules are decided in image space (where the jump limit is
    # meaningful); a segment is drawn only if both ends also project on-map.

    cap = cv2.VideoCapture(args.video)
    vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    pad = 12
    scale = (vh - 2 * pad) / (COURT_H + 2 * MARGIN_FT)
    pw = int((COURT_W + 2 * MARGIN_FT) * scale + 2 * pad)
    base = draw_court(scale, pad, (pw, vh))

    f0 = max(0, int((start - args.pad_sec) * FPS))
    f1 = min(len(img_pts) - 1, int((end + args.pad_sec) * FPS))
    trail_frames = max(1, int(args.trail_sec * FPS))
    index = {p: i for i, p in enumerate(img_pts) if p is not None}  # image pt -> frame

    tmp = args.out + ".raw.mp4"
    writer = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (vw + pw, vh))
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    shown = 0
    for i in range(f0, f1 + 1):
        ok, frame = cap.read()
        if not ok:
            break
        panel = base.copy()
        for p0, p1, age in trail_segments(img_pts, i, trail_frames,
                                           args.max_gap_frames, args.max_jump):
            c0, c1 = court_pts[index[p0]], court_pts[index[p1]]
            if c0 is None or c1 is None:
                continue
            fade = 1.0 - age / trail_frames
            color = tuple(int(c * (0.35 + 0.65 * fade)) for c in TRAIL)
            a = tuple(int(v) for v in court_to_px(*c0, scale, pad))
            b = tuple(int(v) for v in court_to_px(*c1, scale, pad))
            cv2.line(panel, a, b, color, max(1, int(1 + 3 * fade)))
        if court_pts[i] is not None:
            shown += 1
            cv2.circle(panel, tuple(int(v) for v in court_to_px(*court_pts[i], scale, pad)),
                       5, HEAD, 1)
        cv2.putText(frame, f"{int(i / FPS // 60)}:{i / FPS % 60:04.1f}", (16, vh - 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        writer.write(np.hstack([frame, panel]))
    writer.release()
    cap.release()

    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", tmp, "-c:v", "libx264",
                    "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", "-an", args.out], check=True)
    subprocess.run(["rm", "-f", tmp], check=True)
    total = f1 - f0 + 1
    print(f"wrote {args.out}: {f0 / FPS:.1f}s-{f1 / FPS:.1f}s, "
          f"ball on map for {shown}/{total} frames ({100 * shown / total:.0f}%)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
