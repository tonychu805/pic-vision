"""v1 rally pipeline: raw video -> rally segments, through the single-ball
tracker (ADR-039). Wires the previously-disconnected slices together:

    detect_candidates -> track_ball -> crossing_times -> cluster_crossings

The tracker step is what separates real rallies from dead time: it follows ONE
ball and rejects teleports to out-of-play balls (adjacent courts, idle balls),
so "best ball anywhere per frame" can't hop between courts and flip sides =
phantom crossings (EXPERIMENTS 2026-08-10, benchmark 659-666s).

rally_segments_from_candidates is the pure, testable core (takes a candidate
stream). detect_rallies adds the YOLO front-end for a real video."""

from src.track import track_ball
from src.ball import crossing_times, cluster_crossings, detect_candidates


def rally_segments_from_candidates(candidates, net_y, *, max_jump, gap_sec,
                                   band=0.0, min_crossings=5, reset_after=15):
    """candidates: [(time_sec, [(x, y, conf), ...])] from detect_candidates.
    Tracks a single ball across frames, counts net-crossings on the tracked
    positions, and clusters dense bursts into rallies. Returns
    [{start, end, crossings}]. net_y is the net line's image-y (from
    net_line_y(calib) on clean footage, or a per-window measured value on the
    zoom-compromised benchmark clips)."""
    times = [t for t, _ in candidates]
    frames = [c for _, c in candidates]
    ys = track_ball(frames, max_jump=max_jump, reset_after=reset_after)
    track = list(zip(times, ys))
    times_crossed = crossing_times(track, net_y=net_y, band=band)
    return cluster_crossings(times_crossed, gap_sec=gap_sec,
                             min_crossings=min_crossings)


def detect_rallies(video_path, net_y, *, max_jump, gap_sec, band=0.0,
                   min_crossings=5, reset_after=15, start=0.0, end=None,
                   conf=0.10, imgsz=1280, weights="yolov8x.pt",
                   sample_fps=None, max_ball_px=None):
    """End-to-end: run the ball detector over the clip, then
    rally_segments_from_candidates. net_y as above. Leave sample_fps=None (dense
    per-frame) — the tracker needs real ball motion to stay under max_jump
    between frames; subsampling breaks that. Returns [{start, end, crossings}]."""
    candidates = detect_candidates(
        video_path, start=start, end=end, conf=conf, imgsz=imgsz,
        weights=weights, sample_fps=sample_fps, max_ball_px=max_ball_px)
    return rally_segments_from_candidates(
        candidates, net_y, max_jump=max_jump, gap_sec=gap_sec, band=band,
        min_crossings=min_crossings, reset_after=reset_after)
