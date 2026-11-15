"""Same cut-off / top-N precision table as eval_topn_precision.py, on the four graded
public videos (validate_absolute_ranking.SESSIONS), scored against the hand labels at
IoU >= 0.5. Descriptive; companion to the PGC run (2026-10-14).
Run: .venv/bin/python scripts/eval_topn_precision_public.py
"""
import json, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from eval.harness import load_labels, match_intervals
from src.select import net_width_px, score_segments
import validate_absolute_ranking as base

rows = []  # (video, score, rank, n, is_real)
nlab_total = 0
for name, csvp, calibp, labp, wend in base.SESSIONS:
    calib = json.load(open(calibp))
    segs, crossed, speeds = base.detect(csvp, calib)
    labs = [l for l in load_labels(labp) if wend is None or l["end"] <= wend]
    if wend is not None:
        segs = [s for s in segs if s["end"] <= wend]
    scored = score_segments(segs, crossed, speeds, net_width_px(calib))
    m = match_intervals(scored, labs)
    real = {pi for pi, _, _ in m["matches"]}
    nlab_total += len(labs)
    for i, s in enumerate(scored):
        rows.append((name, s["score"], i + 1, len(scored), i in real))
    print(f"{name}: detected {len(scored)}, real {len(real)}, labelled {len(labs)}")

n = len(rows); nreal = sum(r[4] for r in rows)
print(f"\npooled: {n} detections, {nreal} real ({nreal/n:.0%}), labelled rallies {nlab_total}")
print(f"\n{'score >=':>9s} {'kept':>5s} {'real kept':>10s} {'of real':>8s} {'precision':>10s} {'recall':>7s}")
for t in (0, 30, 40, 45, 50, 55, 60, 65):
    k = [r for r in rows if r[1] >= t]; rk = sum(r[4] for r in k)
    print(f"{t:9d} {len(k):5d} {rk:10d} {rk/nreal:8.0%} {rk/len(k) if k else 0:10.0%} {rk/nlab_total:7.0%}")
print(f"\n{'top-N/video':>12s} {'kept':>5s} {'real kept':>10s} {'precision':>10s}")
for N in (3, 5, 8, 12):
    k = [r for r in rows if r[2] <= N]; rk = sum(r[4] for r in k)
    print(f"{N:12d} {len(k):5d} {rk:10d} {rk/len(k):10.0%}")
