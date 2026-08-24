"""Rank and cut a highlight reel (as rank_and_reel.py does) for a session whose
calibration is only valid in pieces -- e.g. IMG_7743, where a mid-session
camera bump at t~2900s invalidated the original calibration for the rest of
the recording (DECISIONS.md ADR-049). Detection, gating, and net-crossing
math are all run separately per calibrated time range against the *same*
full-session predictions CSV (no re-inference needed -- this is the same
split-calibration method used throughout EXPERIMENTS.md since 2026-08-17),
then merged into one candidate set before ranking, so scores are comparable
across the whole session rather than normalized per half.

Usage:
    python3 scripts/rank_and_reel_split.py --video videos/IMG_7743_fixed.mp4 \
        --csv cache/IMG_7743_predictions_k14.csv \
        --calib calib/IMG_7743_prebump_0-2900s_calib.json 0 2900 \
        --calib calib/IMG_7743_postbump_2900s-end_calib.json 2900 4037.1 \
        --out-dir clips/IMG_7743_reel --target-sec 300 --session-id IMG_7743_reel
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
    ap.add_argument("--video", required=True, help="full-session video to cut clips from")
    ap.add_argument("--csv", required=True, help="TrackNet predictions CSV, full session")
    ap.add_argument("--calib", required=True, action="append", nargs=3,
                     metavar=("PATH", "T_MIN", "T_MAX"),
                     help="one calibration file + the [t_min, t_max) range it's valid for; "
                          "repeat for each piece, e.g. --calib pre.json 0 2900 --calib post.json 2900 4037")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--target-sec", type=float, default=300.0)
    ap.add_argument("--session-id", default="reel")
    args = ap.parse_args()

    pieces = [(path, float(t_min), float(t_max)) for path, t_min, t_max in args.calib]
    full_track = load_predictions(args.csv, FPS)

    all_segments, all_crossing_times, all_speeds = [], [], []
    for calib_path, t_min, t_max in pieces:
        with open(calib_path) as f:
            calib = json.load(f)
        track = [row for row in full_track if t_min <= row[0] < t_max]
        if not track:
            print(f"{calib_path}: no predictions in [{t_min}, {t_max}), skipping", file=sys.stderr)
            continue
        times = [t for t, *_ in track]
        in_court = court_wedge(calib)
        net_y = net_line_y(calib)

        frames = [[(x, y, conf if conf is not None else 1.0)] if in_court(x, y) else []
                  for _, x, y, w, h, conf in track]
        ys = track_ball(frames, max_jump=150, reset_after=15)
        tracked = list(zip(times, ys))
        times_crossed = crossing_times(tracked, net_y=net_y, band=0.0)
        segments = cluster_crossings(times_crossed, gap_sec=GAP_SEC, min_crossings=MIN_CROSSINGS)
        print(f"{calib_path} [{t_min:.0f}-{t_max:.0f}s]: {len(segments)} candidate segments",
              file=sys.stderr)

        raw_points = sorted([(t, x, y) for t, x, y, w, h, c in track if in_court(x, y)],
                             key=lambda p: p[0])
        all_segments.extend(segments)
        all_crossing_times.extend(times_crossed)
        all_speeds.extend(frame_speeds(raw_points))

    all_segments.sort(key=lambda s: s["start"])
    threshold = spike_threshold(all_speeds, percentile=90)
    ranked = rank_segments(all_segments, all_crossing_times, all_speeds, threshold, weights=WEIGHTS)

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
