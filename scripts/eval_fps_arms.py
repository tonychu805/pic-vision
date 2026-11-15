"""60 fps vs 30 fps on one recording (PIC-226). Does a higher frame rate let k14 see and
track the ball better? SwingVision's founder says bounce is not visible without 60 fps
(public interview); our venue cameras and all our footage are 30 fps.

Recording: brickwall (YouTube tournament stream), 1280 x 720. `brickwall_pro_series_finals.mp4`
is 59.94 fps; `brickwall_30fps.mp4` is the same recording at 30 fps (same duration, near-zero
pixel difference). First 900 s; labels with end <= 900 s (30 of 49), eval/labels/brickwall_30fps.jsonl.
Arms: 60fps = k14 on every frame; 30fps_src = k14 on every second frame of the same 60 fps
file (exactly 30 fps from the same encode: the control); 30fps_shipped = the existing
cached k14 run on the 30 fps file, for reference only.
Downstream is frame-rate aware (ADR-086): max_jump = 4500 px/s / fps, reset_after = 0.5 s,
gap_sec 3.0, min_crossings 6, court_wedge gate, IoU >= 0.5 matching.

Measures: tracked = share of frames inside labelled rallies with a tracker-confirmed position;
blind = median over labelled rallies of the longest stretch (seconds) without one; rally
precision and recall, pooled over the 30 labels.
BAR, fixed before running: 60 fps HELPS only if, against 30fps_src, tracked rises by >= 10
points AND precision >= control - 0.03 AND recall >= control - 0.03 AND at least one of
precision / recall rises by >= 0.05 AND the median longest blind stretch does not get longer.
One recording, 30 labels: a pass is a lead for a wider test, and says nothing yet about
venue cameras.
Run: .venv/bin/python scripts/eval_fps_arms.py
"""
import json, sys, os
sys.path.insert(0, ".")
import numpy as np
from eval.harness import match_intervals, load_labels
from src.ball import crossing_times, cluster_crossings, net_line_y
from src.calib import court_wedge
from src.track import track_ball
from src.tracknet import load_predictions

WIN = 900.0
CALIB = "calib/brickwall_30fps_calib.json"
LABELS = "eval/labels/brickwall_30fps.jsonl"
ARMS = [("30fps_shipped", "cache/brickwall_30fps_predictions_k14.csv", 30.0),
        ("30fps_src", "cache/arms/bw_stride2.csv", 59.94 / 2),
        ("60fps", "cache/arms/bw_stride1.csv", 59.94)]


def run_arm(path, fps, calib, labels):
    tr = load_predictions(path, fps)
    w = court_wedge(calib)
    times = [t for t, *_ in tr]
    frames = [[(x, y, c if c is not None else 1.0)] if (x is not None and w(x, y)) else [] for _, x, y, _w, _h, c in tr]
    ys = track_ball(frames, max_jump=int(round(4500.0 / fps)), reset_after=int(round(0.5 * fps)))
    crossed = crossing_times(list(zip(times, ys)), net_y=net_line_y(calib), band=0.0)
    segs = [s for s in cluster_crossings(crossed, gap_sec=3.0, min_crossings=6) if s["end"] <= WIN]
    preds = [{"start": s["start"], "end": s["end"]} for s in segs]
    m = len(match_intervals(preds, labels)["matches"])
    trk = np.array([y is not None for y in ys])
    hit = tot = 0
    blinds = []
    for r in labels:
        a, b = int(r["start"] * fps), min(len(trk) - 1, int(r["end"] * fps))
        win = trk[a:b + 1]
        hit += int(win.sum()); tot += len(win)
        run = best = 0
        for v in win:
            run = 0 if v else run + 1
            best = max(best, run)
        blinds.append(best / fps)
    return {"tracked": hit / tot, "blind": float(np.median(blinds)), "pred": len(preds), "matched": m, "labels": len(labels)}


def main():
    calib = json.load(open(CALIB))
    labels = [r for r in load_labels(LABELS) if r["end"] <= WIN]
    out = {}
    print(f"{'arm':14s} {'fps':>6s} {'tracked':>8s} {'blind s':>8s} {'pred':>5s} {'matched':>8s} {'precision':>10s} {'recall':>8s}")
    for name, path, fps in ARMS:
        if not os.path.exists(path):
            continue
        n_rows = sum(1 for _ in open(path)) - 1
        if n_rows < 0.98 * WIN * fps:
            print(f"{name:14s} SKIPPED: {n_rows} rows of {int(WIN * fps)} (file incomplete)")
            continue
        r = run_arm(path, fps, calib, labels); out[name] = r
        print(f"{name:14s} {fps:6.1f} {r['tracked']:8.0%} {r['blind']:8.2f} {r['pred']:5d} {r['matched']:8d} "
              f"{r['matched'] / max(r['pred'], 1):10.0%} {r['matched'] / r['labels']:8.0%}")
    if "60fps" in out and "30fps_src" in out:
        c, s = out["30fps_src"], out["60fps"]
        cp, cr = c["matched"] / max(c["pred"], 1), c["matched"] / c["labels"]
        sp, sr = s["matched"] / max(s["pred"], 1), s["matched"] / s["labels"]
        ok = (s["tracked"] - c["tracked"] >= 0.10 and sp >= cp - 0.03 and sr >= cr - 0.03
              and (sp - cp >= 0.05 or sr - cr >= 0.05) and s["blind"] <= c["blind"])
        print(f"\n60fps vs control: tracked {s['tracked'] - c['tracked']:+.0%}, precision {sp - cp:+.0%}, "
              f"recall {sr - cr:+.0%}, blind {s['blind'] - c['blind']:+.2f}s -> {'HELPS' if ok else 'does not help (bar)'}")


if __name__ == "__main__":
    main()
