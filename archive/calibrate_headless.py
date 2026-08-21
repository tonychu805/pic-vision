#!/usr/bin/env python3
"""
Headless court calibration — same 12 court intersections + 2 net-tape points as
calibrate.py, but typed in instead of mouse-clicked. Use this over a plain SSH
session (no X11/display available): it saves a still frame as a PNG, you open
that PNG in any viewer that shows cursor pixel position (VS Code Remote-SSH,
GIMP, browser dev tools, etc.), and type each point's coordinates back here.

Usage:
    python calibrate_headless.py session.mp4 --at 300 --out court_calibration.json

Controls at each prompt:
    x,y   accept the point
    u     undo the previous point and re-enter it
    q     quit without saving
"""
import argparse
import sys

import cv2

from calibrate import POINTS, NET_PROMPTS, compute_calibration


def prompt_points(labels):
    points = []
    i = 0
    while i < len(labels):
        raw = input(f"{i + 1}/{len(labels)}  {labels[i]}  (x,y): ").strip()
        if raw.lower() == "q":
            sys.exit("aborted")
        if raw.lower() == "u":
            if points:
                points.pop()
                i -= 1
            continue
        try:
            x_str, y_str = raw.replace(",", " ").split()
            points.append((float(x_str), float(y_str)))
            i += 1
        except ValueError:
            print("  could not parse — enter as 'x,y' (or u to undo, q to quit)")
    return points


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--at", type=float, default=60.0,
                     help="seconds into the video to grab the frame")
    ap.add_argument("--out", default="court_calibration.json")
    ap.add_argument("--frame-out", default=None,
                     help="where to save the still frame PNG (default: <out>.png)")
    args = ap.parse_args()

    frame_out = args.frame_out or (args.out.rsplit(".", 1)[0] + "_frame.png")

    cap = cv2.VideoCapture(args.video)
    cap.set(cv2.CAP_PROP_POS_MSEC, args.at * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        sys.exit(f"could not read a frame at {args.at}s")

    cv2.imwrite(frame_out, frame)
    print(f"saved frame -> {frame_out}")
    print(f"open it in a viewer that shows pixel coordinates on hover, then enter "
          f"each point below (image is {frame.shape[1]}x{frame.shape[0]}).\n")

    print("--- 12 court points ---")
    court_points = prompt_points([label for label, _ in POINTS])
    print("\n--- 2 net-tape points (TOP of net, where the ball crosses) ---")
    net_points = prompt_points(NET_PROMPTS)

    result = compute_calibration(court_points, POINTS)
    rmse_ft = result["reprojection_rmse_ft"]

    out = {
        "video": args.video,
        "frame_at_sec": args.at,
        **result,
        "net_image_points": [[float(x), float(y)] for x, y in net_points],
        "court_size_ft": [20.0, 44.0],
        "net_y_ft": 22.0,
    }
    import json
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)

    print(f"\nsaved {args.out}")
    print(f"reprojection RMSE: {rmse_ft:.3f} ft")
    if rmse_ft > 0.5:
        print("WARNING: RMSE > 0.5 ft - re-check the 12 court points, especially the worst one below")
    err_ft = result["per_point_error_ft"]
    worst = int(max(range(len(err_ft)), key=lambda k: err_ft[k]))
    print(f"worst point: #{worst + 1} {POINTS[worst][0]} ({err_ft[worst]:.3f} ft)")


if __name__ == "__main__":
    main()
