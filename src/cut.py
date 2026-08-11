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


def cut_rallies(video, net_y, out_dir, *, max_jump, gap_sec, band=0.0,
                min_crossings=5, court_id=None, session_id=None,
                **detect_kwargs):
    """Footage -> rally clips in one pass: detect rallies, score each by its
    crossing count (ADR-039), cut H.264 clips + manifest.json into out_dir.
    Returns the manifest (list of clip records). detect_kwargs pass through to
    detect_rallies (start, end, conf, imgsz, weights, sample_fps, max_ball_px)."""
    segments = detect_rallies(video, net_y, max_jump=max_jump, gap_sec=gap_sec,
                              band=band, min_crossings=min_crossings,
                              **detect_kwargs)
    scored = [{**s, "score": s["crossings"]} for s in segments]
    manifest = cut_clips(video, scored, out_dir,
                         court_id=court_id, session_id=session_id)
    concat_clips(manifest, out_dir)
    return manifest


def main(argv=None):
    p = argparse.ArgumentParser(description="Cut rally clips from footage.")
    p.add_argument("--video", required=True)
    p.add_argument("--calib", required=True,
                   help="calibration json (net line comes from it)")
    p.add_argument("--out", required=True, help="output dir for clips + manifest")
    p.add_argument("--max-jump", type=float, default=150.0,
                   help="tracker teleport threshold, px (100-200 validated)")
    p.add_argument("--gap-sec", type=float, default=3.0,
                   help="max seconds between crossings in one rally (1.0 too tight)")
    p.add_argument("--min-crossings", type=int, default=5)
    p.add_argument("--band", type=float, default=0.0,
                   help="net hysteresis band, px")
    p.add_argument("--max-ball-px", type=float, default=None,
                   help="ball size filter; measure on the actual footage first")
    p.add_argument("--court-id", default=None)
    p.add_argument("--session-id", default=None)
    args = p.parse_args(argv)

    with open(args.calib) as f:
        calib = json.load(f)
    net_y = net_line_y(calib)
    manifest = cut_rallies(
        args.video, net_y, args.out, max_jump=args.max_jump,
        gap_sec=args.gap_sec, band=args.band, min_crossings=args.min_crossings,
        court_id=args.court_id, session_id=args.session_id,
        max_ball_px=args.max_ball_px)
    print(f"cut {len(manifest)} rallies -> {args.out}/manifest.json")
    if manifest:
        print(f"highlight -> {args.out}/highlight.mp4")


if __name__ == "__main__":
    main()
