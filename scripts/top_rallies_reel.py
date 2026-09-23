"""Cut each of a session's top-N individual rallies into its own clip --
no concatenation, no fixed time budget, unlike rank_and_reel.py's
build_reel() or burst_moment_reel.py's build_burst_reel().

Ranks candidates the same way build_reel() does (src/select.py's
rank_segments, ADR-063, identical default weights) so "top rally" means
the same thing here as it already does in the "full" reel's ranked
ordering (highlight_by_rank.mp4) -- this just delivers the same ranking
as N separate files instead of one concatenated reel.

Usage:
    python3 scripts/top_rallies_reel.py --video videos/x_30fps.mp4 \
        --csv cache/x_predictions_k14.csv --calib calib/x_calib.json \
        --out-dir clips/x_top_rallies --n 10 --session-id x_top_rallies
"""
import argparse
import json
import sys

sys.path.insert(0, ".")

from src.rallies import detect_candidates
from src.select import rank_segments
from src.render import cut_clips

PAD_SEC = 3.0  # same as rank_and_reel.py's build_reel -- full rally context
WEIGHTS = (1 / 3, 1 / 3, 1 / 3)  # same score as build_reel's ranking (ADR-063)
DEFAULT_N = 10


def build_top_rallies(video, csv, calib_path, out_dir, session_id, n=DEFAULT_N,
                       weights=WEIGHTS, pad_sec=PAD_SEC, logo_path=None):
    """Detect rally candidates, rank them, and cut the top `n` into their
    own clips -- each its own file, never concatenated.

    Fewer than `n` clips when fewer candidates qualify at all -- no
    padding or placeholder, same spirit as build_burst_reel handling an
    empty candidate pool by just producing nothing.

    Returns {"manifest", "stats"}. manifest is cut_clips' per-clip list
    (each entry already carries 'score', src/render.py's manifest_entry)
    with a 'rank' field added (1 = highest score) and re-sorted into rank
    order -- cut_clips itself always returns clips in chronological
    (start-time) order for its own manifest.json bookkeeping, which is not
    the order this function's callers want. stats is
    {"n_candidates", "n_chosen"}.
    """
    cand = detect_candidates(video, csv, calib_path)
    segments, times_crossed, speeds, threshold = cand["segments"], cand["times_crossed"], cand["speeds"], cand["threshold"]
    print(f"{len(segments)} candidate rally segments", file=sys.stderr)

    ranked = rank_segments(segments, times_crossed, speeds, threshold, weights=weights)
    chosen = ranked[:n]
    print(f"chose top {len(chosen)}/{len(ranked)} rallies by score (n={n})",
          file=sys.stderr)

    manifest = cut_clips(video, chosen, out_dir, court_id=session_id,
                          session_id=session_id, pad_sec=pad_sec, logo_path=logo_path)
    by_rank = sorted(manifest, key=lambda c: -(c["score"] or 0.0))
    for rank, clip in enumerate(by_rank, 1):
        clip["rank"] = rank

    return {
        "manifest": by_rank,
        "stats": {"n_candidates": len(segments), "n_chosen": len(chosen)},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--video", required=True)
    ap.add_argument("--csv", required=True, help="TrackNet predictions CSV")
    ap.add_argument("--calib", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--n", type=int, default=DEFAULT_N,
                     help="how many top-ranked rallies to cut (default 10)")
    ap.add_argument("--session-id", default="top_rallies")
    ap.add_argument("--weights", type=float, nargs=3, default=None,
                     metavar=("W_DURATION", "W_PEAK_CROSSING_RATE", "W_N_SPIKES"),
                     help="override the default ranking weights (ADR-063)")
    args = ap.parse_args()

    result = build_top_rallies(
        args.video, args.csv, args.calib, args.out_dir, args.session_id,
        n=args.n, weights=tuple(args.weights) if args.weights else WEIGHTS)
    print(json.dumps(result["stats"]))


if __name__ == "__main__":
    main()
