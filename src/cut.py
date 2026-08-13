"""End-to-end orchestrator: TrackNet predictions -> browse-ready rally clips.

TrackNet inference runs on RunPod GPU (scripts/pod_infer.py) and produces a
predictions.csv. This module reads that CSV, detects rally segments, and cuts
H.264 clips + a manifest. The YOLO-based path is archived (archive/yolo_pipeline.py,
ADR-046).

Typical flow:
    python3 scripts/pod_infer.py --video game.MOV           # on pod
    # copy predictions.csv back locally, then (interactive net picker):
    make process VIDEO=game.MOV CSV=predictions.csv OUT=clips/
    # or reuse a known net line:
    make process VIDEO=game.MOV CSV=predictions.csv NET_Y=210 OUT=clips/
"""

import argparse
import json
import logging

import cv2

from src.tracknet import rally_segments_from_predictions
from src.render import cut_clips, concat_clips
from src.ball import net_line_y
from src.calib import detect_net_y, pick_net_y


def cut_rallies_from_predictions(video, csv_path, fps, net_y, out_dir, *,
                                 gap_sec=3.0, min_crossings=3, band=0.0,
                                 court_id=None, session_id=None, pad_sec=3.0):
    """TrackNet CSV -> rally clips in one pass: parse predictions, score by
    crossing count (ADR-039), cut H.264 clips + manifest.json into out_dir."""
    segments = rally_segments_from_predictions(
        csv_path, fps, net_y,
        gap_sec=gap_sec, min_crossings=min_crossings, band=band,
    )
    scored = [{**s, "score": s["crossings"]} for s in segments]
    manifest = cut_clips(video, scored, out_dir,
                         court_id=court_id, session_id=session_id,
                         pad_sec=pad_sec)
    concat_clips(manifest, out_dir)
    return manifest


def main(argv=None):
    p = argparse.ArgumentParser(description="Cut rally clips from TrackNet predictions.")
    p.add_argument("--video", required=True)
    p.add_argument("--predictions", required=True,
                   help="predictions.csv produced by scripts/pod_infer.py")
    p.add_argument("--calib", default=None,
                   help="calibration JSON containing net_y (overridden by --net-y)")
    p.add_argument("--net-y", type=float, default=None,
                   help="net line pixel y-coordinate (fastest; overrides --calib and picker)")
    p.add_argument("--fps", type=float, default=None,
                   help="video frame rate (auto-detected from video if omitted)")
    p.add_argument("--auto-detect", action="store_true",
                   help="headless Hough-based net detection instead of interactive picker")
    p.add_argument("--out", required=True, help="output dir for clips + manifest")
    p.add_argument("--gap-sec", type=float, default=3.0,
                   help="max seconds between crossings in one rally (default 3.0)")
    p.add_argument("--min-crossings", type=int, default=3,
                   help="minimum crossings to count as a rally (default 3)")
    p.add_argument("--band", type=float, default=0.0,
                   help="net hysteresis band, px (tune for dink rallies: 15-30px)")
    p.add_argument("--pad-sec", type=float, default=3.0,
                   help="seconds of context added before/after each rally burst (default 3)")
    p.add_argument("--court-id", default=None)
    p.add_argument("--session-id", default=None)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")

    if args.net_y is not None:
        net_y = args.net_y
        print(f"net_y = {net_y:.1f} (from --net-y)")
    elif args.calib:
        with open(args.calib) as f:
            calib = json.load(f)
        net_y = net_line_y(calib)
        print(f"net_y = {net_y:.1f} (from calibration)")
    elif args.auto_detect:
        print("auto-detecting net line from footage...")
        net_y = detect_net_y(args.video)
        print(f"net_y = {net_y:.1f} (auto-detected)")
    else:
        net_y = pick_net_y(args.video)
        print(f"net_y = {net_y:.1f} (picked interactively)")

    if args.fps:
        fps = args.fps
    else:
        cap = cv2.VideoCapture(args.video)
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
    print(f"fps = {fps:.2f}")

    manifest = cut_rallies_from_predictions(
        args.video, args.predictions, fps, net_y, args.out,
        gap_sec=args.gap_sec, min_crossings=args.min_crossings,
        band=args.band, court_id=args.court_id, session_id=args.session_id,
        pad_sec=args.pad_sec,
    )
    print(f"cut {len(manifest)} rallies -> {args.out}/manifest.json")
    if manifest:
        print(f"highlight -> {args.out}/highlight.mp4")


if __name__ == "__main__":
    main()
