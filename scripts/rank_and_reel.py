"""Rank a video's detector candidates (src/select.py's rank_segments, ADR-063)
and cut a highlight reel from the top-ranked ones.

Writes two versions to --out-dir: highlight.mp4 (chronological, cut_clips'
default -- the browse-ready venue-console format) and highlight_by_rank.mp4
(best-scored clip first, for reviewing the ranking itself).

Usage:
    python3 scripts/rank_and_reel.py --video videos/x_30fps.mp4 \
        --csv cache/x_predictions_k14.csv --calib calib/x_calib.json \
        --out-dir clips/x_reel --target-sec 300 --session-id x_reel
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, ".")

from src.tracknet import load_predictions
from src.calib import court_wedge
from src.track import track_ball
from src.ball import net_line_y, crossing_times, cluster_crossings
from src.select import frame_speeds, spike_threshold, rank_segments
from src.render import cut_clips, concat_clips

FPS = 30.0
GAP_SEC = 3.0
MIN_CROSSINGS = 6
PAD_SEC = 3.0
WEIGHTS = (1 / 3, 1 / 3, 1 / 3)  # (duration, peak_crossing_rate, n_spikes) -- config.yaml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--csv", required=True, help="TrackNet predictions CSV")
    ap.add_argument("--calib", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--target-sec", type=float, default=300.0)
    ap.add_argument("--session-id", default="reel")
    args = ap.parse_args()

    with open(args.calib) as f:
        calib = json.load(f)
    track = load_predictions(args.csv, FPS)
    in_court = court_wedge(calib)
    net_y = net_line_y(calib)

    times = [t for t, *_ in track]
    frames = [[(x, y, conf if conf is not None else 1.0)] if in_court(x, y) else []
              for _, x, y, w, h, conf in track]
    ys = track_ball(frames, max_jump=150, reset_after=15)
    tracked = list(zip(times, ys))
    times_crossed = crossing_times(tracked, net_y=net_y, band=0.0)
    segments = cluster_crossings(times_crossed, gap_sec=GAP_SEC, min_crossings=MIN_CROSSINGS)
    print(f"{len(segments)} candidate rally segments", file=sys.stderr)

    raw_points = sorted([(t, x, y) for t, x, y, w, h, c in track if in_court(x, y)],
                         key=lambda p: p[0])
    speeds = frame_speeds(raw_points)
    threshold = spike_threshold(speeds, percentile=90)

    ranked = rank_segments(segments, times_crossed, speeds, threshold, weights=WEIGHTS)

    print(f"\n{'rank':>4} {'start':>7} {'end':>7} {'dur':>6} {'pk_cr/s':>8} "
          f"{'spikes':>6} {'score':>6}")
    for i, r in enumerate(ranked, 1):
        print(f"{i:>4} {r['start']:>7.1f} {r['end']:>7.1f} {r['duration']:>6.1f} "
              f"{r['peak_crossing_rate']:>8.3f} {r['n_spikes']:>6} {r['score']:>6.3f}")

    chosen, total = [], 0.0
    for r in ranked:
        padded_dur = r["duration"] + 2 * PAD_SEC
        if total + padded_dur > args.target_sec and chosen:
            continue
        chosen.append(r)
        total += padded_dur
        if total >= args.target_sec:
            break
    print(f"\nchose {len(chosen)}/{len(ranked)} candidates, ~{total:.1f}s padded "
          f"(target {args.target_sec:.0f}s)", file=sys.stderr)

    scored = [{**r, "score": r["score"]} for r in chosen]
    manifest = cut_clips(args.video, scored, args.out_dir, court_id=args.session_id,
                          session_id=args.session_id, pad_sec=PAD_SEC)
    concat_clips(manifest, args.out_dir)  # chronological -> out_dir/highlight.mp4

    # second concat, same clips, best-score-first
    clips_by_rank = sorted(manifest, key=lambda c: -c["score"])
    filelist = os.path.join(args.out_dir, "_filelist_ranked.txt")
    with open(filelist, "w") as f:
        for c in clips_by_rank:
            f.write(f"file '{c['file']}'\n")
    ranked_out = os.path.join(args.out_dir, "highlight_by_rank.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                     "-i", filelist, "-c", "copy", ranked_out], check=True)
    os.remove(filelist)
    print(f"chronological -> {os.path.join(args.out_dir, 'highlight.mp4')}", file=sys.stderr)
    print(f"ranked        -> {ranked_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
