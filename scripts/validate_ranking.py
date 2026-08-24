"""Validate src/select.py's rank_segments (ADR-063) against real quality:1/
quality:2 hand grades on the four videos that have them.

ADR-063 explicitly flagged this as not yet done -- the ranking formula was
tuned by live playback review of one reel on one video, a weaker form of
evidence than how duration/crossing_rate/top-5-velocity were validated as
quality signals (EXPERIMENTS.md, 2026-08-23 "selection signals" thread).
This closes that gap.

Method: run the shipped detector chain per video, match each candidate to a
graded label at IoU>=0.5 (never window against the label's own boundary --
matches compute_quality_signals.py's existing convention), compute
rank_segments' three signals + combined score for each matched candidate,
compare quality:1 vs quality:2.
"""
import json
import statistics
import sys

sys.path.insert(0, ".")

from eval.harness import iou
from src.tracknet import load_predictions
from src.calib import court_wedge
from src.track import track_ball
from src.ball import net_line_y, crossing_times, cluster_crossings
from src.select import frame_speeds, spike_threshold, rank_segments

FPS = 30.0
GAP_SEC = 3.0
MIN_CROSSINGS = 6
IOU_THRESHOLD = 0.5

SESSIONS = [
    ("brickwall_30fps", "videos/brickwall_30fps.mp4",
     "cache/brickwall_30fps_predictions_k14.csv",
     "calib/brickwall_30fps_calib.json", "eval/labels/brickwall_30fps.jsonl", None),
    ("pb_draft_cup", "videos/pb_draft_cup_30fps.mp4",
     "cache/pb_draft_cup_predictions_k14.csv",
     "calib/pb_draft_cup_30fps_calib.json", "eval/labels/pb_draft_cup_30fps.jsonl", None),
    ("IMG_7744", "videos/IMG_7744_fixed.mp4",
     "cache/IMG_7744_predictions_k14.csv",
     "calib/IMG_7744_calib.json", "eval/labels/IMG_7744.jsonl", None),
    ("brickwall-SEMI", "videos/brickwall_semi_30fps.mp4",
     "cache/brickwall_semi_predictions_k14.csv",
     "calib/brickwall_semi_calib.json", "eval/labels/brickwall-SEMI.jsonl", 900.0),
]


def best_match(label, segments):
    scored = [(iou(label, s), s) for s in segments]
    scored.sort(key=lambda p: p[0], reverse=True)
    if scored and scored[0][0] >= IOU_THRESHOLD:
        return scored[0][1]
    return None


def main():
    all_rows = []
    for name, video, csv_path, calib_path, labels_path, window_end in SESSIONS:
        with open(calib_path) as f:
            calib = json.load(f)
        in_court = court_wedge(calib)
        net_y = net_line_y(calib)

        track = load_predictions(csv_path, FPS)
        times = [t for t, *_ in track]
        frames = [[(x, y, conf if conf is not None else 1.0)] if in_court(x, y) else []
                  for _, x, y, w, h, conf in track]
        ys = track_ball(frames, max_jump=150, reset_after=15)
        tracked = list(zip(times, ys))
        times_crossed = crossing_times(tracked, net_y=net_y, band=0.0)
        segments = cluster_crossings(times_crossed, gap_sec=GAP_SEC, min_crossings=MIN_CROSSINGS)

        raw_points = sorted([(t, x, y) for t, x, y, w, h, c in track if in_court(x, y)],
                             key=lambda p: p[0])
        speeds = frame_speeds(raw_points)
        threshold = spike_threshold(speeds, percentile=90)

        ranked = rank_segments(segments, times_crossed, speeds, threshold)
        ranked_by_key = {(round(r["start"], 1), round(r["end"], 1)): r for r in ranked}

        rallies = [json.loads(l) for l in open(labels_path) if l.strip()]
        rallies = [r for r in rallies if r.get("quality") in (1, 2)]
        if window_end is not None:
            rallies = [r for r in rallies if r["end"] <= window_end]

        n_matched = {1: 0, 2: 0}
        n_total = {1: 0, 2: 0}
        for r in rallies:
            grade = r["quality"]
            n_total[grade] += 1
            seg = best_match(r, segments)
            if seg is None:
                continue
            key = (round(seg["start"], 1), round(seg["end"], 1))
            ranked_seg = ranked_by_key.get(key)
            if ranked_seg is None:
                continue
            n_matched[grade] += 1
            all_rows.append({
                "session": name, "grade": grade,
                "duration": ranked_seg["duration"],
                "peak_crossing_rate": ranked_seg["peak_crossing_rate"],
                "n_spikes": ranked_seg["n_spikes"],
                "score": ranked_seg["score"],
            })

        print(f"{name}: quality:1 matched {n_matched[1]}/{n_total[1]}, "
              f"quality:2 matched {n_matched[2]}/{n_total[2]}", file=sys.stderr)

    print(f"\n{len(all_rows)} matched rallies total across 4 videos\n")

    for metric in ["duration", "peak_crossing_rate", "n_spikes", "score"]:
        print(f"=== {metric} ===")
        for name, *_ in SESSIONS:
            g1 = [r[metric] for r in all_rows if r["session"] == name and r["grade"] == 1]
            g2 = [r[metric] for r in all_rows if r["session"] == name and r["grade"] == 2]
            if not g1 or not g2:
                print(f"  {name}: insufficient data (n1={len(g1)}, n2={len(g2)})")
                continue
            m1, m2 = statistics.mean(g1), statistics.mean(g2)
            direction = "quality:1 higher" if m1 > m2 else "quality:2 higher"
            print(f"  {name:20s} q1(n={len(g1):2d}) mean={m1:8.3f}  "
                  f"q2(n={len(g2):2d}) mean={m2:8.3f}  {direction}")
        allg1 = [r[metric] for r in all_rows if r["grade"] == 1]
        allg2 = [r[metric] for r in all_rows if r["grade"] == 2]
        print(f"  {'POOLED':20s} q1(n={len(allg1):2d}) mean={statistics.mean(allg1):8.3f}  "
              f"q2(n={len(allg2):2d}) mean={statistics.mean(allg2):8.3f}")
        print()


if __name__ == "__main__":
    main()
