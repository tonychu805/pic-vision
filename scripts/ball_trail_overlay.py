"""Burn a ball-path trail onto a clip from TrackNet predictions (PIC-204,
Court Moments Stage 1).

The trail is drawn ONLY from real, gated detections:
  - a detection must be inside the court wedge (src/calib.py court_wedge) and,
    when the CSV has a Conf column, at or above --min-conf;
  - two consecutive trail points are joined by a line only if they come from
    adjacent frames (max_gap_frames) AND are within --max-jump pixels of each
    other. A gap or a jump breaks the line -- we never interpolate across
    occlusion, so a missing stretch shows as a visible gap, not a guess;
  - older trail points fade out over --trail-sec.

The source video is never modified; output is a new file.

Usage:
    python3 scripts/ball_trail_overlay.py --video videos/brickwall_30fps.mp4 \
        --csv cache/brickwall_30fps_predictions_k14.csv \
        --calib calib/brickwall_30fps_calib.json \
        --labels eval/labels/brickwall_30fps.jsonl --rally 24 \
        --out clips/brickwall_trail_r24.mp4
    # or an explicit window: --start-sec 763.3 --end-sec 771.3
"""
import argparse
import json
import subprocess
import sys

sys.path.insert(0, ".")

from src.calib import court_wedge
from src.tracknet import load_predictions

FPS = 30.0
TRAIL_COLOR = (60, 220, 60)   # BGR green
HEAD_COLOR = (255, 255, 255)


def gated_points(track, in_court, min_conf=0.0):
    """Per-frame (x, y) for detections that pass the gate, else None.

    track: [(t, x, y, w, h, conf)] from load_predictions (None where unseen).
    A missing Conf (older CSV) is accepted -- only a *present* low value
    rejects a point."""
    out = []
    for _t, x, y, _w, _h, conf in track:
        if x is None or y is None or not in_court(x, y):
            out.append(None)
        elif conf is not None and conf < min_conf:
            out.append(None)
        else:
            out.append((x, y))
    return out


def trail_segments(points, frame_idx, trail_frames, max_gap_frames=1, max_jump=150.0):
    """Line segments to draw at frame_idx, as [(p0, p1, age_frames)].

    Walks back up to trail_frames and joins two gated points only when they
    are <= max_gap_frames apart in time and <= max_jump apart in pixels.
    Anything else (occlusion, a jump to a different object) breaks the trail.
    age_frames is the age of the newer end (0 = current frame)."""
    segs = []
    prev = None  # (frame, (x, y))
    lo = max(0, frame_idx - trail_frames)
    for f in range(frame_idx, lo - 1, -1):
        p = points[f]
        if p is None:
            continue
        if prev is not None:
            pf, pp = prev
            gap = pf - f
            dist = ((pp[0] - p[0]) ** 2 + (pp[1] - p[1]) ** 2) ** 0.5
            if gap <= max_gap_frames and dist <= max_jump:
                segs.append((p, pp, frame_idx - pf))
        prev = (f, p)
    return segs


def resolve_window(args):
    if args.rally is not None:
        with open(args.labels) as f:
            for line in f:
                r = json.loads(line)
                if r.get("rally_id") == args.rally:
                    return r["start"], r["end"]
        raise SystemExit(f"rally {args.rally} not found in {args.labels}")
    if args.start_sec is None or args.end_sec is None:
        raise SystemExit("give --rally (with --labels) or --start-sec and --end-sec")
    return args.start_sec, args.end_sec


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
    ap.add_argument("--trail-sec", type=float, default=1.0)
    ap.add_argument("--min-conf", type=float, default=0.0)
    ap.add_argument("--max-jump", type=float, default=150.0)
    ap.add_argument("--max-gap-frames", type=int, default=1)
    args = ap.parse_args()

    import cv2

    start, end = resolve_window(args)
    with open(args.calib) as f:
        calib = json.load(f)
    in_court = court_wedge(calib)
    track = load_predictions(args.csv, FPS)
    points = gated_points(track, in_court, args.min_conf)

    cap = cv2.VideoCapture(args.video)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    f0 = max(0, int((start - args.pad_sec) * FPS))
    f1 = min(len(points) - 1, int((end + args.pad_sec) * FPS))
    trail_frames = max(1, int(args.trail_sec * FPS))

    tmp = args.out + ".raw.mp4"
    writer = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (width, height))
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    n_with_ball = 0
    for i in range(f0, f1 + 1):
        ok, frame = cap.read()
        if not ok:
            break
        for p0, p1, age in trail_segments(points, i, trail_frames,
                                           args.max_gap_frames, args.max_jump):
            fade = 1.0 - age / trail_frames
            color = tuple(int(c * (0.35 + 0.65 * fade)) for c in TRAIL_COLOR)
            cv2.line(frame, (int(p0[0]), int(p0[1])), (int(p1[0]), int(p1[1])),
                     color, max(1, int(1 + 3 * fade)))
        if points[i] is not None:
            n_with_ball += 1
            cv2.circle(frame, (int(points[i][0]), int(points[i][1])), 5, HEAD_COLOR, 1)
        cv2.putText(frame, f"{int(i / FPS // 60)}:{i / FPS % 60:04.1f}", (16, height - 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        writer.write(frame)
    writer.release()
    cap.release()

    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", tmp, "-c:v", "libx264",
                    "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", "-an", args.out], check=True)
    subprocess.run(["rm", "-f", tmp], check=True)
    total = f1 - f0 + 1
    print(f"wrote {args.out}: {f0 / FPS:.1f}s-{f1 / FPS:.1f}s, "
          f"ball shown on {n_with_ball}/{total} frames ({100 * n_with_ball / total:.0f}%)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
