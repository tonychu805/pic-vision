"""Does the ball's own motion tell a bounce from a paddle hit? (2026-10-15)

Context. The tile arm's 37 candidates on the unselected PGC chunk (eda301d9 2026-09-25 08:21
session-000) were all reviewed by the operator in CVAT: 23 bounce (17 matched to labels + 6
unmarked), 13 paddle_hit, 1 not_ball. The audio did not separate them (EXPERIMENTS.md).

Features, fixed BEFORE the run. T = tracker-accepted ball points of the tile arm (the same
tracker as everywhere). For a candidate at frame f: 'in' = points in frames f-8..f-1, 'out' =
f+1..f+8; each side needs >= 3 points, else the event is skipped. A straight line fitted to
x and y against frame gives (vx, vy) per side, in px/frame. Four features:
  speed_ratio   |v_out| / |v_in|          (a hit adds energy; a bounce loses some)
  speed_out     |v_out|
  turn_deg      angle between v_in and v_out
  side_change   |vx_out - vx_in| / (|v_in| + 1e-6)

BAR.
  coverage     features computable for >= 80% of the 36 events
  separable    the feature with the largest |AUC - 0.5| (bounce vs hit) has AUC >= 0.85 or <= 0.15
  not chance   a label-shuffle test of that best-of-four statistic (10,000 shuffles) gives p < 0.01
All three must hold. n = 23 vs 13; there is NO held-out data at this point: any pass is a lead
to be confirmed on a second chunk, not a result.
Run: .venv/bin/python scripts/eval_motion_hit_vs_bounce.py
"""
import json, subprocess, sys
import numpy as np
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import eval_bounce_recovery as E

C = "cache/pgc_fieldtest/365c798c-6554-42b1-b0e6-b2825e73d264.calib.json"
TILE = "cache/bounce_pilot/chunk_eda301d9_0821.tile.csv"
FEATS = ("speed_ratio", "speed_out", "turn_deg", "side_change")


def tags():
    out = {}
    for proj in (3, 4):
        q = f"""select t.name, l.name from engine_task t join engine_segment s on s.task_id=t.id join engine_job j on j.segment_id=s.id
                join engine_labeledimage i on i.job_id=j.id join engine_label l on l.id=i.label_id where t.project_id={proj}"""
        r = subprocess.run(["docker", "--context", "desktop-linux", "exec", "cvat_db", "psql", "-U", "root", "-d", "cvat",
                            "-tA", "-F", "|", "-c", q], capture_output=True, text=True, check=True).stdout
        for line in r.splitlines():
            n, lab = line.split("|")
            out[int(n.split("frame ")[1].split(" ")[0])] = lab
    return out


def vel(T, frames):
    pts = [(f, T[f]) for f in frames if f in T]
    if len(pts) < 3: return None
    f = np.array([p[0] for p in pts], float); x = np.array([p[1][0] for p in pts]); y = np.array([p[1][1] for p in pts])
    return np.array([np.polyfit(f, x, 1)[0], np.polyfit(f, y, 1)[0]])


def feats(T, f):
    vi, vo = vel(T, range(f - 8, f)), vel(T, range(f + 1, f + 9))
    if vi is None or vo is None: return None
    si, so = np.linalg.norm(vi), np.linalg.norm(vo)
    cos = float(np.clip(vi @ vo / (si * so + 1e-9), -1, 1))
    return {"speed_ratio": so / (si + 1e-6), "speed_out": so, "turn_deg": float(np.degrees(np.arccos(cos))),
            "side_change": abs(vo[0] - vi[0]) / (si + 1e-6)}


def auc(pos, neg):
    return sum((p > q) + 0.5 * (p == q) for p in pos for q in neg) / (len(pos) * len(neg))


def stat(rows, labs):
    b = [i for i, l in enumerate(labs) if l == "bounce"]; h = [i for i, l in enumerate(labs) if l == "paddle_hit"]
    return max(abs(auc([rows[i][k] for i in b], [rows[i][k] for i in h]) - 0.5) for k in FEATS)


def main():
    _, _, T, cands = E.clip_points({"calib": C, "csv": TILE})
    ev = [(f, l) for f, l in sorted(tags().items()) if l in ("bounce", "paddle_hit")]
    rows, labs = [], []
    for f, l in ev:
        g = min(cands, key=lambda c: abs(c - f))
        ft = feats(T, g) if abs(g - f) <= 3 else None
        if ft: rows.append(ft); labs.append(l)
    n = len(ev)
    print(f"events {n} (bounce {sum(1 for _, l in ev if l == 'bounce')}, hit {sum(1 for _, l in ev if l == 'paddle_hit')}); "
          f"features for {len(rows)} ({len(rows) / n:.0%})")
    b = [i for i, l in enumerate(labs) if l == "bounce"]; h = [i for i, l in enumerate(labs) if l == "paddle_hit"]
    best = None
    for k in FEATS:
        pb, ph = [rows[i][k] for i in b], [rows[i][k] for i in h]
        a = auc(pb, ph)
        print(f"  {k:12s} bounce median {np.median(pb):7.2f}  hit median {np.median(ph):7.2f}  AUC(bounce>hit) {a:.2f}")
        if best is None or abs(a - 0.5) > abs(best[1] - 0.5): best = (k, a)
    obs = stat(rows, labs)
    rng = np.random.default_rng(0)
    perm = [stat(rows, list(rng.permutation(labs))) for _ in range(10000)]
    p = (1 + sum(1 for s in perm if s >= obs)) / (1 + len(perm))
    print(f"best: {best[0]} AUC {best[1]:.2f};  shuffle p = {p:.4f}")
    cov = len(rows) / n >= 0.8; sep = best[1] >= 0.85 or best[1] <= 0.15
    print(f"coverage {'PASS' if cov else 'FAIL'}   separable {'PASS' if sep else 'FAIL'}   not chance {'PASS' if p < 0.01 else 'FAIL'}")


if __name__ == "__main__":
    main()
