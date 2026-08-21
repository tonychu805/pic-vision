"""TrackNetV3 vs. k14, IoU>=0.5, on pb_draft_cup and IMG_7744 — the two
videos the 2026-08-21 brickwall result (PIC-47) still needed before it means
anything conclusively. Mirrors scripts/tv3_bench_k14_baseline.py's method.
"""
import json

from eval.harness import load_labels, detection_metrics
from src.calib import court_wedge
from src.ball import net_line_y, crossing_times, cluster_crossings
from src.track import track_ball
from src.tracknet import load_predictions

FPS = 30.0
GAP_SEC = 3.0
MIN_CROSSINGS = 6


def score(csv_path, calib_path, labels_path):
    with open(calib_path) as f:
        calib = json.load(f)
    track = load_predictions(csv_path, FPS)
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
    dur = times[-1]
    det = detection_metrics(preds, gts, dur)
    return det, len(preds)


VIDEOS = [
    ("pb_draft_cup", "calib/pb_draft_cup_30fps_calib.json", "eval/labels/pb_draft_cup_30fps.jsonl",
     "cache/pb_draft_cup_predictions_k14.csv", "/mnt/fast_scratch/tv3_work/pb_draft_cup_pred/pb_draft_cup_30fps_ball.csv"),
    ("IMG_7744", "calib/IMG_7744_calib.json", "eval/labels/IMG_7744.jsonl",
     "cache/IMG_7744_predictions_k14.csv", "/mnt/fast_scratch/tv3_work/IMG_7744_pred/IMG_7744_fixed_ball.csv"),
]

if __name__ == "__main__":
    for name, calib_path, labels_path, k14_csv, tv3_csv in VIDEOS:
        det_k14, n_k14 = score(k14_csv, calib_path, labels_path)
        det_tv3, n_tv3 = score(tv3_csv, calib_path, labels_path)
        print(f"{name}  k14: {n_k14} preds | {det_k14}")
        print(f"{name}  tv3: {n_tv3} preds | {det_tv3}")
