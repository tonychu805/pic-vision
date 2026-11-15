"""Rally formation: what should count as evidence that a rally happened? (PIC-228 / PIC-48)

Findings that motivate it (EXPERIMENTS.md 2026-10-13): of 18 labelled rallies k14 misses,
14 are ordinary rallies, 2 fast, 1 dink, 1 serve-and-return; the tracked dot followed the
ball in all 18; they are shorter (7.1 s vs 10.0 s) and have 2-4 image-row crossings, so the
"at least 6 crossings" rule cuts them. A failed serve gets 5-12 jitter crossings from a ball
bouncing at the net. The crossing count does not rank real above fake in that range.

Arms, fixed BEFORE running (nothing tuned on results; gap_sec 3.0 and the tracker's
max_jump / reset_after as in production for every arm):
  R0  current rule: crossings of the net row, band 0, min_crossings 6 (baseline)
  E1  excursions: crossings only when the ball is tracked at least 30 px beyond the net row
      on the far side of the previous one (band 30), min_crossings 4
  E2  as E1 with band 15
  S1  R0 + the tracker's existing segment filters (min_seg_frames 8, min_seg_span 60 px),
      which drop tracked runs that are very short or do not move (a ball at rest)
  S2  E1 + the same segment filters
  A1  agreement-only: frames where k14 and yolo11x both detect within 25 px (brickwall
      excerpts only, where the yolo11x CSVs exist), band 0, min_crossings 4. Reported, not gated.

Three sets:
  MISSED  the 18 labelled rallies R0 misses on the two 600 s excerpts (pb_draft_cup,
          brickwall-SEMI): cache/missed_review_key.csv. Count recovered at IoU >= 0.5.
  PGC     the 30 judged fresh clips (cache/fresh_sample_key.csv): 15 real, 12 not a rally, 3
          serve-and-return only. R0 detects all of them by construction. Count of each group
          the arm still detects (IoU >= 0.5 with a segment from the same segment's CSV).
  DEV     the four graded videos (validate_absolute_ranking.SESSIONS): pooled precision and
          recall at IoU >= 0.5 against the hand labels.

BAR, fixed before running. An arm HELPS only if all hold:
  (a) recovers >= 6 of the 18 MISSED rallies,
  (b) PGC: loses at most 1 of the 15 real clips,
  (c) DEV: recall >= R0 - 0.02 AND precision >= R0 - 0.03.
Also reported, not gated: how many of the 15 PGC non-rally clips each arm removes.
Two public excerpts, one venue's clips, in sample: a pass is a lead and needs a playback
check of the recovered rallies before anything enters src/rallies.py.
Run: .venv/bin/python scripts/eval_rally_formation.py
"""
import csv, json, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
from eval.harness import iou, load_labels, match_intervals
from src.ball import cluster_crossings, crossing_times, net_line_y
from src.calib import court_wedge
from src.track import track_ball
from src.tracknet import load_predictions
import validate_absolute_ranking as base

GAP = 3.0
ARMS = {
    "R0": dict(band=0, min_cross=6, seg=None),
    "E1": dict(band=30, min_cross=4, seg=None),
    "E2": dict(band=15, min_cross=4, seg=None),
    "S1": dict(band=0, min_cross=6, seg=(8, 60.0)),
    "S2": dict(band=30, min_cross=4, seg=(8, 60.0)),
}
EXC = {"pb_draft_cup": ("cache/pb_draft_cup_predictions_k14.csv", "cache/arms/pb_draft_cup_yolo.csv", "calib/pb_draft_cup_30fps_calib.json"),
       "brickwall-SEMI": ("cache/brickwall_semi_predictions_k14.csv", "cache/arms/brickwall-SEMI_yolo.csv", "calib/brickwall_semi_calib.json")}


def segments(csv_path, calib, arm, yolo_path=None):
    tr = load_predictions(csv_path, 30.0)
    w = court_wedge(calib)
    frames = []
    yv = load_predictions(yolo_path, 30.0) if yolo_path else None
    for i, (_, x, y, _w, _h, c) in enumerate(tr):
        ok = x is not None and w(x, y)
        if arm == "A1":
            o = yv[i] if i < len(yv) else None
            both = ok and o is not None and o[1] is not None and ((x - o[1]) ** 2 + (y - o[2]) ** 2) ** 0.5 <= 25
            frames.append([(x, y, c if c is not None else 1.0)] if both else [])
        else:
            frames.append([(x, y, c if c is not None else 1.0)] if ok else [])
    cfg = ARMS.get(arm, dict(band=0, min_cross=4, seg=None))
    kw = {}
    if cfg["seg"]:
        kw = dict(min_seg_frames=cfg["seg"][0], min_seg_span=cfg["seg"][1])
    ys = track_ball(frames, max_jump=150, reset_after=15, **kw)
    cr = crossing_times(list(zip([i / 30.0 for i in range(len(ys))], ys)), net_y=net_line_y(calib), band=cfg["band"])
    return [{"start": s["start"], "end": s["end"]} for s in cluster_crossings(cr, gap_sec=GAP, min_crossings=cfg["min_cross"])]


def found(lab, segs):
    return any(iou(lab, s) >= 0.5 for s in segs)


def main():
    key = list(csv.DictReader(open("cache/missed_review_key.csv")))
    fresh = list(csv.DictReader(open("cache/fresh_sample_key.csv")))
    V = dict(x.split("=") for x in "301=not 302=not 303=real 304=short 305=short 306=not 307=real 308=not 309=real 310=real 311=not 312=short 313=real 314=not 315=real 316=not 317=real 318=real 319=not 320=not 321=real 322=not 323=real 324=not 325=real 326=real 327=real 328=not 329=real 330=real".split())
    res = {}
    for arm in list(ARMS) + ["A1"]:
        r = {}
        # MISSED
        got = 0
        for k in key:
            kp, yp, cp = EXC[k["excerpt"]]
            calib = json.load(open(cp))
            if arm == "A1":
                segs = segments(kp, calib, arm, yp)
            else:
                segs = segments(kp, calib, arm)
            segs = [s for s in segs if s["end"] <= 600]
            got += found({"start": float(k["start"]), "end": float(k["end"])}, segs)
        r["recovered"] = got
        if arm != "A1":
            # PGC fresh clips
            cache = {}
            real_kept = nonreal_removed = 0
            for f in fresh:
                seg = f["segment"]
                if seg not in cache:
                    m = json.load(open(f"cache/fresh/{seg}.meta.json"))
                    cache[seg] = segments(f"cache/fresh/{seg}.csv", json.load(open(m["calib"])), arm)
                kept = found({"start": float(f["start"]), "end": float(f["end"])}, cache[seg])
                if V[f["clip"]] == "real":
                    real_kept += kept
                else:
                    nonreal_removed += (not kept)
            r["real_kept"], r["nonreal_removed"] = real_kept, nonreal_removed
            # DEV
            tp = npred = nlab = 0
            for name, csvp, calibp, labp, wend in base.SESSIONS:
                calib = json.load(open(calibp))
                labs = [l for l in load_labels(labp) if wend is None or l["end"] <= wend]
                segs = segments(csvp, calib, arm)
                if wend is not None:
                    segs = [s for s in segs if s["end"] <= wend]
                m = match_intervals(segs, labs)
                tp += len(m["matches"]); npred += len(segs); nlab += len(labs)
            r["dev_p"], r["dev_r"] = tp / max(npred, 1), tp / max(nlab, 1)
        res[arm] = r
    print(f"{'arm':4s} {'MISSED recovered /18':>21s} {'PGC real kept /15':>18s} {'PGC non-rally removed /15':>26s} {'DEV precision':>14s} {'DEV recall':>11s}")
    for arm, r in res.items():
        if arm == "A1":
            print(f"{arm:4s} {r['recovered']:21d} {'-':>18s} {'-':>26s} {'-':>14s} {'-':>11s}   (brickwall excerpts only; not gated)")
        else:
            print(f"{arm:4s} {r['recovered']:21d} {r['real_kept']:18d} {r['nonreal_removed']:26d} {r['dev_p']:14.1%} {r['dev_r']:11.1%}")
    b = res["R0"]
    print()
    for arm in ("E1", "E2", "S1", "S2"):
        r = res[arm]
        ok = r["recovered"] >= 6 and r["real_kept"] >= 14 and r["dev_r"] >= b["dev_r"] - 0.02 and r["dev_p"] >= b["dev_p"] - 0.03
        print(f"{arm}: {'HELPS' if ok else 'does not help (bar)'}")


if __name__ == "__main__":
    main()
