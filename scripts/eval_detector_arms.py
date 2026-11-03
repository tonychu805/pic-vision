"""Score detector arms on the same labelled excerpts (PIC-226 zoom test).

Question: does giving TrackNet k14 a closer view (two overlapping tiles,
scripts/infer_tile_k14.py; the crop-to-court arm was a no-op on this footage and was
stopped) make the ball visible more often and does the rally-level result hold? A modern-YOLO arm is added if its weights are on disk
(scripts/infer_yolo_ball.py).

Excerpts: first 600 s of pb_draft_cup_30fps (1080p) and brickwall-SEMI (1080p);
labels with end <= 600 s. Arms: base = cached k14 on the whole frame; tile = k14 on
two overlapping tiles of the court band. Same downstream: court_wedge gate, track_ball, crossing_times,
cluster_crossings (gap 3.0, min_crossings 6), IoU >= 0.5 matching.

Measures: (a) ball seen = share of frames inside labelled rallies with a detection
inside the court wedge; (b) rally precision and recall, pooled.

Added before any complete arm result was read: a 'tracked' column (frames inside
labelled rallies with a tracker-confirmed position), reported, not gated. (When this
was tested, an incomplete tile file that was still being written was scored once;
its numbers were an artifact and were discarded. The scorer now skips files with
fewer than 98% of the expected rows.)

BAR, fixed before running: an arm HELPS only if, pooled over both excerpts,
 ball seen rises by >= 10 points over base AND precision >= base - 0.03 AND recall
 >= base - 0.03 AND at least one of precision / recall rises by >= 0.05.
Two excerpts, one venue style: a pass is a lead for a wider test.
"""
import json, sys, os
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
from eval.harness import match_intervals, load_labels
import validate_absolute_ranking as base
from src.calib import court_wedge
from src.track import track_ball
from src.tracknet import load_predictions

WIN = 600.0
EXC = [("pb_draft_cup", "cache/pb_draft_cup_predictions_k14.csv", "calib/pb_draft_cup_30fps_calib.json", "eval/labels/pb_draft_cup_30fps.jsonl"),
       ("brickwall-SEMI", "cache/brickwall_semi_predictions_k14.csv", "calib/brickwall_semi_calib.json", "eval/labels/brickwall-SEMI.jsonl")]
ARMS = {"base": lambda name, csv: csv, "tile": lambda name, csv: f"cache/arms/{name}_tile.csv", "yolo": lambda name, csv: f"cache/arms/{name}_yolo.csv"}


def seen_fraction(csvp, calib, labels):
    """(seen_hits, tracked_hits, total_frames) inside labelled rallies. seen = a detection
    inside the court wedge; tracked = a position the tracker confirmed (stricter)."""
    tr = load_predictions(csvp, 30.0); w = court_wedge(calib)
    vis = np.array([x is not None and w(x, y) for _, x, y, *_ in tr])
    frames = [[(x, y, c if c is not None else 1.0)] if (x is not None and w(x, y)) else [] for _, x, y, _w, _h, c in tr]
    ys = track_ball(frames, max_jump=150, reset_after=15)
    trk = np.array([y is not None for y in ys])
    tot = hit = hit_t = 0
    for r in labels:
        a, b = int(r["start"] * 30), min(len(vis) - 1, int(r["end"] * 30))
        tot += b - a + 1; hit += int(vis[a:b + 1].sum()); hit_t += int(trk[a:b + 1].sum())
    return hit, hit_t, tot


def main():
    print(f"{'arm':6s} {'video':16s} {'seen %':>7s} {'tracked':>8s} {'pred':>5s} {'labels':>7s} {'matched':>8s} {'precision':>10s} {'recall':>8s}")
    pooled = {}
    for arm, path in ARMS.items():
        for name, csv, calib_p, lab_p in EXC:
            p = path(name, csv)
            if not os.path.exists(p):
                continue
            calib = json.load(open(calib_p))
            n_rows = sum(1 for _ in open(p)) - 1
            if n_rows < 0.98 * WIN * 30:
                print(f"{arm:6s} {name:16s} SKIPPED: {n_rows} rows of {int(WIN * 30)} (file incomplete)")
                continue
            labels = [r for r in load_labels(lab_p) if r["end"] <= WIN]
            segs = [s for s in base.detect(p, calib)[0] if s["end"] <= WIN]
            preds = [{"start": s["start"], "end": s["end"]} for s in segs]
            m = len(match_intervals(preds, labels)["matches"])
            h, ht, t = seen_fraction(p, calib, labels)
            print(f"{arm:6s} {name:16s} {h / t:7.0%} {ht / t:8.0%} {len(preds):5d} {len(labels):7d} {m:8d} {m / max(len(preds), 1):10.0%} {m / len(labels):8.0%}")
            a = pooled.setdefault(arm, [0, 0, 0, 0, 0, 0]); a[0] += h; a[1] += t; a[2] += m; a[3] += len(preds); a[4] += len(labels); a[5] += ht
    print()
    b = pooled["base"]; bs, bp, br = b[0] / b[1], b[2] / b[3], b[2] / b[4]
    print(f"POOLED base: seen {bs:.0%}, tracked {b[5] / b[1]:.0%}, precision {bp:.0%}, recall {br:.0%}")
    for arm in ("tile", "yolo"):
        if arm not in pooled: continue
        a = pooled[arm]; s, p, r = a[0] / a[1], a[2] / a[3], a[2] / a[4]
        ok = (s - bs >= 0.10) and p >= bp - 0.03 and r >= br - 0.03 and (p - bp >= 0.05 or r - br >= 0.05)
        print(f"POOLED {arm}: seen {s:.0%} ({s - bs:+.0%}), tracked {a[5] / a[1]:.0%} ({a[5] / a[1] - b[5] / b[1]:+.0%}, reported not gated), precision {p:.0%} ({p - bp:+.0%}), recall {r:.0%} ({r - br:+.0%})  -> {'HELPS' if ok else 'does not help (bar)'}")


if __name__ == "__main__":
    main()
