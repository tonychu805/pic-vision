"""Prototype: a vertical (9:16) rally clip whose frame pans to keep the ball in view.

Operator request 2026-09-28: the shipped 16:9 clips aren't phone-friendly, and
a fixed centre 9:16 crop loses the play. Instagram-style highlights instead
pan a tall window across the wide shot, following the action. This tests that
on a real rally, using the ball positions detection already produces.

How the window moves:
  1. The tracked ball x per frame (src/track.py, return_x=True: the same
     teleport-rejected track rally detection uses, not raw detections).
  2. Gaps (ball not seen) are filled by joining the nearest seen positions
     with a straight line; before the first / after the last sighting it holds.
  3. That path is smoothed with a centred Gaussian (sigma --smooth-sec), so
     the window glides instead of chasing every bounce. Offline, so it can
     look ahead: the window starts moving before a long cross-court shot.
  4. The pan speed is capped (--max-pan, frame widths per second) and the
     window is kept inside the frame.

Writes <out>.mp4 (1080x1920 vertical) and <out>_debug.mp4 (the wide shot with
the window drawn on it, and the raw ball position), to judge the motion.

Usage:
  python3 scripts/follow_crop_prototype.py --video V --csv C --calib J --rank 1 --out clips/follow_r1
"""
import argparse
import json
import math
import subprocess
import sys

import cv2
import numpy as np

sys.path.insert(0, ".")

from src.calib import court_wedge
from src.rallies import detect_candidates
from src.render import probe_fps
from src.select import rank_segments
from src.track import max_jump_for_fps, reset_after_for_fps, track_ball
from src.tracknet import load_predictions


def ball_xs(csv, calib, fps):
    """Tracked ball x per frame (None when not seen), in video pixels."""
    in_court = court_wedge(calib)
    track = load_predictions(csv, fps)
    frames = [[(x, y, c if c is not None else 1.0)] if in_court(x, y) else [] for _, x, y, w, h, c in track]
    _, xs = track_ball(frames, max_jump=max_jump_for_fps(fps), reset_after=reset_after_for_fps(fps), return_x=True)
    return xs


def window_path(xs, fps, width, crop_w, smooth_sec, max_pan):
    """Left edge of the crop window per frame."""
    n = len(xs)
    seen = [i for i, x in enumerate(xs) if x is not None]
    centre = np.full(n, width / 2.0)
    if seen:
        centre = np.interp(np.arange(n), seen, [xs[i] for i in seen])  # holds at both ends
    sigma = max(1.0, smooth_sec * fps)
    k = np.arange(-int(3 * sigma), int(3 * sigma) + 1)
    kernel = np.exp(-0.5 * (k / sigma) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(centre, len(k) // 2, mode="edge")
    smooth = np.convolve(padded, kernel, mode="valid")
    step = max_pan * width / fps  # max px per frame
    out = [smooth[0]]
    for c in smooth[1:]:
        out.append(out[-1] + max(-step, min(step, c - out[-1])))
    return [int(round(min(max(c - crop_w / 2, 0), width - crop_w))) for c in out]


# The venue logo on a vertical clip: the same rounded badge as the 16:9 reels
# (src/render.py logo_filter), about the same size on screen (14% of the
# vertical frame's width, 152 px at 1080), close in to the lower-right corner
# (operator, 2026-09-28). A full-screen player on a phone taller than 9:16
# must crop from the LEFT (object-position: right) to keep it in view.
V_LOGO_WIDTH_FRAC = 0.14
V_LOGO_INSET_X_FRAC = 0.025
V_LOGO_INSET_Y_FRAC = 0.025


def vertical_logo_filter(w, h):
    lw = max(2, round(w * V_LOGO_WIDTH_FRAC / 2) * 2)
    r = round(lw * 0.12)
    mx, my = round(w * V_LOGO_INSET_X_FRAC), round(h * V_LOGO_INSET_Y_FRAC)
    corner = (f"hypot(max(0,{r}-min(X+0.5,W-X-0.5)),"
              f"max(0,{r}-min(Y+0.5,H-Y-0.5)))")
    return (f"[1]crop=iw-2:ih-2:1:1,scale={lw}:-2:flags=lanczos,format=rgba,"
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='255*clip({r}+0.5-{corner},0,1)'[logo];"
            f"[0][logo]overlay=W-w-{mx}:H-h-{my}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--calib", required=True)
    ap.add_argument("--rank", type=int, default=1, help="which rally, by the shipped ranking (1 = best)")
    ap.add_argument("--start", type=float, help="render this exact range instead (seconds into the video)")
    ap.add_argument("--end", type=float)
    ap.add_argument("--pad-sec", type=float, default=1.0)
    ap.add_argument("--smooth-sec", type=float, default=0.5)
    ap.add_argument("--max-pan", type=float, default=0.6, help="frame widths per second")
    ap.add_argument("--out", required=True)
    ap.add_argument("--logo", help="venue logo image, burnt into the vertical clip's lower right")
    a = ap.parse_args()

    calib = json.load(open(a.calib))
    fps = probe_fps(a.video)
    if a.start is not None and a.end is not None:
        seg = {"start": a.start, "end": a.end, "score": float("nan")}
        a.pad_sec = 0.0
    else:
        cand = detect_candidates(a.video, a.csv, a.calib)
        ranked = rank_segments(cand["segments"], cand["times_crossed"], cand["speeds"], cand["threshold"])
        seg = ranked[a.rank - 1]

    cap = cv2.VideoCapture(a.video)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    f0 = max(0, int((seg["start"] - a.pad_sec) * fps))
    f1 = min(n_total, int((seg["end"] + a.pad_sec) * fps))
    crop_w = int(round(H * 9 / 16)) // 2 * 2

    xs = ball_xs(a.csv, calib, fps)[f0:f1]
    xs += [None] * (f1 - f0 - len(xs))
    lefts = window_path(xs, fps, W, crop_w, a.smooth_sec, a.max_pan)
    visible = sum(x is not None for x in xs)
    inside = sum(1 for x, l in zip(xs, lefts) if x is not None and l <= x <= l + crop_w)
    print(f"{'range' if a.start is not None else f'rally #{a.rank}'}: {seg['start']:.1f}-{seg['end']:.1f}s ({seg['end'] - seg['start']:.1f}s), "
          f"score {seg['score']:.2f}; ball seen in {visible}/{f1 - f0} frames, "
          f"inside the window in {inside}/{visible} of those")

    def writer(path, w, h, logo=None):
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{w}x{h}", "-r", str(fps), "-i", "-"]
        if logo:
            cmd += ["-i", logo, "-filter_complex", vertical_logo_filter(w, h)]
        cmd += ["-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", path]
        return subprocess.Popen(cmd, stdin=subprocess.PIPE)
    vert = writer(f"{a.out}.mp4", 1080, 1920, a.logo)
    dbg_w, dbg_h = 960, int(960 * H / W) // 2 * 2
    dbg = writer(f"{a.out}_debug.mp4", dbg_w, dbg_h)
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    for i in range(f1 - f0):
        ok, frame = cap.read()
        if not ok:
            break
        l = lefts[i]
        crop = frame[:, l:l + crop_w]
        vert.stdin.write(cv2.resize(crop, (1080, 1920), interpolation=cv2.INTER_LANCZOS4).tobytes())
        d = frame.copy()
        cv2.rectangle(d, (l, 0), (l + crop_w - 1, H - 1), (0, 255, 255), 6)
        if xs[i] is not None:
            cv2.line(d, (int(xs[i]), 0), (int(xs[i]), H), (0, 0, 255), 3)
        dbg.stdin.write(cv2.resize(d, (dbg_w, dbg_h)).tobytes())
    for p in (vert, dbg):
        p.stdin.close()
        p.wait()
    print(f"wrote {a.out}.mp4 and {a.out}_debug.mp4")


if __name__ == "__main__":
    main()
