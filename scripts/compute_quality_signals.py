"""Precompute per-rally candidate signals for the highlight-worthy question
(PIC-7/PIC-45), on dev sessions only (IMG_7743 is locked eval, LABELING.md).

Every signal (duration, crossing_count, motion_mean/max, kitchen_mean/
kitchen_both_up_frac) is computed from the DETECTOR's own proposed segment
for a rally -- shipped config (court_wedge, gap_sec=3.0, min_crossings=6),
matched to the hand-graded label at IoU>=0.5 (TECH_SPEC's scoring threshold)
-- never from the hand label's own start/end. At inference time on new
footage there is no hand label to window against, only whatever segment the
detector itself proposes; using the label's boundary as a "signal" would be
information the deployed pipeline will never actually have.

A rally the detector didn't propose anything for (IoU<0.5, or missed
entirely) has no detector segment to compute signals from and is dropped
from the signal set -- reported separately, by grade, since PIC-7 already
flagged that the detector may find grade-1 (highlight) rallies less often
than grade-2, and dropping silently would hide exactly that.

Output: cache/quality_signals.json, read by quality_dashboard.py. Expensive
(YOLO person detection per matched segment) -- re-run only when new sessions
are labelled/graded or the shipped detector config changes. Regenerable; not
committed (see CLAUDE.md).
"""
import json
import statistics
import sys

import cv2
from ultralytics import YOLO

from eval.harness import iou
from src.ball import net_line_y, crossing_times, cluster_crossings
from src.calib import court_wedge
from src.players import load_calibration, foot_point, to_court, on_court
from src.events import motion_series, kitchen_series
from src.track import track_ball
from src.tracknet import load_predictions

SESSIONS = [
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

FPS = 30.0
GAP_SEC = 3.0
MIN_CROSSINGS = 6
IOU_THRESHOLD = 0.5
OUT_PATH = "cache/quality_signals.json"


def detector_segments(csv_path, calib, fps=FPS):
    """The exact shipped chain (src/cut.py's default as of today's fix):
    load predictions -> court_wedge gate -> track_ball -> crossing_times ->
    cluster_crossings. Returns [{start, end, crossings}, ...]."""
    track = load_predictions(csv_path, fps)
    times = [t for t, *_ in track]
    in_court = court_wedge(calib)
    frames = [[(x, y, conf if conf is not None else 1.0)] if in_court(x, y) else []
              for _, x, y, w, h, conf in track]
    ys = track_ball(frames, max_jump=150, reset_after=15)
    tracked = list(zip(times, ys))
    net_y = net_line_y(calib)
    times_crossed = crossing_times(tracked, net_y=net_y, band=0.0)
    segments = cluster_crossings(times_crossed, gap_sec=GAP_SEC, min_crossings=MIN_CROSSINGS)
    return segments, net_y


def best_match(label, segments):
    scored = [(iou(label, s), s) for s in segments]
    scored.sort(key=lambda p: p[0], reverse=True)
    if scored and scored[0][0] >= IOU_THRESHOLD:
        return scored[0][1]
    return None


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


def main():
    model = YOLO("yolov8n.pt")
    rows = []
    match_stats = {}   # session -> {1: [matched, total], 2: [matched, total]}

    for name, video, csv_path, calib_path, labels_path in SESSIONS:
        with open(calib_path) as f:
            calib = json.load(f)
        homography = load_calibration(calib_path)
        segments, net_y = detector_segments(csv_path, calib)
        rallies = [json.loads(l) for l in open(labels_path) if l.strip()]
        rallies = [r for r in rallies if r.get("quality") in (1, 2)]

        print(f"{name}: {len(rallies)} graded rallies, net_y={net_y:.1f}, "
              f"{len(segments)} detector segments (shipped config)", file=sys.stderr)

        stats = {1: [0, 0], 2: [0, 0]}
        for r in rallies:
            grade = r["quality"]
            stats[grade][1] += 1
            seg = best_match(r, segments)
            if seg is None:
                print(f"  rally {r.get('rally_id')} (grade={grade}): "
                      f"NO detector match at IoU>={IOU_THRESHOLD} -- dropped", file=sys.stderr)
                continue
            stats[grade][0] += 1

            start, end = seg["start"], seg["end"]
            tracks = windowed_court_positions(model, video, homography, start, end)
            ms = motion_series(tracks)
            ks = kitchen_series(tracks)
            rows.append({
                "session": name, "rally_id": r.get("rally_id"), "grade": grade,
                "duration": end - start, "crossing_count": seg["crossings"],
                "motion_mean": statistics.mean(m for _, m in ms) if ms else 0.0,
                "motion_max": max((m for _, m in ms), default=0.0),
                "kitchen_mean": statistics.mean(n for _, n in ks) if ks else 0.0,
                "kitchen_both_up_frac": (sum(1 for _, n in ks if n >= 2) / len(ks)) if ks else 0.0,
            })
            print(f"  rally {r.get('rally_id')} (grade={grade}): matched detector segment "
                  f"[{start:.1f},{end:.1f}] crossings={seg['crossings']}", file=sys.stderr)

        match_stats[name] = {
            "grade1_match_rate": f"{stats[1][0]}/{stats[1][1]}",
            "grade2_match_rate": f"{stats[2][0]}/{stats[2][1]}",
        }

    print("\n=== detector match rate by grade (does the detector find highlights less often?) ===",
          file=sys.stderr)
    for name, s in match_stats.items():
        print(f"{name}: grade1={s['grade1_match_rate']}  grade2={s['grade2_match_rate']}",
              file=sys.stderr)

    with open(OUT_PATH, "w") as f:
        json.dump(rows, f, indent=2)
    print(f"\nwrote {len(rows)} rows (detector-matched only) -> {OUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
