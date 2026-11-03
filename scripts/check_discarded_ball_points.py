"""Did the tracker throw away real ball points near the labelled bounces? (2026-10-16). Pre-registered:
committed before it was run.

Context: on bounce chunk 2 (c199a97c 0926 s002, 36 labelled bounces) the tile arm found 4 of 36 and the track
sat on fixed glints (EXPERIMENTS.md 2026-10-16). A "tracklets before commitment" design (build short tracklets
from all detections, drop stationary ones, then choose) can only help if the detector DID see the ball near the
bounces and track_ball discarded it. This measures that, per arm (tile = primary, base = reported).

Definitions, fixed now:
  raw       every TrackNet detection (one per frame, threshold 0.5), inside court_wedge(margin 400) as the
            tracker sees it
  static    a 20 px grid cell holding >= 100 raw detections over the chunk (a ball does not dwell 3+ s in
            one cell); a raw point in such a cell is 'static'
  near      frames f-8..f+8 of a labelled bounce at frame f, and within 100 px of the labelled point
  visible   >= 3 near, non-static raw points
  discarded visible AND < 3 of those near non-static points were accepted by track_ball
BAR on the tile arm:
  worth building   discarded >= 30% of the 36 bounces
  weak             discarded 15-30%
  no               discarded < 15% (the ball was not detected, or the tracker already had it)
Also reported: visible share, static cells found, how many raw points they hold.
Run: .venv/bin/python scripts/check_discarded_ball_points.py
"""
import collections, json, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
from src.calib import court_wedge
from src.tracknet import load_predictions
import eval_bounce_recovery as E
from eval_bounce_chunk2 import BASE, TILE, CALIB, LABELS

CELL, STATIC_N, WIN, RAD = 20, 100, 8, 100.0


def main():
    labs = json.load(open(LABELS))["bounces"]; n = len(labs)
    w = court_wedge(json.load(open(CALIB)), margin_px=400.0)
    for arm, csv_ in (("tile", TILE), ("base", BASE)):
        raw = {i: (x, y) for i, (_, x, y, *_r) in enumerate(load_predictions(csv_, 30.0)) if x is not None and w(x, y)}
        _, _, tracked, _ = E.clip_points({"calib": CALIB, "csv": csv_})
        cell = lambda p: (int(p[0] // CELL), int(p[1] // CELL))
        cnt = collections.Counter(cell(p) for p in raw.values())
        static = {c for c, k in cnt.items() if k >= STATIC_N}
        vis = disc = 0
        for b in labs:
            near = [f for f in range(b["frame"] - WIN, b["frame"] + WIN + 1) if f in raw and cell(raw[f]) not in static
                    and np.hypot(raw[f][0] - b["x"], raw[f][1] - b["y"]) <= RAD]
            if len(near) >= 3:
                vis += 1
                acc = sum(1 for f in near if f in tracked and np.hypot(tracked[f][0] - raw[f][0], tracked[f][1] - raw[f][1]) < 1)
                disc += acc < 3
        held = sum(cnt[c] for c in static)
        print(f"{arm:5s} raw {len(raw)}  static cells {len(static)} holding {held} ({held / max(len(raw), 1):.0%})  "
              f"visible {vis}/{n} ({vis / n:.0%})  discarded {disc}/{n} ({disc / n:.0%})")
        if arm == "tile":
            d = disc / n
            print("  VERDICT:", "WORTH BUILDING" if d >= 0.30 else "WEAK" if d >= 0.15 else "NO")


if __name__ == "__main__":
    main()
