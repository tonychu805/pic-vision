"""Two balls in the air: the mark of warm-up dinking (EXPERIMENTS.md 2026-11-24).

In a warm-up each pair at the kitchen hits its own ball. The ball model then
finds one ball in one frame and the other in the next, so the track keeps
jumping sideways across the court. A real point has one ball and rarely does.

two_ball_rate() counts those jumps per second of a clip. The console keeps a
long clip with a high rate out of the top 10 (reel_warmup_vetoed); the pod only
measures and reports.
"""
import numpy as np

JUMP_FT = 6.0          # sideways move between two detections that one ball can't make
CENTRE_FT = 10.0       # court centre line (court is 0..20 ft wide)
MAX_GAP_FRAMES = 2     # detections further apart than this aren't compared


def two_ball_rate(track, start, end, calib, video_size, fps):
    """Sideways jumps across the centre line per second of [start, end].

    track: src.tracknet.load_predictions output, [(t, x, y, ...)] in video pixels.
    calib: the calibration the video is in (after calib_for_box on a cropped video).
    video_size: (width, height) of that video. Returns None for an empty window.
    """
    if end <= start:
        return None
    cw, ch = calib.get("calibration_resolution") or video_size
    h = np.array(calib["homography"], dtype=np.float64) @ np.diag([cw / video_size[0], ch / video_size[1], 1.0])
    pts = []
    for t, x, y, *_ in track:
        if x is None or not start <= t <= end:
            continue
        q = h @ (x, y, 1.0)
        pts.append((t, q[0] / q[2]))
    max_dt = (MAX_GAP_FRAMES + 0.5) / fps
    jumps = sum(1 for (t0, x0), (t1, x1) in zip(pts, pts[1:])
                if t1 - t0 <= max_dt and abs(x1 - x0) > JUMP_FT and (x0 - CENTRE_FT) * (x1 - CENTRE_FT) < 0)
    return jumps / (end - start)
