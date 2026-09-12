"""Reel-cutting script -- runs ON the RunPod pod, right after inference
(ADR-074). Detection/ranking/cutting is pure CPU/ffmpeg work with no GPU
dependency, so it runs here instead of being shipped back to the caller
as raw detection data for a separate local cut -- the whole point of
ADR-074 is that the caller never needs predictions.csv or a local cut
step again.

Thin wrapper around scripts/rank_and_reel.py's build_reel(), which this
script's own src/ + scripts/ dependency closure gets copied onto the pod
by cloud_pipeline/run_cloud_job.py (tarred locally, scp'd over, extracted
here) -- same already-validated detect/rank/cut logic as every other
caller of build_reel, not reimplemented for the pod.

Usage (on the pod):
    python3 pod_cut.py --video video_proxy.mp4 --csv predictions.csv \
        --calib calib.json --out-dir reel --target-sec 180 --session-id x

Writes THREE reel products now (top-rally clips added on top of the
2026-09-04 full+burst pair, same "two forms of content" operator request
extended to a third): reel/full/highlight_by_rank.mp4 (build_reel, full
rally length, ranked -- now a shorter default, see TOP_LEVEL_TARGET_SEC
below), reel/burst/highlight.mp4 (scripts/burst_moment_reel.py's
build_burst_reel -- each top rally's own peak-intensity window), and
reel/top/rally_NNN.mp4 x up to TOP_RALLIES_N individual clips
(scripts/top_rallies_reel.py's build_top_rallies -- the same ranking as
"full", but delivered as separate un-concatenated files instead of one
reel). All three reuse the same detection pipeline independently (cheap
CPU work, not worth threading shared state between three otherwise-
separate, already-reviewed scripts for). BURST_TARGET_SEC is fixed, not
the caller's own --target-sec -- burst clips are ~5s each, so hitting a
300s *full-reel* target would mean 50+ clips. Set to 30s (2026-09-04,
operator request, down from an initial 60s reused from
burst_moment_reel.py's own CLI default -- 30s reads as a tighter "quick
hits" clip once real output was seen).

reel/stats.json now holds {"full": {...}, "burst": {...} | null,
"top_rallies": [{...}] | []} -- burst is null (never []) when
build_burst_reel's own candidate pool (identical detection to full,
since gap_sec/min_crossings are unchanged) comes up empty, in which case
there's no burst/highlight.mp4 to write or upload at all; top_rallies is
simply an empty list in the same situation (no padding to N, no
placeholder -- same spirit as burst's None). The orchestrator
(run_cloud_job.py) checks for each product's presence rather than
assuming it's always there.

No chronological cut of either -- operator request, 2026-09-04: the
console's Reels tab only ever offers the ranked cut, so build_reel() is
called with include_chronological=False to skip cutting it at all, not
just skip uploading it.

Deployed flat (cloud_pipeline/run_cloud_job.py's POD_REEL_DEPS tarball
extracts src/ and scripts/ as this file's own siblings, e.g.
/workspace/pod_cut.py next to /workspace/src/ and /workspace/scripts/ --
not REPO_ROOT's actual cloud_pipeline/pod_cut.py nesting), so the import
path below is this file's own directory, not its parent.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.rank_and_reel import build_reel, WEIGHTS
from scripts.burst_moment_reel import build_burst_reel
from scripts.top_rallies_reel import build_top_rallies

BURST_TARGET_SEC = 30.0  # operator request, 2026-09-04 -- see module docstring
TOP_RALLIES_N = 10  # operator request, 2026-09-12


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--csv", required=True)
    p.add_argument("--calib", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--target-sec", type=float, default=180.0)
    p.add_argument("--session-id", default="reel")
    args = p.parse_args()

    full_dir = os.path.join(args.out_dir, "full")
    full_result = build_reel(args.video, args.csv, args.calib, full_dir,
                              args.target_sec, args.session_id, weights=WEIGHTS,
                              include_chronological=False)

    burst_dir = os.path.join(args.out_dir, "burst")
    burst_result = build_burst_reel(args.video, args.csv, args.calib, burst_dir,
                                     BURST_TARGET_SEC, args.session_id)
    # None when no candidates made the cut (empty manifest) -- see module docstring.
    burst_stats = burst_result["stats"] if burst_result["chronological"] else None

    top_dir = os.path.join(args.out_dir, "top")
    top_result = build_top_rallies(args.video, args.csv, args.calib, top_dir,
                                    args.session_id, n=TOP_RALLIES_N)
    # Each entry's 'file' is cut_clips' bare filename (e.g. "rally_003.mp4"),
    # relative to top_dir -- rewritten here to the out-dir-relative path
    # (e.g. "top/rally_003.mp4") the orchestrator needs to find it on disk.
    top_rallies = [
        {"rank": c["rank"], "score": c["score"], "duration": c["duration"],
         "file": os.path.join("top", c["file"])}
        for c in top_result["manifest"]
    ]

    stats = {"full": full_result["stats"], "burst": burst_stats,
              "top_rallies": top_rallies}
    with open(os.path.join(args.out_dir, "stats.json"), "w") as f:
        json.dump(stats, f)

    print(f"[pod_cut] done: {stats}")


if __name__ == "__main__":
    main()
