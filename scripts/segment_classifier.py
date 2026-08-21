"""Segment classifier (exploratory, direction-setting follow-up 2026-08-20):
learn TP/FP separation over per-candidate-segment features, compared against
the shipped min_crossings=6 heuristic.

Candidates are generated at min_crossings=1 (every crossing cluster, not just
ones that already clear the shipped gate) from the same chain as production
(court_wedge -> track_ball -> crossing_times -> cluster_crossings), then
labelled TP/FP by the exact same matching eval/harness.py uses for the
project's own precision/recall numbers (greedy one-to-one, IoU>=0.5).

Dev-only training/model-selection (brickwall_30fps, pb_draft_cup_30fps,
IMG_7744) via leave-one-video-out CV -- IMG_7743 is eval, locked (ADR-052,
sessions.jsonl) and is scored exactly once at the very end, after the model
is finalized, purely to report a number. Never used to pick features,
hyperparameters, or a decision threshold.
"""
import json
import os
import statistics
import sys

import cv2
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score
from ultralytics import YOLO

from eval.harness import match_intervals
from src.ball import net_line_y, crossing_times, cluster_crossings
from src.calib import court_wedge
from src.players import load_calibration, foot_point, to_court, on_court
from src.events import motion_series, kitchen_series
from src.track import track_ball
from src.tracknet import load_predictions

FPS = 30.0
GAP_SEC = 3.0
SHIPPED_MIN_CROSSINGS = 6
IOU_THRESHOLD = 0.5

DEV_SESSIONS = [
    ("brickwall_30fps", "videos/brickwall_30fps.mp4",
     "cache/brickwall_30fps_predictions_k14.csv",
     "calib/brickwall_30fps_calib.json", "eval/labels/brickwall_30fps.jsonl"),
    ("pb_draft_cup_30fps", "videos/pb_draft_cup_30fps.mp4",
     "cache/pb_draft_cup_predictions_k14.csv",
     "calib/pb_draft_cup_30fps_calib.json", "eval/labels/pb_draft_cup_30fps.jsonl"),
    ("IMG_7744", "videos/IMG_7744_fixed.mp4",
     "cache/IMG_7744_predictions_k14.csv",
     "calib/IMG_7744_calib.json", "eval/labels/IMG_7744.jsonl"),
]

FEATURES = ["duration", "crossing_count", "crossing_rate",
            "motion_mean", "motion_max", "kitchen_mean", "kitchen_both_up_frac"]


def gen_candidates(csv_path, calib_path, time_lo=None, time_hi=None, fps=FPS):
    """All crossing clusters at min_crossings=1 -- the full candidate pool
    before the shipped gate. Optionally restricted to [time_lo, time_hi)."""
    with open(calib_path) as f:
        calib = json.load(f)
    track = load_predictions(csv_path, fps)
    if time_lo is not None or time_hi is not None:
        lo = time_lo if time_lo is not None else -1e18
        hi = time_hi if time_hi is not None else 1e18
        track = [row for row in track if lo <= row[0] < hi]
    times = [t for t, *_ in track]
    in_court = court_wedge(calib)
    frames = [[(x, y, conf if conf is not None else 1.0)] if in_court(x, y) else []
              for _, x, y, w, h, conf in track]
    ys = track_ball(frames, max_jump=150, reset_after=15)
    tracked = list(zip(times, ys))
    net_y = net_line_y(calib)
    times_crossed = crossing_times(tracked, net_y=net_y, band=0.0)
    segments = cluster_crossings(times_crossed, gap_sec=GAP_SEC, min_crossings=1)
    return segments, calib


def windowed_court_positions(model, video_path, homography, start, end, sample_fps=5.0):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(fps / sample_fps))
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    out, idx = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if t > end:
            break
        if idx % step == 0:
            res = model(frame, imgsz=1280, conf=0.3, classes=[0], verbose=False)[0]
            boxes = [tuple(map(float, b)) for b in res.boxes.xyxy.cpu().numpy()]
            court = to_court([foot_point(b) for b in boxes], homography) if boxes else []
            out.append((t, [p for p in court if on_court(p)]))
        idx += 1
    cap.release()
    return out


def add_features(segments, video_path, calib_path, yolo_model, label_offset=0.0):
    homography = load_calibration(calib_path)
    rows = []
    for seg in segments:
        start, end = seg["start"], seg["end"]
        dur = end - start
        tracks = windowed_court_positions(yolo_model, video_path, homography, start, end)
        ms = motion_series(tracks)
        ks = kitchen_series(tracks)
        rows.append({
            "start": start + label_offset, "end": end + label_offset,
            "duration": dur,
            "crossing_count": seg["crossings"],
            "crossing_rate": seg["crossings"] / dur if dur > 0 else 0.0,
            "motion_mean": statistics.mean(m for _, m in ms) if ms else 0.0,
            "motion_max": max((m for _, m in ms), default=0.0),
            "kitchen_mean": statistics.mean(n for _, n in ks) if ks else 0.0,
            "kitchen_both_up_frac": (sum(1 for _, n in ks if n >= 2) / len(ks)) if ks else 0.0,
        })
    return rows


def label_tp_fp(cand_rows, labels):
    """Greedy one-to-one IoU>=0.5 match, same rule eval/harness.py uses for
    the project's own precision/recall. Sets cand['y'] = 1 (TP) / 0 (FP)."""
    preds = [{"start": r["start"], "end": r["end"]} for r in cand_rows]
    m = match_intervals(preds, labels, threshold=IOU_THRESHOLD)
    matched_pred_idx = {pi for pi, gi, s in m["matches"]}
    for i, r in enumerate(cand_rows):
        r["y"] = 1 if i in matched_pred_idx else 0
    return len(m["matches"]), len(labels), len(m["false_pos"])


def score_predicted(pred_rows, labels):
    preds = [{"start": r["start"], "end": r["end"]} for r in pred_rows]
    m = match_intervals(preds, labels, threshold=IOU_THRESHOLD)
    n_matched, n_pred, n_labeled = len(m["matches"]), len(preds), len(labels)
    precision = n_matched / n_pred if n_pred else 0.0
    recall = n_matched / n_labeled if n_labeled else 0.0
    return precision, recall, n_pred, n_matched, n_labeled


def make_models():
    """Two candidate models: a small linear one (few features, little data --
    likely to generalize) and a boosted-tree one (can pick up interactions,
    more prone to overfitting 322 rows). Both dev-only, compared honestly."""
    return {
        "logreg": make_pipeline(StandardScaler(),
                                 LogisticRegression(class_weight="balanced", max_iter=1000)),
        "hgb": HistGradientBoostingClassifier(max_depth=3, min_samples_leaf=10,
                                               class_weight="balanced"),
    }


def leave_one_video_out_eval(dev_data, n_true_labels):
    """Train on 2 dev videos, evaluate on the 3rd held out. Compares each
    classifier (default 0.5 threshold) against the shipped min_crossings>=6
    heuristic applied to the SAME candidate pool -- the fair baseline for this
    experiment, per the module docstring. Recall denominator is the real
    labeled-rally count (n_true_labels), not the count of matched candidates,
    since not every real label necessarily has a matching candidate."""
    names = list(dev_data.keys())
    results = {}
    for held_out in names:
        train_rows = [r for n in names if n != held_out for r in dev_data[n]]
        test_rows = dev_data[held_out]

        X_train = np.array([[r[f] for f in FEATURES] for r in train_rows])
        y_train = np.array([r["y"] for r in train_rows])
        X_test = np.array([[r[f] for f in FEATURES] for r in test_rows])
        y_test = np.array([r["y"] for r in test_rows])
        n_labels = n_true_labels[held_out]

        def prec_rec(keep_mask):
            n_matched = int(sum(1 for k, y in zip(keep_mask, y_test) if k and y))
            n_kept = int(sum(keep_mask))
            precision = n_matched / n_kept if n_kept else 0.0
            recall = n_matched / n_labels if n_labels else 0.0
            return precision, recall, n_kept, n_matched

        heur_p, heur_r, heur_kept, heur_matched = prec_rec(
            [r["crossing_count"] >= SHIPPED_MIN_CROSSINGS for r in test_rows])
        held_result = {"heuristic": {"precision": heur_p, "recall": heur_r,
                                      "kept": heur_kept, "matched": heur_matched,
                                      "n_labels": n_labels}}

        for model_name, model in make_models().items():
            model.fit(X_train, y_train)
            proba = model.predict_proba(X_test)[:, 1]
            p, r, kept, matched = prec_rec(proba >= 0.5)
            ap = average_precision_score(y_test, proba) if len(set(y_test)) > 1 else float("nan")
            held_result[model_name] = {"precision": p, "recall": r, "kept": kept,
                                        "matched": matched, "n_labels": n_labels,
                                        "avg_precision": ap}
        results[held_out] = held_result
    return results


def print_lovo_table(results):
    model_names = ["heuristic"] + [k for k in next(iter(results.values())) if k != "heuristic"]
    for held_out, held_result in results.items():
        print(f"\n-- held out: {held_out} --")
        for m in model_names:
            r = held_result[m]
            ap = f", AP={r['avg_precision']:.3f}" if "avg_precision" in r else ""
            print(f"  {m:10s} precision={r['precision']:.3f} recall={r['recall']:.3f} "
                  f"({r['matched']}/{r['kept']} kept, {r['n_labels']} labels){ap}")


def main():
    cache_path = "cache/segment_classifier_dev_rows.json"
    if os.path.exists(cache_path):
        print(f"reusing cached features from {cache_path}", file=sys.stderr)
        with open(cache_path) as f:
            dev_data = json.load(f)
    else:
        yolo_model = YOLO("yolov8n.pt")
        dev_data = {}  # name -> list of feature rows (with 'y')
        for name, video, csv_path, calib_path, labels_path in DEV_SESSIONS:
            segments, calib = gen_candidates(csv_path, calib_path)
            labels = [json.loads(l) for l in open(labels_path) if l.strip()]
            rows = add_features(segments, video, calib_path, yolo_model)
            n_tp, n_labels, n_fp = label_tp_fp(rows, labels)
            print(f"{name}: {len(rows)} candidates (min_crossings=1), "
                  f"{n_tp} TP / {n_fp} FP, {n_labels} labels", file=sys.stderr)
            dev_data[name] = rows

        with open(cache_path, "w") as f:
            json.dump(dev_data, f, indent=2)
        print(f"wrote {cache_path}", file=sys.stderr)

    n_true_labels = {}
    for name, video, csv_path, calib_path, labels_path in DEV_SESSIONS:
        n_true_labels[name] = sum(1 for l in open(labels_path) if l.strip())

    results = leave_one_video_out_eval(dev_data, n_true_labels)
    print_lovo_table(results)

    print("\nNOTE: dev-only (leave-one-video-out across brickwall/pb_draft_cup/"
          "IMG_7744). IMG_7743 (eval) untouched -- per ADR-052 it may be scored "
          "exactly once, after a model/threshold is picked from the above, never "
          "used to pick either.", file=sys.stderr)


if __name__ == "__main__":
    main()
