"""Does removing fixed glare spots before tracking let the bounce finder find chunk-2 bounces? (2026-10-16).
Pre-registered: committed before it was run.

Chunk 2 (c199a97c 0926 s002, 36 labelled bounces): tile arm found 4. Static cells = 20 px grid cells holding
>= 100 raw detections over the chunk (check_discarded_ball_points.py definition; 4 cells on the tile arm).
Here every raw detection in a static cell is removed BEFORE track_ball; tracker, finder and matching (+-3 frames,
15 px) otherwise unchanged (eval_bounce_recovery.clip_points). Tile arm primary, base reported.

BAR (tile arm, found of 36):
  glare is a main cause     found >= 10 (2.5x the 4 found with glare in)
  glare is a minor cause    found 6-9
  not the cause             found <= 5
Also reported: labelled bounces lying inside a static cell (lost to the removal by construction), candidates,
candidates matching a label.
Run: .venv/bin/python scripts/check_static_removed_bounces.py
"""
import collections, json, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
from src.bounce_eval import recover
from src.calib import court_wedge
from src.track import track_ball
from src.tracknet import load_predictions
import eval_bounce_recovery as E
from eval_bounce_chunk2 import BASE, TILE, CALIB, LABELS
from check_discarded_ball_points import CELL, STATIC_N


def points(csv_, calib, drop_static):
    tr = load_predictions(csv_, 30.0)
    w = court_wedge(calib, margin_px=400.0)
    cell = lambda x, y: (int(x // CELL), int(y // CELL))
    cnt = collections.Counter(cell(x, y) for _, x, y, *_r in tr if x is not None and w(x, y))
    static = {c for c, k in cnt.items() if k >= STATIC_N} if drop_static else set()
    raw = {i: (x, y) for i, (_, x, y, *_r) in enumerate(tr) if x is not None}
    frames = [[(x, y, c if c is not None else 1.0)] if (x is not None and w(x, y) and cell(x, y) not in static) else []
              for _, x, y, _w, _h, c in tr]
    ys, xs = track_ball(frames, max_jump=150, reset_after=15, return_x=True)
    tracked = {i: (xs[i], ys[i]) for i in range(len(ys)) if ys[i] is not None and xs[i] is not None}
    cf, pts = E.sbp.candidates(xs, ys, 0, len(ys) - 1)
    return np.array(calib["homography"], float), raw, tracked, {f: pts[f] for f in cf}, static, cell


def main():
    labs = json.load(open(LABELS))["bounces"]; n = len(labs); calib = json.load(open(CALIB))
    for arm, csv_ in (("tile", TILE), ("base", BASE)):
        for drop in (False, True):
            H, raw, tracked, cands, static, cell = points(csv_, calib, drop)
            r = [recover({"frame": b["frame"], "x": b["x"], "y": b["y"], "visible": True}, raw, tracked, cands, H) for b in labs]
            found = sum(x["found"] for x in r)
            match = sum(1 for g in cands if any(abs(g - b["frame"]) <= 3 for b in labs))
            on = sum(1 for b in labs if cell(b["x"], b["y"]) in static)
            print(f"{arm:5s} {'glare removed' if drop else 'as before   '}  found {found:2d}/{n}  candidates {len(cands):3d}"
                  f"  matching {match:2d}" + (f"  labels on a static cell {on}" if drop else ""))
            if arm == "tile" and drop:
                print("  VERDICT:", "MAIN CAUSE" if found >= 10 else "MINOR CAUSE" if found >= 6 else "NOT THE CAUSE")


if __name__ == "__main__":
    main()
