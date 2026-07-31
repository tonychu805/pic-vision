#!/usr/bin/env python3
"""
Court calibration — click 12 court intersections once per camera mount.

Usage:
    python calibrate.py session.mp4 --at 300 --out court_calibration.json

Controls:
    left click   place the next point
    u            undo last point
    r            reset all
    ENTER        save (once all 12 placed)
    q            quit without saving
"""
import argparse
import json
import sys

import cv2
import numpy as np

# Pickleball court, feet. Origin = near-left corner. Net at y=22.
# Non-volley zone lines 7 ft from the net -> y=15 (near) and y=29 (far).
POINTS = [
    ("near-left corner (baseline x left sideline)", (0.0, 0.0)),
    ("near-right corner", (20.0, 0.0)),
    ("far-left corner", (0.0, 44.0)),
    ("far-right corner", (20.0, 44.0)),
    ("near NVZ line x left sideline", (0.0, 15.0)),
    ("near NVZ line x right sideline", (20.0, 15.0)),
    ("far NVZ line x left sideline", (0.0, 29.0)),
    ("far NVZ line x right sideline", (20.0, 29.0)),
    ("near centerline x baseline", (10.0, 0.0)),
    ("far centerline x baseline", (10.0, 44.0)),
    ("near centerline x NVZ line", (10.0, 15.0)),
    ("far centerline x NVZ line", (10.0, 29.0)),
]

clicked: list[tuple[int, int]] = []


def on_mouse(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN and len(clicked) < len(POINTS):
        clicked.append((x, y))


def draw(frame):
    img = frame.copy()
    for i, (px, py) in enumerate(clicked):
        cv2.circle(img, (px, py), 6, (0, 255, 0), -1)
        cv2.putText(img, str(i + 1), (px + 9, py - 9),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    n = len(clicked)
    msg = "ALL 12 PLACED - press ENTER to save" if n == len(POINTS) \
        else f"{n + 1}/12  ->  {POINTS[n][0]}"
    cv2.rectangle(img, (0, 0), (img.shape[1], 40), (0, 0, 0), -1)
    cv2.putText(img, msg, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                (255, 255, 255), 2)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--at", type=float, default=60.0,
                    help="seconds into the video to grab the frame")
    ap.add_argument("--out", default="court_calibration.json")
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.video)
    cap.set(cv2.CAP_PROP_POS_MSEC, args.at * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        sys.exit(f"could not read a frame at {args.at}s")

    cv2.namedWindow("calibrate", cv2.WINDOW_NORMAL)
    cv2.setMouseCallback("calibrate", on_mouse)

    while True:
        cv2.imshow("calibrate", draw(frame))
        k = cv2.waitKey(20) & 0xFF
        if k == ord("q"):
            sys.exit("aborted")
        if k == ord("u") and clicked:
            clicked.pop()
        if k == ord("r"):
            clicked.clear()
        if k in (13, 10) and len(clicked) == len(POINTS):
            break

    cv2.destroyAllWindows()

    src = np.array(clicked, dtype=np.float32)
    dst = np.array([c for _, c in POINTS], dtype=np.float32)
    H, mask = cv2.findHomography(src, dst, method=cv2.RANSAC,
                                 ransacReprojThreshold=5.0)
    if H is None:
        sys.exit("homography failed - points are probably mis-ordered")

    # Reprojection error, in feet, then back-projected to pixels for a sanity read.
    proj = cv2.perspectiveTransform(src.reshape(-1, 1, 2), H).reshape(-1, 2)
    err_ft = np.linalg.norm(proj - dst, axis=1)
    rmse_ft = float(np.sqrt((err_ft ** 2).mean()))

    out = {
        "video": args.video,
        "frame_at_sec": args.at,
        "image_points": [[float(x), float(y)] for x, y in clicked],
        "court_points_ft": [list(c) for _, c in POINTS],
        "point_names": [n for n, _ in POINTS],
        "homography": H.tolist(),
        "reprojection_rmse_ft": rmse_ft,
        "per_point_error_ft": [float(e) for e in err_ft],
        "court_size_ft": [20.0, 44.0],
        "net_y_ft": 22.0,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)

    print(f"saved {args.out}")
    print(f"reprojection RMSE: {rmse_ft:.3f} ft")
    if rmse_ft > 0.5:
        print("WARNING: RMSE > 0.5 ft - check point order and re-click")
    worst = int(np.argmax(err_ft))
    print(f"worst point: #{worst + 1} {POINTS[worst][0]} ({err_ft[worst]:.3f} ft)")


if __name__ == "__main__":
    main()
