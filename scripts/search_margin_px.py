"""Re-derive court_wedge's margin_px against dev only (PIC-43-style), same
discipline as the 2026-08-19 min_crossings re-derivation: sweep a grid,
score against dev videos (brickwall, pb_draft_cup, IMG_7744) at IoU>=0.5,
pick the value that improves or holds on every dev video with zero
regression against the current shipped default (margin_px=160, inherited
unexamined when court_wedge was wired into src/cut.py, EXPERIMENTS.md
2026-08-20). eval (IMG_7743) is untouched during selection -- only checked
once, at the end, as a held-out confirmation.
"""
import json
import statistics

from eval.harness import load_labels, match_intervals
from src.ball import net_line_y, crossing_times, cluster_crossings
from src.calib import court_wedge
from src.track import track_ball
from src.tracknet import load_predictions

DEV_SESSIONS = [
    ("brickwall_30fps", "cache/brickwall_30fps_predictions_k14.csv",
     "calib/brickwall_30fps_calib.json", "eval/labels/brickwall_30fps.jsonl"),
    ("pb_draft_cup_30fps", "cache/pb_draft_cup_predictions_k14.csv",
     "calib/pb_draft_cup_30fps_calib.json", "eval/labels/pb_draft_cup_30fps.jsonl"),
    ("IMG_7744", "cache/IMG_7744_predictions_k14.csv",
     "calib/IMG_7744_calib.json", "eval/labels/IMG_7744.jsonl"),
]

FPS = 30.0
GAP_SEC = 3.0
MIN_CROSSINGS = 6
SHIPPED_MARGIN = 160.0
MARGIN_GRID = [30.0, 50.0, 80.0, 110.0, 140.0, 160.0, 200.0, 250.0]
TOLERANCE = 0.005


def score(csv_path, calib_path, labels_path, margin_px):
    with open(calib_path) as f:
        calib = json.load(f)
    track = load_predictions(csv_path, FPS)
    times = [t for t, *_ in track]
    in_court = court_wedge(calib, margin_px=margin_px)
    frames = [[(x, y, conf if conf is not None else 1.0)] if in_court(x, y) else []
              for _, x, y, w, h, conf in track]
    ys = track_ball(frames, max_jump=150, reset_after=15)
    tracked = list(zip(times, ys))
    net_y = net_line_y(calib)
    times_crossed = crossing_times(tracked, net_y=net_y, band=0.0)
    segments = cluster_crossings(times_crossed, gap_sec=GAP_SEC, min_crossings=MIN_CROSSINGS)

    gts = load_labels(labels_path)
    preds = [{"start": s["start"], "end": s["end"]} for s in segments]
    m = match_intervals(preds, gts)
    precision = len(m["matches"]) / len(preds) if preds else 0.0
    recall = len(m["matches"]) / len(gts) if gts else 0.0
    return precision, recall


def f1(p, r):
    return 2 * p * r / (p + r) if (p + r) else 0.0


def main():
    results = {}   # margin -> {session: (p, r)}
    for margin in MARGIN_GRID:
        results[margin] = {}
        for name, csv_path, calib_path, labels_path in DEV_SESSIONS:
            p, r = score(csv_path, calib_path, labels_path, margin)
            results[margin][name] = (p, r)

    print(f"{'margin':>7} " + " ".join(f"{name:>22}" for name, *_ in DEV_SESSIONS) + f"{'avg F1':>9}")
    for margin in MARGIN_GRID:
        row = results[margin]
        f1s = [f1(*row[name]) for name, *_ in DEV_SESSIONS]
        cells = " ".join(f"{row[name][0]:.2f}/{row[name][1]:.2f}".rjust(22) for name, *_ in DEV_SESSIONS)
        marker = "  <- shipped" if margin == SHIPPED_MARGIN else ""
        print(f"{margin:>7.0f} {cells} {statistics.mean(f1s):>9.3f}{marker}")

    baseline = results[SHIPPED_MARGIN]
    print(f"\nzero-regression check vs shipped (margin={SHIPPED_MARGIN:.0f}), tolerance ±{TOLERANCE}:")
    for margin in MARGIN_GRID:
        if margin == SHIPPED_MARGIN:
            continue
        row = results[margin]
        regressions = []
        for name, *_ in DEV_SESSIONS:
            p, r = row[name]
            bp, br = baseline[name]
            if p < bp - TOLERANCE or r < br - TOLERANCE:
                regressions.append(f"{name} (p {bp:.3f}->{p:.3f}, r {br:.3f}->{r:.3f})")
        status = "REGRESSES: " + ", ".join(regressions) if regressions else "no regression anywhere"
        print(f"  margin={margin:>5.0f}: {status}")


if __name__ == "__main__":
    main()
