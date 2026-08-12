"""Process game footage using TrackNet predictions from RunPod.

Full workflow:
  1. On the pod: python3 scripts/pod_infer.py --video game.MOV --output predictions.csv
  2. Copy predictions.csv back locally (runpodctl receive or scp)
  3. Run this script locally to cut rally clips:
     python3 scripts/process_footage.py \
       --video game.MOV \
       --predictions predictions.csv \
       --net-y 260 \
       --out clips/

The video FPS is read from the video file itself; --fps overrides if needed.
"""

import argparse
import json
import logging
import cv2

from src.tracknet import rally_segments_from_predictions
from src.render import cut_clips, concat_clips


def get_video_fps(video_path):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    return fps


def main(argv=None):
    p = argparse.ArgumentParser(description="Cut rally clips from TrackNet predictions.")
    p.add_argument("--video", required=True, help="original full-res video (local)")
    p.add_argument("--predictions", required=True,
                   help="predictions.csv from pod_infer.py")
    p.add_argument("--net-y", type=float, required=True,
                   help="net line pixel y-coordinate in the video (use pick_net_y or --net-y from calib)")
    p.add_argument("--fps", type=float, default=None,
                   help="video frame rate (auto-detected from video if omitted)")
    p.add_argument("--out", required=True, help="output directory for clips + manifest")
    p.add_argument("--gap-sec", type=float, default=3.0,
                   help="max gap between crossings within one rally (default 3.0)")
    p.add_argument("--min-crossings", type=int, default=3,
                   help="minimum crossings to count as a rally (default 3)")
    p.add_argument("--band", type=float, default=0.0,
                   help="net hysteresis band in pixels (default 0; tune for dink rallies)")
    p.add_argument("--pad-sec", type=float, default=3.0,
                   help="seconds of context added before/after each clip (default 3)")
    p.add_argument("--court-id", default=None)
    p.add_argument("--session-id", default=None)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")

    fps = args.fps or get_video_fps(args.video)
    print(f"fps={fps:.2f}  net_y={args.net_y}  gap_sec={args.gap_sec}  min_crossings={args.min_crossings}")

    segments = rally_segments_from_predictions(
        args.predictions, fps, args.net_y,
        gap_sec=args.gap_sec,
        min_crossings=args.min_crossings,
        band=args.band,
    )
    print(f"Detected {len(segments)} rally segments:")
    for i, s in enumerate(segments):
        print(f"  [{i+1}] {s['start']:.1f}–{s['end']:.1f}s  ({s['crossings']} crossings)")

    if not segments:
        print("No rallies detected. Try lowering --min-crossings or adjusting --net-y.")
        return

    scored = [{**s, "score": s["crossings"]} for s in segments]
    manifest = cut_clips(args.video, scored, args.out,
                         court_id=args.court_id,
                         session_id=args.session_id,
                         pad_sec=args.pad_sec)
    concat_clips(manifest, args.out)
    print(f"\nCut {len(manifest)} rally clips -> {args.out}/manifest.json")
    if manifest:
        print(f"Highlight reel -> {args.out}/highlight.mp4")


if __name__ == "__main__":
    main()
