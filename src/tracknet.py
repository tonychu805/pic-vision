"""TrackNet output -> rally segments.

TrackNet inference runs on RunPod GPU (scripts/pod_infer.py) and emits a
predictions.csv with columns Frame,Visibility,X,Y. This module parses that
output and feeds it into the existing backend-agnostic signal pipeline.

Flow: predictions_csv -> ball_track -> crossing_times -> cluster_crossings

Validated parameters (IMG_7655 full-video run, EXPERIMENTS.md 2026-08-12):
  gap_sec=3.0, min_crossings=3
"""

import csv
import logging

from src.ball import crossing_times, cluster_crossings

log = logging.getLogger(__name__)


def load_predictions(csv_path, fps):
    """Parse TrackNet predictions.csv -> [(time_sec, y or None)] ball track.

    csv_path: path to the CSV produced by scripts/pod_infer.py
    fps: frame rate of the video used for inference (used to convert frame
         numbers to timestamps; must match the source video)
    """
    track = []
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            frame = int(row["Frame"])
            t = frame / fps
            y = float(row["Y"]) if row["Visibility"] == "1" else None
            track.append((t, y))
    visible = sum(1 for _, y in track if y is not None)
    pct = 100 * visible / len(track) if track else 0
    log.info("CSV: %d frames, %d visible (%.0f%%) — %.1fs @ %.1f fps",
             len(track), visible, pct, len(track) / fps if fps else 0, fps)
    return track


def rally_segments_from_predictions(csv_path, fps, net_y, *, gap_sec,
                                    min_crossings=3, band=0.0):
    """Parse a TrackNet predictions CSV and return rally segments.

    Returns [{start, end, crossings}] — same schema as cluster_crossings.
    Use gap_sec=3.0 and min_crossings=3 (validated on IMG_7655 full run).
    """
    track = load_predictions(csv_path, fps)
    times = crossing_times(track, net_y=net_y, band=band)
    log.info("net_y=%.1f band=%.1f → %d raw crossings", net_y, band, len(times))
    segments = cluster_crossings(times, gap_sec=gap_sec, min_crossings=min_crossings)
    log.info("%d clusters pass min_crossings=%d (gap_sec=%.1f)",
             len(segments), min_crossings, gap_sec)
    return segments
