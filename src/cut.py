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
from src.calib import detect_net_y, pick_net_y, court_x_range, court_wedge


def cut_rallies_from_predictions(video, csv_path, fps, net_y, out_dir, *,
                                 gap_sec=3.0, min_crossings=6, band=0.0,
                                 max_jump=150, reset_after=15,
                                 court_x_min=None, court_x_max=None,
                                 in_court=None,
                                 court_id=None, session_id=None, pad_sec=3.0,
                                 adaptive_gap=False):
    """TrackNet CSV -> rally clips in one pass: parse predictions, score by
    crossing count (ADR-039), cut H.264 clips + manifest.json into out_dir."""
    segments = rally_segments_from_predictions(
        csv_path, fps, net_y,
        gap_sec=gap_sec, min_crossings=min_crossings, band=band,
        max_jump=max_jump, reset_after=reset_after,
        court_x_min=court_x_min, court_x_max=court_x_max, in_court=in_court,
        adaptive_gap=adaptive_gap,
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
    p.add_argument("--min-crossings", type=int, default=6,
                   help="minimum crossings to count as a rally (default 6)")
    p.add_argument("--adaptive-gap", action="store_true",
                   help="derive gap_sec from this video's own observed rally length "
                        "(PIC-33) instead of applying --gap-sec as a fixed constant; "
                        "--gap-sec becomes the starting point. Opt-in, validated on 4 "
                        "videos to match or beat the fixed default -- see EXPERIMENTS.md")
    p.add_argument("--band", type=float, default=0.0,
                   help="net hysteresis band, px (tune for dink rallies: 15-30px)")
    p.add_argument("--max-jump", type=float, default=150,
                   help="track_ball teleport-rejection threshold, px between consecutive frames (default 150)")
    p.add_argument("--reset-after", type=int, default=15,
                   help="frames of no detection before track_ball allows re-acquiring elsewhere (default 15)")
    p.add_argument("--court-x-min", type=float, default=None,
                   help="reject detections left of this image-x (flat gate, explicit; overrides --calib's court_wedge)")
    p.add_argument("--court-x-max", type=float, default=None,
                   help="reject detections right of this image-x (flat gate, explicit; overrides --calib's court_wedge)")
    p.add_argument("--court-margin", type=float, default=50.0,
                   help="px padding applied to --calib-derived flat court X-range when --flat-court-gate is set (default 50)")
    p.add_argument("--flat-court-gate", action="store_true",
                   help="opt out of the default court_wedge gate and use the older flat "
                        "court_x_range gate, derived from --calib, instead. court_wedge is used "
                        "by default whenever --calib is given and no explicit "
                        "--court-x-min/--court-x-max is set (see CLAUDE.md)")
    p.add_argument("--pad-sec", type=float, default=3.0,
                   help="seconds of context added before/after each rally burst (default 3)")
    p.add_argument("--court-id", default=None)
    p.add_argument("--session-id", default=None)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")

    calib = None
    if args.calib:
        with open(args.calib) as f:
            calib = json.load(f)

    if args.net_y is not None:
        net_y = args.net_y
        print(f"net_y = {net_y:.1f} (from --net-y)")
    elif calib:
        net_y = net_line_y(calib)
        print(f"net_y = {net_y:.1f} (from calibration)")
    elif args.auto_detect:
        print("auto-detecting net line from footage...")
        net_y = detect_net_y(args.video)
        print(f"net_y = {net_y:.1f} (auto-detected)")
    else:
        net_y = pick_net_y(args.video)
        print(f"net_y = {net_y:.1f} (picked interactively)")

    court_x_min, court_x_max = args.court_x_min, args.court_x_max
    in_court = None
    if court_x_min is not None or court_x_max is not None:
        print(f"court X-range = [{court_x_min}, {court_x_max}] (explicit flat gate)")
    elif calib and args.flat_court_gate:
        court_x_min, court_x_max = court_x_range(calib, margin_px=args.court_margin)
        print(f"court X-range = [{court_x_min:.0f}, {court_x_max:.0f}] "
              f"(from calibration, margin={args.court_margin:.0f}px, flat gate)")
    elif calib:
        in_court = court_wedge(calib)
        print("court gate = court_wedge (perspective-aware, from calibration; "
              "pass --flat-court-gate for the older flat range)")

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
        band=args.band, max_jump=args.max_jump, reset_after=args.reset_after,
        court_x_min=court_x_min, court_x_max=court_x_max, in_court=in_court,
        court_id=args.court_id, session_id=args.session_id,
        pad_sec=args.pad_sec, adaptive_gap=args.adaptive_gap,
    )
    print(f"cut {len(manifest)} rallies -> {args.out}/manifest.json")
    if manifest:
        print(f"highlight -> {args.out}/highlight.mp4")


if __name__ == "__main__":
    main()
