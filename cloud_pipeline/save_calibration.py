#!/usr/bin/env python3
"""Computes and writes a calib.json from 14 clicked points (12 court + 2
net) against a snapshot image -- the desktop client's live-camera
calibration flow. Reuses calibrate.py's homography/solve_assignment math
exactly the way webapp/app.py's browser calibration route already does
(the click-collection UI is a literal copy of webapp/templates/
calibrate.html's JS, ported into React), rather than reimplementing the
fit in JS -- per ADR-071's "invoke the existing Python as a subprocess."

Points are read as JSON from stdin: {"points": [[x, y], ...]} (14 pairs,
in POINTS then NET_PROMPTS order -- same as webapp/app.py's
calibrate_save). Frame width/height come from reading the snapshot itself
with cv2, not from the caller, so a mismatched report can't silently
produce a wrong calibration_resolution.

Usage:
    echo '{"points": [[x1,y1], ...]}' | python3 save_calibration.py \\
        --snapshot snapshot.png --out calib.json
"""
import argparse
import json
import os
import sys

import cv2

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from calibrate import POINTS, NET_PROMPTS, compute_calibration, solve_assignment


def fail(msg):
    print(json.dumps({"error": msg}))
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        fail(f"invalid points JSON on stdin: {e}")

    points = data.get("points", [])
    n_court = len(POINTS)
    n_total = n_court + len(NET_PROMPTS)
    if len(points) != n_total:
        fail(f"expected {n_total} points, got {len(points)}")

    court_points = [tuple(p) for p in points[:n_court]]
    net_points = [tuple(p) for p in points[n_court:]]

    try:
        ordered, _ = solve_assignment(court_points)
        result = compute_calibration(ordered)
    except Exception as e:
        fail(str(e))

    frame = cv2.imread(args.snapshot)
    if frame is None:
        fail(f"could not read snapshot {args.snapshot}")
    frame_h, frame_w = frame.shape[:2]

    calib = {
        "video": "live-snapshot",
        "frame_at_sec": None,
        **result,
        "net_image_points": [[float(x), float(y)] for x, y in net_points],
        "court_size_ft": [20.0, 44.0],
        "net_y_ft": 22.0,
        # See calibrate.py's identical field for why this is needed.
        "calibration_resolution": [frame_w, frame_h],
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(calib, f, indent=2)

    err_ft = result["per_point_error_ft"]
    worst = int(max(range(len(err_ft)), key=lambda k: err_ft[k]))
    print(json.dumps({
        "ok": True,
        "rmse_ft": result["reprojection_rmse_ft"],
        "worst": POINTS[worst][0],
    }))


if __name__ == "__main__":
    main()
