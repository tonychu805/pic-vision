"""Re-derive court_wedge's cap_court_heights/spread against dev only
(PIC-43's actual remaining scope, per Linear -- margin_px was a separate,
adjacent question, already closed 2026-08-20). Same discipline as the
min_crossings and margin_px re-derivations: grid sweep, score dev only at
IoU>=0.5, zero-regression check against the shipped baseline
(cap_court_heights=0.7, spread=0.5 -- court_wedge's own function defaults,
never explicitly chosen). margin_px held at its confirmed value (160).
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
MARGIN_PX = 160.0
SHIPPED_CAP = 0.7
SHIPPED_SPREAD = 0.5
CAP_GRID = [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, None]
SPREAD_GRID = [0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0]
TOLERANCE = 0.005


def score(csv_path, calib_path, labels_path, cap, spread):
    with open(calib_path) as f:
        calib = json.load(f)
    track = load_predictions(csv_path, FPS)
    times = [t for t, *_ in track]
    in_court = court_wedge(calib, margin_px=MARGIN_PX, cap_court_heights=cap, spread=spread)
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


def cap_label(c):
    return "None" if c is None else f"{c:.1f}"


def main():
    results = {}
    for cap in CAP_GRID:
        for spread in SPREAD_GRID:
            key = (cap, spread)
            results[key] = {}
            for name, csv_path, calib_path, labels_path in DEV_SESSIONS:
                p, r = score(csv_path, calib_path, labels_path, cap, spread)
                results[key][name] = (p, r)

    baseline = results[(SHIPPED_CAP, SHIPPED_SPREAD)]

    rows = []
    for (cap, spread), row in results.items():
        f1s = [f1(*row[name]) for name, *_ in DEV_SESSIONS]
        avg = statistics.mean(f1s)
        regressions = []
        for name, *_ in DEV_SESSIONS:
            p, r = row[name]
            bp, br = baseline[name]
            if p < bp - TOLERANCE or r < br - TOLERANCE:
                regressions.append(name)
        rows.append((cap, spread, row, avg, regressions))

    rows.sort(key=lambda r: r[3], reverse=True)

    print(f"{'cap':>5} {'spread':>7} " + " ".join(f"{name:>22}" for name, *_ in DEV_SESSIONS)
          + f"{'avg F1':>9}  zero-regression?")
    for cap, spread, row, avg, regressions in rows[:15]:
        cells = " ".join(f"{row[name][0]:.2f}/{row[name][1]:.2f}".rjust(22) for name, *_ in DEV_SESSIONS)
        marker = "  <- shipped" if (cap, spread) == (SHIPPED_CAP, SHIPPED_SPREAD) else ""
        status = "yes" if not regressions else "no: " + ",".join(regressions)
        print(f"{cap_label(cap):>5} {spread:>7.1f} {cells} {avg:>9.3f}  {status}{marker}")

    print(f"\n(top 15 of {len(rows)} combinations by avg F1; shipped = cap=0.7, spread=0.5)")

    zero_reg = [(c, s, avg) for c, s, _, avg, regs in rows if not regs]
    print(f"\n{len(zero_reg)} combinations hold with zero regression vs shipped.")
    if zero_reg:
        best = max(zero_reg, key=lambda t: t[2])
        print(f"best zero-regression avg F1: cap={cap_label(best[0])}, spread={best[1]:.1f} -> {best[2]:.3f} "
              f"(shipped: {statistics.mean([f1(*baseline[n]) for n, *_ in DEV_SESSIONS]):.3f})")


if __name__ == "__main__":
    main()
