#!/usr/bin/env python3
"""
Near-team pre-serve stillness signal (PIC-31), reusable version.

EXPERIMENTS.md 2026-08-22 ("Near-team pre-serve stillness") found near-team
ankle speed drops to 7-17% of the surrounding dead-time baseline in the last
second before a real serve, on 3 brickwall_30fps.mp4 boundaries -- a candidate
independent (non-ball) signal for PIC-31 (separating real rallies from
courtesy/dead-time net crossings, which crossing-count alone cannot do).
That entry's own next step, never run until now: check this signal AT
PIC-37's already-known, confirmed real dead-time-crossing false positives
(IMG_7743 post-bump, all 12 confirmed by trajectory-plot read, no ambiguity)
-- if the fusion idea (stillness-dip gates a crossing burst) is going to
work, these false positives should *lack* the pre-serve dip real serves have.

Method, unchanged from the original scratch analysis: yolov8n-pose run via
ultralytics' model.track(tracker="bytetrack.yaml") over a short window ending
at each candidate boundary time, vid_stride=2 (15fps effective, matching the
original). Per sampled frame, average ankle-midpoint (COCO keypoints 15/16)
displacement across whichever tracks are active that frame -- this project's
cameras reliably detect only the near team (2026-08-22 pose sanity check),
so no explicit near/far filtering is needed. Speed stays in raw pixels per
frame-step, as the original did (not projected through the homography -- foot
points are noisy for a homography built from court markings, and the
original comparison is a same-video ratio anyway).

Usage:
    python scripts/pose_stillness.py --video videos/brickwall_30fps.mp4 \
        --times 20.0 55.0 90.0 --weights yolov8n-pose.pt

    # or read boundary times from a false-positive list, one per line
    python scripts/pose_stillness.py --video videos/IMG_7743_postbump_2900s-end.mp4 \
        --times-file /tmp/fp_starts.txt
"""
import argparse

import cv2
import numpy as np

LEFT_ANKLE, RIGHT_ANKLE = 15, 16
KP_CONF_MIN = 0.3


def _ankle_midpoint(kpts_xy, kpts_conf):
    pts = []
    for idx in (LEFT_ANKLE, RIGHT_ANKLE):
        if kpts_conf[idx] >= KP_CONF_MIN:
            pts.append(kpts_xy[idx])
    if not pts:
        return None
    pts = np.array(pts)
    return tuple(pts.mean(axis=0))


def track_speeds(video_path, t_start, t_end, vid_stride=2, weights="yolov8n-pose.pt"):
    """Per-sampled-frame average ankle speed (px per frame-step) across active
    tracks, for frames in [t_start, t_end). Returns (times, speeds) — times
    are frame timestamps at which a speed was computable (i.e. not the first
    sampled frame). Tracker state is local to this window only."""
    from ultralytics import YOLO

    model = YOLO(weights)
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_MSEC, t_start * 1000.0)

    last_pos = {}
    times, speeds = [], []
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if t >= t_end:
            break
        if frame_idx % vid_stride == 0:
            res = model.track(frame, tracker="bytetrack.yaml", persist=True,
                               verbose=False, classes=[0])[0]
            step_speeds = []
            if res.boxes is not None and res.boxes.id is not None and res.keypoints is not None:
                ids = res.boxes.id.cpu().numpy().astype(int)
                kxy = res.keypoints.xy.cpu().numpy()
                kconf = res.keypoints.conf.cpu().numpy() if res.keypoints.conf is not None else None
                for i, tid in enumerate(ids):
                    conf = kconf[i] if kconf is not None else np.ones(kxy.shape[1])
                    mid = _ankle_midpoint(kxy[i], conf)
                    if mid is None:
                        continue
                    if tid in last_pos:
                        d = float(np.hypot(mid[0] - last_pos[tid][0], mid[1] - last_pos[tid][1]))
                        step_speeds.append(d)
                    last_pos[tid] = mid
            if step_speeds:
                times.append(t)
                speeds.append(float(np.mean(step_speeds)))
        frame_idx += 1
    cap.release()
    return times, speeds


def stillness_ratio(video_path, boundary_time, pre_window=1.0, baseline_window=4.5,
                     vid_stride=2, weights="yolov8n-pose.pt"):
    """Ratio of immediate pre-boundary speed to the preceding dead-time
    baseline. Returns (immediate, baseline, ratio) — baseline is None if the
    window would start before t=0 (no prior dead time to measure)."""
    t_lo = boundary_time - pre_window - baseline_window
    if t_lo < 0:
        immediate_times, immediate_speeds = track_speeds(
            video_path, max(0.0, boundary_time - pre_window), boundary_time,
            vid_stride=vid_stride, weights=weights)
        immediate = float(np.mean(immediate_speeds)) if immediate_speeds else None
        return immediate, None, None

    times, speeds = track_speeds(video_path, t_lo, boundary_time,
                                  vid_stride=vid_stride, weights=weights)
    cut = boundary_time - pre_window
    immediate_speeds = [s for t, s in zip(times, speeds) if t >= cut]
    baseline_speeds = [s for t, s in zip(times, speeds) if t < cut]
    immediate = float(np.mean(immediate_speeds)) if immediate_speeds else None
    baseline = float(np.mean(baseline_speeds)) if baseline_speeds else None
    ratio = (immediate / baseline) if (immediate is not None and baseline) else None
    return immediate, baseline, ratio


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True)
    ap.add_argument("--times", type=float, nargs="*", default=[])
    ap.add_argument("--times-file", help="one boundary time (seconds) per line")
    ap.add_argument("--weights", default="yolov8n-pose.pt")
    ap.add_argument("--pre-window", type=float, default=1.0)
    ap.add_argument("--baseline-window", type=float, default=4.5)
    ap.add_argument("--vid-stride", type=int, default=2)
    args = ap.parse_args()

    times = list(args.times)
    if args.times_file:
        with open(args.times_file) as f:
            times += [float(line.strip()) for line in f if line.strip()]

    print(f"{'time':>10} {'immediate':>10} {'baseline':>10} {'ratio':>8}")
    for t in times:
        immediate, baseline, ratio = stillness_ratio(
            args.video, t, pre_window=args.pre_window,
            baseline_window=args.baseline_window, vid_stride=args.vid_stride,
            weights=args.weights)
        imm_s = f"{immediate:.2f}" if immediate is not None else "n/a"
        base_s = f"{baseline:.2f}" if baseline is not None else "n/a"
        ratio_s = f"{ratio:.2f}" if ratio is not None else "n/a"
        print(f"{t:10.2f} {imm_s:>10} {base_s:>10} {ratio_s:>8}")


if __name__ == "__main__":
    main()
