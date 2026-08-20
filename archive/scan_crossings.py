"""Fast scan: find all net-crossing clusters in a video and print their timestamps.

Does NOT cut clips. Just shows where the pipeline would find rallies under given params.

Usage:
    python archive/scan_crossings.py --video <path> --net-y <y> [options]
"""

import argparse
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.ball import detect_candidates, crossing_times, cluster_crossings
from src.track import track_ball


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--net-y", type=float, required=True)
    p.add_argument("--sample-fps", type=float, default=10.0)
    p.add_argument("--weights", default="yolov8x.pt")
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--max-ball-px", type=float, default=25.0)
    p.add_argument("--band", type=float, default=0.0)
    p.add_argument("--gap-sec", type=float, default=3.0)
    p.add_argument("--min-crossings", type=int, default=3)
    p.add_argument("--max-jump", type=float, default=150.0)
    args = p.parse_args()

    print(f"Scanning {args.video}")
    print(f"  net_y={args.net_y}  conf={args.conf}  max_ball_px={args.max_ball_px}  sample_fps={args.sample_fps}")

    candidates = detect_candidates(
        args.video,
        conf=args.conf,
        weights=args.weights,
        sample_fps=args.sample_fps,
        max_ball_px=args.max_ball_px,
    )

    times_list = [t for t, _ in candidates]
    frames = [c for _, c in candidates]
    ys = track_ball(frames, max_jump=args.max_jump)
    track = list(zip(times_list, ys))
    times = crossing_times(track, args.net_y, band=args.band)
    clusters = cluster_crossings(times, args.gap_sec, min_crossings=args.min_crossings)

    print(f"\nRaw crossings: {len(times)}")
    if times:
        print("  " + "  ".join(f"{t:.1f}s" for t in times[:30]) + ("..." if len(times) > 30 else ""))

    print(f"\nRally candidates (min_crossings={args.min_crossings}):")
    if not clusters:
        print("  None found.")
    for c in clusters:
        m, s = divmod(int(c['start']), 60)
        print(f"  {m:02d}:{s:02d} – {c['end']:.1f}s   crossings={c['crossings']}")


if __name__ == "__main__":
    main()
