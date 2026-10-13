"""Both detectors' blobs offered to the tracker (PIC-228). No GPU: reads the cached
k14 predictions and the yolo11x predictions already produced for the arm comparison.

Post hoc from the YOLO run: inside real rallies k14 alone sees 8-16% of frames, yolo11x
alone 14-18%, both (and agreeing within 25 px) 25-36%, neither about 40%. Does offering
both to the tracker turn that complementarity into better rallies?

Rule, fixed BEFORE running: per frame the candidate list is the court-gated k14 blob and
the court-gated yolo11x blob; when both exist and are within 25 px, only the k14 position
is offered (they are the same ball). Each keeps its own confidence value. Everything
downstream is identical to the base arm: track_ball(max_jump 150, reset_after 15),
crossing_times, cluster_crossings (gap 3.0, min_crossings 6), IoU >= 0.5 matching.
Same two excerpts as scripts/eval_detector_arms.py: first 600 s of pb_draft_cup_30fps
(32 labels) and brickwall-SEMI (23 labels), labels with end <= 600 s.

BAR, fixed before running (pooled over both excerpts, against the base k14 arm):
union HELPS only if recall rises by >= 0.05 AND precision does not fall by more than 0.03.
Reported alongside: yolo-only and the tracked-frame share. Two excerpts: a pass is a lead,
and it would cost running both detectors (yolo11x ran at about 7-8 fps on a shared GPU).
Run: .venv/bin/python scripts/eval_union_arm.py
"""
import json, sys
sys.path.insert(0, ".")
import numpy as np
from eval.harness import match_intervals, load_labels
from src.ball import crossing_times, cluster_crossings, net_line_y
from src.calib import court_wedge
from src.track import track_ball
from src.tracknet import load_predictions

WIN, AGREE_PX = 600.0, 25.0
EXC = [("pb_draft_cup", "cache/pb_draft_cup_predictions_k14.csv", "cache/arms/pb_draft_cup_yolo.csv", "calib/pb_draft_cup_30fps_calib.json", "eval/labels/pb_draft_cup_30fps.jsonl"),
       ("brickwall-SEMI", "cache/brickwall_semi_predictions_k14.csv", "cache/arms/brickwall-SEMI_yolo.csv", "calib/brickwall_semi_calib.json", "eval/labels/brickwall-SEMI.jsonl")]


def run(mode, K, Y, calib, labels):
    w = court_wedge(calib)
    n = int(WIN * 30)
    frames, times = [], []
    for i in range(n):
        c = []
        k = K[i] if i < len(K) else None
        y = Y[i] if i < len(Y) else None
        kv = k is not None and k[1] is not None and w(k[1], k[2])
        yv = y is not None and y[1] is not None and w(y[1], y[2])
        if mode in ("k14", "union") and kv:
            c.append((k[1], k[2], k[5] if k[5] is not None else 1.0))
        if mode in ("yolo", "union") and yv:
            dup = mode == "union" and kv and ((k[1] - y[1]) ** 2 + (k[2] - y[2]) ** 2) ** 0.5 <= AGREE_PX
            if not dup:
                c.append((y[1], y[2], y[5] if y[5] is not None else 1.0))
        frames.append(c); times.append(i / 30.0)
    ys = track_ball(frames, max_jump=150, reset_after=15)
    crossed = crossing_times(list(zip(times, ys)), net_y=net_line_y(calib), band=0.0)
    segs = [s for s in cluster_crossings(crossed, gap_sec=3.0, min_crossings=6) if s["end"] <= WIN]
    preds = [{"start": s["start"], "end": s["end"]} for s in segs]
    m = len(match_intervals(preds, labels)["matches"])
    trk = np.array([v is not None for v in ys])
    hit = tot = 0
    for r in labels:
        a, b = int(r["start"] * 30), min(n - 1, int(r["end"] * 30))
        hit += int(trk[a:b + 1].sum()); tot += b - a + 1
    return {"pred": len(preds), "matched": m, "labels": len(labels), "trk_hit": hit, "trk_tot": tot}


def main():
    print(f"{'arm':6s} {'video':16s} {'tracked':>8s} {'pred':>5s} {'matched':>8s} {'precision':>10s} {'recall':>8s}")
    pooled = {}
    for mode in ("k14", "yolo", "union"):
        for name, kp, yp, cp, lp in EXC:
            calib = json.load(open(cp))
            labels = [r for r in load_labels(lp) if r["end"] <= WIN]
            r = run(mode, load_predictions(kp, 30.0), load_predictions(yp, 30.0), calib, labels)
            print(f"{mode:6s} {name:16s} {r['trk_hit'] / r['trk_tot']:8.0%} {r['pred']:5d} {r['matched']:8d} "
                  f"{r['matched'] / max(r['pred'], 1):10.0%} {r['matched'] / r['labels']:8.0%}")
            a = pooled.setdefault(mode, dict(pred=0, matched=0, labels=0, hit=0, tot=0))
            a["pred"] += r["pred"]; a["matched"] += r["matched"]; a["labels"] += r["labels"]
            a["hit"] += r["trk_hit"]; a["tot"] += r["trk_tot"]
    print()
    for mode, a in pooled.items():
        print(f"POOLED {mode:6s} tracked {a['hit'] / a['tot']:.0%}, precision {a['matched'] / a['pred']:.0%} "
              f"({a['matched']}/{a['pred']}), recall {a['matched'] / a['labels']:.0%} ({a['matched']}/{a['labels']})")
    b, u = pooled["k14"], pooled["union"]
    bp, br = b["matched"] / b["pred"], b["matched"] / b["labels"]
    up, ur = u["matched"] / u["pred"], u["matched"] / u["labels"]
    ok = ur - br >= 0.05 and up >= bp - 0.03
    print(f"\nunion vs k14: recall {ur - br:+.0%}, precision {up - bp:+.0%} -> {'HELPS' if ok else 'does not help (bar)'}")


if __name__ == "__main__":
    main()
