"""Rank a video's detector candidates (src/select.py's rank_segments, ADR-063)
and cut a highlight reel from the top-ranked ones.

Writes two versions to --out-dir: highlight.mp4 (chronological, cut_clips'
default -- the browse-ready venue-console format) and highlight_by_rank.mp4
(best-scored clip first, for reviewing the ranking itself).

build_reel() below is the reusable core -- also called by webapp/pipeline.py
so the web UI runs the exact same detect+rank+reel logic as this CLI.

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


def build_reel(video, csv, calib_path, out_dir, target_sec, session_id, log_path=None,
                weights=WEIGHTS):
    """Detect rally candidates, rank them, and cut a highlight reel.

    Writes highlight.mp4 (chronological) and highlight_by_rank.mp4 (best-scored
    first) to out_dir. log_path, if given, gets the same progress lines as
    stderr appended to it too -- webapp/pipeline.py passes its job's log.txt so
    a job run through the web UI is tailable there; plain CLI usage leaves it
    None and relies on stderr alone.

    weights: (w_duration, w_peak_crossing_rate, w_n_spikes) passed to
    src/select.py's rank_segments -- defaults to the shipped config.yaml
    formula (ADR-063). Overriding this changes what gets ranked highest but
    not the candidate segments themselves or how they're cut.

    Returns {"manifest", "chronological", "ranked", "stats"} -- stats is
    {"n_candidates", "n_chosen", "total_duration_sec"}.
    """
    def report(msg):
        print(msg, file=sys.stderr)
        if log_path:
            with open(log_path, "a") as f:
                f.write(msg.rstrip("\n") + "\n")

    def report_stdout(msg):
        # The ranked table (below) prints to stdout in the original script,
        # not stderr like everything else -- preserved here so the CLI's
        # stdout/stderr split is unchanged.
        print(msg)
        if log_path:
            with open(log_path, "a") as f:
                f.write(msg.rstrip("\n") + "\n")

    with open(calib_path) as f:
        calib = json.load(f)
    track = load_predictions(csv, FPS)
    in_court = court_wedge(calib)
    net_y = net_line_y(calib)

    times = [t for t, *_ in track]
    frames = [[(x, y, conf if conf is not None else 1.0)] if in_court(x, y) else []
              for _, x, y, w, h, conf in track]
    ys = track_ball(frames, max_jump=150, reset_after=15)
    tracked = list(zip(times, ys))
    times_crossed = crossing_times(tracked, net_y=net_y, band=0.0)
    segments = cluster_crossings(times_crossed, gap_sec=GAP_SEC, min_crossings=MIN_CROSSINGS)
    report(f"{len(segments)} candidate rally segments")

    raw_points = sorted([(t, x, y) for t, x, y, w, h, c in track if in_court(x, y)],
                         key=lambda p: p[0])
    speeds = frame_speeds(raw_points)
    threshold = spike_threshold(speeds, percentile=90)

    ranked = rank_segments(segments, times_crossed, speeds, threshold, weights=weights)

    report_stdout(f"\n{'rank':>4} {'start':>7} {'end':>7} {'dur':>6} {'pk_cr/s':>8} "
                  f"{'spikes':>6} {'score':>6}")
    for i, r in enumerate(ranked, 1):
        report_stdout(f"{i:>4} {r['start']:>7.1f} {r['end']:>7.1f} {r['duration']:>6.1f} "
                      f"{r['peak_crossing_rate']:>8.3f} {r['n_spikes']:>6} {r['score']:>6.3f}")

    chosen, total = [], 0.0
    for r in ranked:
        padded_dur = r["duration"] + 2 * PAD_SEC
        if total + padded_dur > target_sec and chosen:
            continue
        chosen.append(r)
        total += padded_dur
        if total >= target_sec:
            break
    report(f"\nchose {len(chosen)}/{len(ranked)} candidates, ~{total:.1f}s padded "
           f"(target {target_sec:.0f}s)")

    scored = [{**r, "score": r["score"]} for r in chosen]
    manifest = cut_clips(video, scored, out_dir, court_id=session_id,
                          session_id=session_id, pad_sec=PAD_SEC)
    chrono_path = concat_clips(manifest, out_dir)  # chronological -> out_dir/highlight.mp4

    # second concat, same clips, best-score-first
    clips_by_rank = sorted(manifest, key=lambda c: -c["score"])
    filelist = os.path.join(out_dir, "_filelist_ranked.txt")
    with open(filelist, "w") as f:
        for c in clips_by_rank:
            f.write(f"file '{c['file']}'\n")
    ranked_path = os.path.join(out_dir, "highlight_by_rank.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                     "-i", filelist, "-c", "copy", ranked_path], check=True)
    os.remove(filelist)
    report(f"chronological -> {chrono_path}")
    report(f"ranked        -> {ranked_path}")

    return {
        "manifest": manifest,
        "chronological": chrono_path,
        "ranked": ranked_path,
        "stats": {
            "n_candidates": len(segments),
            "n_chosen": len(chosen),
            "total_duration_sec": total,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--csv", required=True, help="TrackNet predictions CSV")
    ap.add_argument("--calib", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--target-sec", type=float, default=300.0)
    ap.add_argument("--session-id", default="reel")
    ap.add_argument("--weights", type=float, nargs=3, default=None,
                     metavar=("W_DURATION", "W_PEAK_CROSSING_RATE", "W_N_SPIKES"),
                     help="override the shipped 1/3-1/3-1/3 ranking weights, "
                          "e.g. --weights 0 1 0 for a burst-only reel")
    args = ap.parse_args()

    build_reel(args.video, args.csv, args.calib, args.out_dir,
               args.target_sec, args.session_id,
               weights=tuple(args.weights) if args.weights else WEIGHTS)


if __name__ == "__main__":
    main()
