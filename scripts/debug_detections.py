"""Dump annotated frames around a time window so we can see what YOLO detects.

Usage:
    python scripts/debug_detections.py --video <path> --net-y <y> \
        --start <sec> --end <sec> --out <dir> [--sample-every <n>]

Saves one JPEG per sampled frame with:
- All 'sports ball' bounding boxes drawn
- Net line in green
- Confidence label on each box
"""

import argparse
import os
import cv2
from ultralytics import YOLO


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--net-y", type=float, required=True)
    p.add_argument("--start", type=float, required=True)
    p.add_argument("--end", type=float, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--sample-every", type=int, default=5,
                   help="save 1 frame every N (default 5 = ~6fps at 30fps source)")
    p.add_argument("--weights", default="yolov8x.pt")
    p.add_argument("--conf", type=float, default=0.10)
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)
    model = YOLO(args.weights)
    cap = cv2.VideoCapture(args.video)
    cap.set(cv2.CAP_PROP_POS_MSEC, args.start * 1000)
    saved = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if t > args.end:
            break
        pos = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        if pos % args.sample_every != 0:
            continue

        h, w = frame.shape[:2]
        net_y = int(args.net_y)
        cv2.line(frame, (0, net_y), (w, net_y), (0, 255, 0), 2)
        cv2.putText(frame, f"net_y={net_y}", (16, net_y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        b = model(frame, imgsz=1280, conf=args.conf, classes=[32], verbose=False)[0].boxes
        for j in range(len(b)):
            x1, y1, x2, y2 = [int(v) for v in b.xyxy[j].cpu().numpy()]
            conf = float(b.conf[j].cpu())
            cy = (y1 + y2) / 2
            color = (0, 0, 255) if cy > args.net_y else (255, 0, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, f"{conf:.2f}", (x1, y1 - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        fname = os.path.join(args.out, f"t{t:08.2f}.jpg")
        cv2.imwrite(fname, frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        saved += 1

    cap.release()
    print(f"saved {saved} frames to {args.out}/")


if __name__ == "__main__":
    main()
