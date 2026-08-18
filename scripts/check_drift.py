"""Check whether a camera holds still for a whole recording.

Run this on any new footage BEFORE calibrating, labeling, or scoring it. A
mid-session camera bump silently invalidates `net_y` from that instant on and
looks exactly like a detection problem downstream (ADR-049) -- it cost a full
session to diagnose by hand on IMG_7743.

Usage:
    python scripts/check_drift.py --video game.mp4 [--step-sec 60] [--width 960]

Reference readings (2026-08-18, --width 960):
    brickwall_pro_series_finals   0.1 px over 25 min   locked -- ideal
    IMG_7743                      29 px step at ~2859s bumped -- needs split calibration
    IMG_7655                      25 px step at ~480s + 15 px creep

Exit code is 1 when a bump is found, so this can gate a pipeline run.
"""

import argparse
import os
import sys

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.drift import phase_offset, find_bumps, drift_span


def measure(video, step_sec, width):
    """Sample the video every step_sec and measure each frame's offset from the
    first. Returns (samples, duration) where samples is [(t, dx, dy, resp), ...]
    starting at the reference frame itself (0, 0, 0, 1.0)."""
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise SystemExit(f"cannot open {video}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if not fps or not frames:
        raise SystemExit(f"{video}: no usable fps/frame count")
    duration = frames / fps

    ref = None
    samples = []
    t = 0.0
    while t < duration - 1:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h = int(round(g.shape[0] * width / g.shape[1]))
        g = cv2.resize(g, (width, h))
        if ref is None:
            ref = g
            samples.append((t, 0.0, 0.0, 1.0))
        else:
            dx, dy, resp = phase_offset(ref, g)
            samples.append((t, dx, dy, resp))
        t += step_sec
    cap.release()
    return samples, duration


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--step-sec", type=float, default=60.0,
                   help="sampling interval; also the precision of a reported bump time")
    p.add_argument("--width", type=int, default=960,
                   help="analysis width -- all px figures are at this scale")
    p.add_argument("--min-step-px", type=float, default=5.0,
                   help="offset change between consecutive samples that counts as a bump")
    args = p.parse_args()

    samples, duration = measure(args.video, args.step_sec, args.width)
    print(f"{args.video}: {duration:.0f}s, {len(samples)} samples every {args.step_sec:.0f}s, "
          f"measured at {args.width}px wide")
    print(f"{'t(s)':>8} {'dx':>8} {'dy':>8} {'resp':>6}")
    for t, dx, dy, resp in samples:
        print(f"{t:8.0f} {dx:8.2f} {dy:8.2f} {resp:6.2f}")

    span_x, span_y = drift_span(samples)
    bumps = find_bumps(samples, min_step_px=args.min_step_px)
    print(f"\ntotal travel: {span_x:.1f} px in x, {span_y:.1f} px in y")

    if bumps:
        print(f"\nBUMPED -- {len(bumps)} step(s) over {args.min_step_px} px:")
        for t0, t1, sdx, sdy in bumps:
            print(f"  between t={t0:.0f}s and t={t1:.0f}s: dx {sdx:+.1f} px, dy {sdy:+.1f} px")
        print("\nCalibration is invalid across each of those points (ADR-049). Split the")
        print("video and labels there and calibrate each segment separately.")
        return 1

    if max(span_x, span_y) > args.min_step_px:
        print("\nCREEP -- no single bump, but the camera wandered. There is no clean")
        print("split point; expect boundary error to grow through the file.")
        return 0

    print("\nSTABLE -- one calibration covers the whole recording.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
