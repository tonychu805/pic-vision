"""Scaled test of rally-level flight scoring (D4 config frozen, no re-tuning) on new PGC sessions
(2026-10-15). Pre-registered; written before inference ran.

Frozen config from Test D4 (most-chosen in 4 of 5 folds): window 45 frames, piece gap 3 frames, fit RMS
8 px, minimum piece 3 points, drop a rally when its mean flight share < 0.15 (rules in
tune_rally_scoring_cv.py). Detection: production rule (gap 3.0 s, >= 6 crossings, court gate, track_ball)
on the new sessions' full-session predictions (cache/scale/*.csv, plan in cache/scale_plan.json).

There are no verdicts for these sessions. The test is on the DROPPED rallies:
  - report: rallies detected, dropped, drop rate per session and overall
  - the operator watches every dropped rally (or a seed-0 random 40 if more than 40) and tags it:
    not_a_rally | real_rally | unsure
BAR: of the dropped rallies the operator tagged (excluding unsure), >= 70% are not_a_rally AND at most 3
(or 10%, whichever is larger) are real_rally. Drop rate above 25% of detected rallies is reported as
aggressive regardless. Nothing is said about recall of fakes: kept fakes are not reviewed here.
Run: .venv/bin/python scripts/scale_rally_scoring.py   -> prints a summary, writes cache/scale/dropped.json
"""
import glob, json, os, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
from src.ball import cluster_crossings, crossing_times, net_line_y
from src.calib import court_wedge
from src.track import track_ball
from src.tracknet import load_predictions
import tune_rally_scoring_cv as D4

FPS = 30.0
CFG = (45, 3, 8.0, 3, 0.15)   # W, gap, rms, minp, T


def main():
    rows, dropped = [], []
    for csvp in sorted(glob.glob("cache/scale/*.csv")):
        meta = json.load(open(csvp[:-4] + ".meta.json"))
        calib = json.load(open(meta["calib"]))
        tr = load_predictions(csvp, FPS)
        w = court_wedge(calib)
        frames = [[(x, y, c if c is not None else 1.0)] if (x is not None and w(x, y)) else [] for _, x, y, _w, _h, c in tr]
        ys, xs = track_ball(frames, max_jump=150, reset_after=15, return_x=True)
        cr = crossing_times(list(zip([i / FPS for i in range(len(ys))], ys)), net_y=net_line_y(calib), band=0)
        segs = cluster_crossings(cr, gap_sec=3.0, min_crossings=6)
        n_drop = 0
        for s in segs:
            sc = D4.rally_score(ys, xs, s, *CFG[:4])
            if sc is not None and sc < CFG[4]:
                n_drop += 1
                dropped.append({"session": os.path.basename(csvp)[:-4], "video": meta["path"], "start": s["start"],
                                "end": s["end"], "score": round(sc, 3)})
        rows.append((os.path.basename(csvp)[:-4], len(segs), n_drop))
    for name, n, d in rows:
        print(f"{name:55s} rallies {n:3d} dropped {d:2d}")
    tot, dr = sum(r[1] for r in rows), sum(r[2] for r in rows)
    print(f"\nsessions {len(rows)}  rallies {tot}  dropped {dr} ({dr / max(tot, 1):.0%})"
          f"{'  AGGRESSIVE (> 25%)' if dr / max(tot, 1) > 0.25 else ''}")
    json.dump(dropped, open("cache/scale/dropped.json", "w"), indent=1)


if __name__ == "__main__":
    main()
