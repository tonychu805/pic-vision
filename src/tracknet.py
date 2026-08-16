"""TrackNet output -> rally segments.

TrackNet inference runs on RunPod GPU (scripts/pod_infer.py) and emits a
predictions.csv with columns Frame,Visibility,X,Y. This module parses that
output and feeds it into the existing backend-agnostic signal pipeline.

Flow: predictions_csv -> court X-gate -> track_ball -> crossing_times -> cluster_crossings

Validated parameters (IMG_7655 full-video run, EXPERIMENTS.md 2026-08-12):
  gap_sec=3.0, min_crossings=3

Multi-court false positive (confirmed 2026-08-16 on IMG_7744): TrackNet's
per-frame best-guess ball can land on an adjacent court (real ball, wrong
court), and Y-only crossing detection has no way to tell. track_ball
(src/track.py) alone does NOT fix this on real footage: it releases its
teleport-rejection lock after reset_after frames with no detection, and real
dead time between rallies routinely exceeds that — so by the time the
adjacent-court ball reappears, track_ball has already forgotten the near
court's last position and happily re-acquires on it. That gap is why
court_x_min/court_x_max exist: they drop out-of-range detections before
track_ball (or anything else) ever sees them, so there's no reset window to
exploit. track_ball still matters on top of the gate for within-court
jitter/teleports. See src/calib.py's court_x_range for deriving the bounds
from calibrate.py's court corners.
"""

import csv
import logging

from src.ball import crossing_times, cluster_crossings
from src.track import track_ball

log = logging.getLogger(__name__)


def load_predictions(csv_path, fps):
    """Parse TrackNet predictions.csv -> [(time_sec, x or None, y or None)].

    csv_path: path to the CSV produced by scripts/pod_infer.py
    fps: frame rate of the video used for inference (used to convert frame
         numbers to timestamps; must match the source video)
    """
    track = []
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            frame = int(row["Frame"])
            t = frame / fps
            if row["Visibility"] == "1":
                x, y = float(row["X"]), float(row["Y"])
            else:
                x = y = None
            track.append((t, x, y))
    visible = sum(1 for _, x, _ in track if x is not None)
    pct = 100 * visible / len(track) if track else 0
    log.info("CSV: %d frames, %d visible (%.0f%%) — %.1fs @ %.1f fps",
             len(track), visible, pct, len(track) / fps if fps else 0, fps)
    return track


def rally_segments_from_predictions(csv_path, fps, net_y, *, gap_sec,
                                    min_crossings=3, band=0.0,
                                    max_jump=150, reset_after=15,
                                    court_x_min=None, court_x_max=None):
    """Parse a TrackNet predictions CSV and return rally segments.

    First applies the court X-gate (court_x_min/court_x_max, from
    src/calib.py's court_x_range): any detection outside the tracked court's
    image-x bounds is dropped outright, before track_ball ever sees it. This
    is what actually stops an adjacent court's ball from producing phantom
    crossings — track_ball's max_jump/reset_after alone can't, since a long
    enough gap resets the teleport check (see module docstring). Pass None
    for either bound to skip that side of the gate (e.g. no calibration
    available yet).

    track_ball then runs over what's left, for within-court jitter/teleports
    (same defaults as the validated YOLO path, ADR-039).

    Returns [{start, end, crossings}] — same schema as cluster_crossings.
    Use gap_sec=3.0 and min_crossings=3 (validated on IMG_7655 full run).
    """
    track = load_predictions(csv_path, fps)
    times = [t for t, _, _ in track]

    def in_court_x(x):
        if x is None:
            return False
        if court_x_min is not None and x < court_x_min:
            return False
        if court_x_max is not None and x > court_x_max:
            return False
        return True

    frames = [[(x, y, 1.0)] if in_court_x(x) else [] for _, x, y in track]
    if court_x_min is not None or court_x_max is not None:
        visible = sum(1 for _, x, _ in track if x is not None)
        in_range = sum(1 for f in frames if f)
        log.info("court X-gate [%s, %s] → dropped %d/%d visible detections outside tracked court",
                 court_x_min, court_x_max, visible - in_range, visible)

    ys = track_ball(frames, max_jump=max_jump, reset_after=reset_after)
    tracked = list(zip(times, ys))
    dropped = sum(1 for f, y in zip(frames, ys) if f and y is None)
    log.info("track_ball: max_jump=%.0f reset_after=%d → dropped %d/%d in-range detections as teleports",
             max_jump, reset_after, dropped, sum(1 for f in frames if f))
    times_crossed = crossing_times(tracked, net_y=net_y, band=band)
    log.info("net_y=%.1f band=%.1f → %d raw crossings", net_y, band, len(times_crossed))
    segments = cluster_crossings(times_crossed, gap_sec=gap_sec, min_crossings=min_crossings)
    log.info("%d clusters pass min_crossings=%d (gap_sec=%.1f)",
             len(segments), min_crossings, gap_sec)
    return segments
