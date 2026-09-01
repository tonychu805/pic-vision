"""Cut a highlight reel from just the highest-intensity *moment* inside each
top-ranked rally, not the whole rally (src/select.py's new peak_window) --
a punchier, shorter-per-clip format than rank_and_reel.py's build_reel,
which always keeps a full rally start-to-end.

Detects and ranks candidate rally segments the same way as rank_and_reel.py
(src/select.py's rank_segments, ADR-063), but defaults to weighting duration
out entirely (0, 0.5, 0.5) -- appropriate here because the output clip only
keeps a few seconds around each rally's own peak-crossing-rate window, so a
long rally gets no length bonus; ranking is "how intense was this rally's
best moment", not "how long was it".

Each chosen rally then contributes ONE clip: [peak_window start, peak_window
end] + a small pad (MOMENT_PAD, shorter than build_reel's full-rally
PAD_SEC=3.0 since this is meant to feel like a quick hit, not a full point).

Usage:
    python3 scripts/burst_moment_reel.py --video videos/x_30fps.mp4 \
        --csv cache/x_predictions_k14.csv --calib calib/x_calib.json \
        --out-dir clips/x_burst_moments --target-sec 60 --session-id x_burst_moments
"""
import argparse
import sys

sys.path.insert(0, ".")

from src.tracknet import load_predictions
from src.calib import court_wedge
from src.track import track_ball
from src.ball import net_line_y, crossing_times, cluster_crossings
from src.select import frame_speeds, spike_threshold, rank_segments, peak_window
from src.render import cut_clips, concat_clips

FPS = 30.0
GAP_SEC = 3.0
MIN_CROSSINGS = 6
MOMENT_WINDOW = 3.0   # matches rank_segments' peak_crossing_rate window -- the
                       # signal used to rank and the span actually cut agree
MOMENT_PAD = 1.5       # shorter than build_reel's 3.0s -- these are meant to
                       # be quick hits, not full rally context
WEIGHTS = (0.0, 0.5, 0.5)  # (duration, peak_crossing_rate, n_spikes) -- no
                            # duration credit, since only a fixed-size window
                            # gets cut regardless of the rally's real length


def build_burst_reel(video, csv, calib_path, out_dir, target_sec, session_id,
                      weights=WEIGHTS, window=MOMENT_WINDOW, pad_sec=MOMENT_PAD):
    """Detect rally candidates, rank them, and cut a reel of just each
    top-ranked rally's peak-intensity window (not the whole rally).

    Returns {"manifest", "chronological", "stats"} -- stats is
    {"n_candidates", "n_chosen", "total_duration_sec"}."""
    with open(calib_path) as f:
        import json
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
    print(f"{len(segments)} candidate rally segments", file=sys.stderr)

    raw_points = sorted([(t, x, y) for t, x, y, w, h, c in track if in_court(x, y)],
                         key=lambda p: p[0])
    speeds = frame_speeds(raw_points)
    threshold = spike_threshold(speeds, percentile=90)

    ranked = rank_segments(segments, times_crossed, speeds, threshold, weights=weights)

    print(f"\n{'rank':>4} {'rally':>7}-{'end':>7} {'mo_start':>9} {'mo_end':>7} "
          f"{'pk_cr/s':>8} {'spikes':>6} {'score':>6}")
    moments = []
    for i, r in enumerate(ranked, 1):
        seg_crossings = [t for t in times_crossed if r["start"] <= t <= r["end"]]
        w_start, w_end, rate = peak_window(seg_crossings, r["start"], r["end"],
                                            window=window)
        print(f"{i:>4} {r['start']:>7.1f}-{r['end']:>7.1f} {w_start:>9.1f} {w_end:>7.1f} "
              f"{rate:>8.3f} {r['n_spikes']:>6} {r['score']:>6.3f}")
        moments.append({**r, "start": w_start, "end": w_end, "peak_rate": rate})

    chosen, total = [], 0.0
    for m in moments:
        padded_dur = (m["end"] - m["start"]) + 2 * pad_sec
        if total + padded_dur > target_sec and chosen:
            continue
        chosen.append(m)
        total += padded_dur
        if total >= target_sec:
            break
    print(f"\nchose {len(chosen)}/{len(moments)} moments, ~{total:.1f}s padded "
          f"(target {target_sec:.0f}s)", file=sys.stderr)

    manifest = cut_clips(video, chosen, out_dir, court_id=session_id,
                          session_id=session_id, pad_sec=pad_sec)
    chrono_path = concat_clips(manifest, out_dir)
    print(f"reel -> {chrono_path}", file=sys.stderr)

    return {
        "manifest": manifest,
        "chronological": chrono_path,
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
    ap.add_argument("--target-sec", type=float, default=60.0)
    ap.add_argument("--session-id", default="burst_moments")
    ap.add_argument("--weights", type=float, nargs=3, default=None,
                     metavar=("W_DURATION", "W_PEAK_CROSSING_RATE", "W_N_SPIKES"),
                     help="override the default 0-0.5-0.5 moment-ranking weights")
    args = ap.parse_args()

    build_burst_reel(args.video, args.csv, args.calib, args.out_dir,
                      args.target_sec, args.session_id,
                      weights=tuple(args.weights) if args.weights else WEIGHTS)


if __name__ == "__main__":
    main()
