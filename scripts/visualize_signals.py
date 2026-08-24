"""Burn every detection/ranking signal into a watchable clip, for eyeballing
whether the pipeline's internal state matches what's actually happening on
court -- not a static-frame chart, an actual annotated video (this is how the
pod_infer.py x/y-ratio bug was caught, ADR-064: the burned-in tracked marker
visibly sat next to the ball instead of on it).

Draws, per frame, using the exact same signal pipeline as scripts/rank_and_reel.py:
  - court-wedge boundary (src/calib.py's court_wedge) -- static per video
  - net line (src/ball.py's net_line_y) -- static per video
  - raw in-court TrackNet detection (dim gray dot, whether or not track_ball
    confirmed it)
  - track_ball-confirmed ball position (bright green dot)
  - velocity spikes (src/select.py's spike_threshold, top-decile frame-to-frame
    speed) -- an orange ring around the ball for a few frames
  - net crossings (src/ball.py's crossing_times) -- a flash across the net
    line for a few frames
  - rally-segment membership (src/ball.py's cluster_crossings, shipped
    gap_sec/min_crossings) -- a colored border, green inside a candidate
    rally, none outside

Optional, off by default (--stillness): PIC-31's pre-serve stillness signal
(scripts/pose_stillness.py) -- NOT part of the shipped pipeline (no caller
wires it into src/tracknet.py or rank_and_reel.py; it's a standalone
experimental signal, validated only as a leading indicator, not a shipped
detector input, see that module's docstring and DECISIONS.md ADR-055/057).
Drawn as a live near-team ankle-speed meter plus the immediate/baseline
stillness_ratio at the in-view segment's start boundary, so the signal can be
eyeballed against real footage rather than read off a table of numbers.

Only renders the requested time window (--start-sec/--end-sec, plus --pad-sec
of context) -- full-video signal computation is cheap, full-video frame-by-frame
rendering is not, and this is a spot-check tool, not a reel builder.

Usage:
    python3 scripts/visualize_signals.py --video videos/x_30fps.mp4 \
        --csv cache/x_predictions_k14.csv --calib calib/x_calib.json \
        --start-sec 1128.8 --end-sec 1161.5 --out clips/x_signals_check.mp4 \
        --stillness
"""
import argparse
import bisect
import json
import subprocess
import sys

sys.path.insert(0, ".")

import cv2
import numpy as np

from src.tracknet import load_predictions
from src.calib import court_wedge
from src.track import track_ball
from src.ball import net_line_y, crossing_times, cluster_crossings
from src.select import frame_speeds, spike_threshold

FPS = 30.0
GAP_SEC = 3.0
MIN_CROSSINGS = 6

RAW_COLOR = (140, 140, 140)     # gray -- in-court detection, confirmed or not
TRACKED_COLOR = (60, 220, 60)   # green -- track_ball-confirmed position
SPIKE_COLOR = (0, 140, 255)     # orange ring -- velocity spike
CROSSING_COLOR = (0, 220, 255)  # yellow flash -- net crossing
WEDGE_COLOR = (255, 120, 0)     # blue -- court-wedge boundary
NET_COLOR = (255, 0, 255)       # magenta -- net line
RALLY_BORDER = (60, 220, 60)    # green border -- inside a candidate segment
STILLNESS_COLOR = (255, 255, 0)     # cyan -- ankle-speed meter, normal
STILLNESS_ACTIVE_COLOR = (0, 0, 255)  # red -- inside the "immediate" pre-boundary window

SPIKE_HOLD_SEC = 0.3
CROSSING_HOLD_SEC = 0.4
STILLNESS_PRE_WINDOW = 1.0
STILLNESS_BASELINE_WINDOW = 4.5


def wedge_boundary(in_court, width, height, y_step=6, x_step=4):
    """Sample in_court(x, y) over a grid to trace the wedge's left/right edge
    per row -- court_wedge returns a boolean test, not the edge coordinates,
    so this recovers a drawable polyline without touching src/calib.py."""
    left, right = [], []
    for y in range(0, height, y_step):
        xs_in = [x for x in range(0, width, x_step) if in_court(x, y)]
        if xs_in:
            left.append((min(xs_in), y))
            right.append((max(xs_in), y))
    return left, right


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--calib", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--start-sec", type=float, required=True)
    ap.add_argument("--end-sec", type=float, required=True)
    ap.add_argument("--pad-sec", type=float, default=3.0)
    ap.add_argument("--gap-sec", type=float, default=GAP_SEC)
    ap.add_argument("--min-crossings", type=int, default=MIN_CROSSINGS)
    ap.add_argument("--stillness", action="store_true",
                     help="overlay PIC-31's pre-serve stillness signal (scripts/pose_stillness.py) "
                          "-- not part of the shipped pipeline, off by default")
    ap.add_argument("--stillness-weights", default="yolov8n-pose.pt")
    args = ap.parse_args()

    with open(args.calib) as f:
        calib = json.load(f)

    track = load_predictions(args.csv, FPS)
    in_court = court_wedge(calib)
    net_y = net_line_y(calib)

    times = [t for t, *_ in track]
    xs_raw = [x for _, x, y, w, h, c in track]
    ys_raw = [y for _, x, y, w, h, c in track]
    frames_cands = [[(x, y, c if c is not None else 1.0)] if in_court(x, y) else []
                     for _, x, y, w, h, c in track]
    ys_tracked = track_ball(frames_cands, max_jump=150, reset_after=15)

    tracked = list(zip(times, ys_tracked))
    tc = crossing_times(tracked, net_y=net_y, band=0.0)
    segments = cluster_crossings(tc, gap_sec=args.gap_sec, min_crossings=args.min_crossings)

    raw_points = sorted([(t, x, y) for t, x, y, w, h, c in track if in_court(x, y)],
                         key=lambda p: p[0])
    speeds = frame_speeds(raw_points)          # [(t, px_per_sec), ...]
    threshold = spike_threshold(speeds, percentile=90)
    spike_times = {t for t, v in speeds if v >= threshold}

    print(f"window signals: {len(segments)} rally segment(s) in full video, "
          f"{len(tc)} total crossings, spike threshold={threshold:.0f}px/s",
          file=sys.stderr)

    cap = cv2.VideoCapture(args.video)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    left_edge, right_edge = wedge_boundary(in_court, width, height)

    win_start = max(0.0, args.start_sec - args.pad_sec)
    win_end = args.end_sec + args.pad_sec
    frame_start = int(win_start * FPS)
    frame_end = min(len(track) - 1, int(win_end * FPS))

    still_times, still_speeds, still_max, still_boundary, still_ratio = [], [], 1.0, None, None
    if args.stillness:
        from scripts.pose_stillness import track_speeds, stillness_ratio, load_model
        in_view = [s for s in segments if win_start <= s["start"] <= win_end]
        if in_view:
            still_boundary = in_view[0]["start"]
        pose_start = win_start
        if still_boundary is not None:
            pose_start = min(win_start, still_boundary - STILLNESS_PRE_WINDOW - STILLNESS_BASELINE_WINDOW)
        pose_start = max(0.0, pose_start)
        print(f"stillness: pose-tracking [{pose_start:.1f}s, {win_end:.1f}s)...", file=sys.stderr)
        model = load_model(args.stillness_weights)
        still_times, still_speeds = track_speeds(args.video, pose_start, win_end, model=model)
        still_max = max(still_speeds) if still_speeds else 1.0
        if still_boundary is not None:
            _, _, still_ratio = stillness_ratio(
                args.video, still_boundary, pre_window=STILLNESS_PRE_WINDOW,
                baseline_window=STILLNESS_BASELINE_WINDOW, model=model)
            print(f"stillness: boundary={still_boundary:.1f}s ratio={still_ratio}", file=sys.stderr)

    tmp_out = args.out + ".raw.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(tmp_out, fourcc, FPS, (width, height))

    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_start)
    for i in range(frame_start, frame_end + 1):
        ok, frame = cap.read()
        if not ok:
            break
        t = i / FPS

        cv2.polylines(frame, [np.array(left_edge + right_edge[::-1], dtype=int)],
                      True, WEDGE_COLOR, 1)
        cv2.line(frame, (0, int(net_y)), (width, int(net_y)), NET_COLOR, 1)

        in_segment = any(s["start"] <= t <= s["end"] for s in segments)
        if in_segment:
            cv2.rectangle(frame, (0, 0), (width - 1, height - 1), RALLY_BORDER, 6)

        near_crossing = any(abs(t - ct) <= CROSSING_HOLD_SEC for ct in tc)
        if near_crossing:
            cv2.line(frame, (0, int(net_y)), (width, int(net_y)), CROSSING_COLOR, 5)
            cv2.putText(frame, "CROSSING", (16, int(net_y) - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, CROSSING_COLOR, 2)

        x_raw, y_raw = xs_raw[i], ys_raw[i]
        if x_raw is not None and y_raw is not None:
            cv2.circle(frame, (int(x_raw), int(y_raw)), 4, RAW_COLOR, -1)

        y_tr = ys_tracked[i]
        if y_tr is not None:
            cv2.circle(frame, (int(x_raw), int(y_tr)), 6, TRACKED_COLOR, 2)
            near_spike = any(abs(t - st) <= SPIKE_HOLD_SEC for st in spike_times)
            if near_spike:
                cv2.circle(frame, (int(x_raw), int(y_tr)), 16, SPIKE_COLOR, 2)

        if args.stillness and still_times:
            idx = bisect.bisect_left(still_times, t)
            idx = min(idx, len(still_times) - 1)
            cur_speed = still_speeds[idx]
            in_immediate = still_boundary is not None and \
                (still_boundary - STILLNESS_PRE_WINDOW) <= t <= still_boundary
            color = STILLNESS_ACTIVE_COLOR if in_immediate else STILLNESS_COLOR

            bar_x, bar_y, bar_w, bar_h = width - 220, 16, 200, 18
            cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (60, 60, 60), 1)
            fill_w = int(bar_w * min(1.0, cur_speed / still_max))
            cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), color, -1)
            cv2.putText(frame, f"ankle speed {cur_speed:4.1f}px/step", (bar_x, bar_y + bar_h + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            if still_ratio is not None:
                cv2.putText(frame, f"stillness ratio (t={still_boundary:.1f}s): {still_ratio:.2f}",
                            (bar_x - 90, bar_y + bar_h + 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, STILLNESS_COLOR, 1)

        cv2.putText(frame, f"t={t:6.1f}s  frame={i}", (16, height - 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        writer.write(frame)

    writer.release()
    cap.release()

    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", tmp_out,
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-an", args.out,
    ], check=True)
    subprocess.run(["rm", "-f", tmp_out], check=True)
    print(f"wrote {args.out} ({win_start:.1f}s-{win_end:.1f}s)", file=sys.stderr)


if __name__ == "__main__":
    main()
