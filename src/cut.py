"""End-to-end orchestrator: raw footage -> browse-ready rally clips (TECH_SPEC §8).

The one-pass wiring the pipeline was missing its final link for: run the v1
rally detector over a clip, attach the crossing count as the ranking score
(ADR-039: crossing count = rally score), and cut each rally into an H.264 clip +
manifest. detect_rallies (YOLO) and cut_clips (ffmpeg) are the heavy ends; this
is the thin glue between them, plus a CLI."""

import argparse
import json

from src.pipeline import detect_rallies
from src.render import cut_clips, concat_clips
from src.ball import net_line_y
from src.calib import detect_net_y, pick_net_y


def cut_rallies(video, net_y, out_dir, *, max_jump, gap_sec, band=0.0,
                min_crossings=5, court_id=None, session_id=None,
                pad_sec=3.0, **detect_kwargs):
    """Footage -> rally clips in one pass: detect rallies, score each by its
    crossing count (ADR-039), cut H.264 clips + manifest.json into out_dir.
    pad_sec adds context before/after each crossing burst (default 3s).
    detect_kwargs pass through to detect_rallies (start, end, conf, imgsz,
    weights, sample_fps, max_ball_px)."""
    segments = detect_rallies(video, net_y, max_jump=max_jump, gap_sec=gap_sec,
                              band=band, min_crossings=min_crossings,
                              **detect_kwargs)
    scored = [{**s, "score": s["crossings"]} for s in segments]
    manifest = cut_clips(video, scored, out_dir,
                         court_id=court_id, session_id=session_id,
                         pad_sec=pad_sec)
    concat_clips(manifest, out_dir)
    return manifest


def main(argv=None):
    p = argparse.ArgumentParser(description="Cut rally clips from footage.")
    p.add_argument("--video", required=True)
    p.add_argument("--calib", default=None,
                   help="calibration json containing net_y")
    p.add_argument("--net-y", type=float, default=None,
                   help="net line pixel y-coordinate (overrides --calib and picker)")
    p.add_argument("--auto-detect", action="store_true",
                   help="headless Hough-based net detection instead of interactive picker")
    p.add_argument("--out", required=True, help="output dir for clips + manifest")
    p.add_argument("--max-jump", type=float, default=150.0,
                   help="tracker teleport threshold, px (100-200 validated)")
    p.add_argument("--gap-sec", type=float, default=3.0,
                   help="max seconds between crossings in one rally (1.0 too tight)")
    p.add_argument("--min-crossings", type=int, default=5)
    p.add_argument("--band", type=float, default=0.0,
                   help="net hysteresis band, px")
    p.add_argument("--sample-fps", type=float, default=10.0,
                   help="frames per second to sample for ball detection (default 10)")
    p.add_argument("--weights", default="yolov8x.pt",
                   help="YOLO weights file (default yolov8x.pt; use yolov8n.pt for speed)")
    p.add_argument("--pad-sec", type=float, default=3.0,
                   help="seconds of context added before/after each rally burst (default 3)")
    p.add_argument("--max-ball-px", type=float, default=None,
                   help="ball size filter; measure on the actual footage first")
    p.add_argument("--court-id", default=None)
    p.add_argument("--session-id", default=None)
    args = p.parse_args(argv)

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
    manifest = cut_rallies(
        args.video, net_y, args.out, max_jump=args.max_jump,
        gap_sec=args.gap_sec, band=args.band, min_crossings=args.min_crossings,
        court_id=args.court_id, session_id=args.session_id,
        sample_fps=args.sample_fps, max_ball_px=args.max_ball_px,
        weights=args.weights, pad_sec=args.pad_sec)
    print(f"cut {len(manifest)} rallies -> {args.out}/manifest.json")
    if manifest:
        print(f"highlight -> {args.out}/highlight.mp4")


if __name__ == "__main__":
    main()
