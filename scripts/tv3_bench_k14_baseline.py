"""Current k14 baseline at IoU>=0.5 against committed labels (prebump 42
labels, IMG_7744 20 labels), for a fair comparison once the TrackNetV3
zero-shot benchmark (2026-08-21) has a number to compare against.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.harness import load_labels, detection_metrics
from src.calib import court_wedge
from src.ball import net_line_y, crossing_times, cluster_crossings
from src.track import track_ball
from src.tracknet import load_predictions

FPS = 30.0
GAP_SEC = 3.0
MIN_CROSSINGS = 6


def score(csv_path, calib_path, labels_path, t_min=None, t_max=None):
    with open(calib_path) as f:
        calib = json.load(f)
    track = load_predictions(csv_path, FPS)
    if t_min is not None or t_max is not None:
        track = [row for row in track
                 if (t_min is None or row[0] >= t_min) and (t_max is None or row[0] < t_max)]
    times = [t for t, *_ in track]
    in_court = court_wedge(calib)
    frames = [[(x, y, conf if conf is not None else 1.0)] if in_court(x, y) else []
              for _, x, y, w, h, conf in track]
    ys = track_ball(frames, max_jump=150, reset_after=15)
    tracked = list(zip(times, ys))
    net_y = net_line_y(calib)
    times_crossed = crossing_times(tracked, net_y=net_y, band=0.0)
    segments = cluster_crossings(times_crossed, gap_sec=GAP_SEC, min_crossings=MIN_CROSSINGS)

    gts = load_labels(labels_path)
    preds = [{"start": s["start"], "end": s["end"]} for s in segments]
    dur = (t_max - t_min) if (t_min is not None and t_max is not None) else times[-1]
    det = detection_metrics(preds, gts, dur)
    return det, len(preds)


if __name__ == "__main__":
    det, n = score("cache/IMG_7743_predictions_k14.csv", "calib/IMG_7743_prebump_0-2900s_calib.json",
                    "eval/labels/IMG_7743_prebump_0-2900s.jsonl", t_min=0, t_max=2900)
    print("IMG_7743 prebump (k14):", n, "preds |", det)

    det2, n2 = score("cache/IMG_7744_predictions_k14.csv", "calib/IMG_7744_calib.json",
                      "eval/labels/IMG_7744.jsonl")
    print("IMG_7744 (k14):", n2, "preds |", det2)
