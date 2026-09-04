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
        --calib calib.json --out-dir reel --target-sec 300 --session-id x

Writes reel/highlight.mp4, reel/highlight_by_rank.mp4 (build_reel's own
output names) and reel/stats.json (n_candidates/n_chosen/total_duration_sec
only -- the orchestrator scp's this one small file back rather than
parsing stdout, since a print-format change elsewhere shouldn't silently
break stats reporting here).

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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--csv", required=True)
    p.add_argument("--calib", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--target-sec", type=float, default=300.0)
    p.add_argument("--session-id", default="reel")
    args = p.parse_args()

    result = build_reel(args.video, args.csv, args.calib, args.out_dir,
                         args.target_sec, args.session_id, weights=WEIGHTS)

    with open(os.path.join(args.out_dir, "stats.json"), "w") as f:
        json.dump(result["stats"], f)

    print(f"[pod_cut] done: {result['stats']}")


if __name__ == "__main__":
    main()
