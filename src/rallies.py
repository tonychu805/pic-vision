"""Rally candidates from one session's ball detections.

The core every reel shares -- the full reel (scripts/rank_and_reel.py), the
burst reel (scripts/burst_moment_reel.py) and the top-rally clips
(scripts/top_rallies_reel.py) each carried an identical copy of this until
2026-09-23: load the detections, keep only the ones inside the court wedge,
track the ball, find its net crossings, cluster those into rally segments,
and measure per-frame ball speed for the ranking. Each reel then ranks the
segments with its own weights and cuts its own clips.
"""
import json

from src.ball import cluster_crossings, crossing_times, net_line_y
from src.calib import court_wedge
from src.render import probe_fps
from src.select import frame_speeds, spike_threshold
from src.track import max_jump_for_fps, reset_after_for_fps, track_ball
from src.tracknet import load_predictions

# Shipped defaults, tuned on IMG_7743 (DECISIONS.md ADR-048).
GAP_SEC = 3.0
MIN_CROSSINGS = 6


def detect_candidates(video, csv, calib_path, gap_sec=GAP_SEC, min_crossings=MIN_CROSSINGS):
    """Candidate rally segments for one session, plus what ranking needs.

    Returns a dict:
      segments       candidate rallies (cluster_crossings' output)
      times_crossed  every net-crossing time, for per-segment crossing rates
      speeds         per-frame ball speeds of in-court detections
      threshold      the 90th-percentile speed that counts as a spike
    """
    with open(calib_path) as f:
        calib = json.load(f)
    fps = probe_fps(video)
    track = load_predictions(csv, fps)
    in_court = court_wedge(calib)
    net_y = net_line_y(calib)

    times = [t for t, *_ in track]
    frames = [[(x, y, conf if conf is not None else 1.0)] if in_court(x, y) else []
              for _, x, y, w, h, conf in track]
    ys = track_ball(frames, max_jump=max_jump_for_fps(fps), reset_after=reset_after_for_fps(fps))
    tracked = list(zip(times, ys))
    times_crossed = crossing_times(tracked, net_y=net_y, band=0.0)
    segments = cluster_crossings(times_crossed, gap_sec=gap_sec, min_crossings=min_crossings)

    raw_points = sorted([(t, x, y) for t, x, y, w, h, c in track if in_court(x, y)],
                        key=lambda p: p[0])
    speeds = frame_speeds(raw_points)
    threshold = spike_threshold(speeds, percentile=90)
    return {"segments": segments, "times_crossed": times_crossed, "speeds": speeds, "threshold": threshold}
