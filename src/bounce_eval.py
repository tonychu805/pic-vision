"""Pure helpers for the bounce-labelling pilot (2026-10-14): matching a hand-labelled
ball bounce to what the detector / tracker produced, and measuring the court error in
feet. No video, no model. Used by scripts/eval_bounce_recovery.py and tests."""
import random

import numpy as np

TOL_FRAMES = 3      # a detection counts as "at the bounce" within +-3 frames
TOL_PX = 15.0       # ...and within 15 px of where the operator marked the ball


def project(H, x, y):
    """Image pixel -> court feet through homography H (3x3, image -> court)."""
    v = np.asarray(H, dtype=float) @ np.array([x, y, 1.0])
    return float(v[0] / v[2]), float(v[1] / v[2])


def court_error_ft(H, a, b):
    """Distance in court feet between two image points (exact for points on the floor)."""
    ax, ay = project(H, *a)
    bx, by = project(H, *b)
    return float(((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5)


def nearest_point(points, frame, tol=TOL_FRAMES):
    """points: {frame: (x, y)}. The point nearest in time to `frame` within tol, or None."""
    best = None
    for f in range(frame - tol, frame + tol + 1):
        if f in points and (best is None or abs(f - frame) < abs(best[0] - frame)):
            best = (f, points[f])
    return None if best is None else best[1]


def near_half(H, x, y, net_y=22.0):
    """True when an image point is on the near (camera-side) half of the court."""
    return project(H, x, y)[1] < net_y


def recover(label, raw, tracked, cands, H):
    """How one labelled bounce shows up in the system's output.

    label   {'frame', 'x', 'y', 'visible'}   (x, y: where the ball touched the floor, image px)
    raw     {frame: (x, y)}  every raw detection
    tracked {frame: (x, y)}  tracker-accepted points
    cands   {frame: (x, y)}  bounce candidates from the finder
    Returns booleans seen / tracked / found plus court error (ft) of the nearest tracked
    point and of the nearest candidate, or None when there is none."""
    f, p = label["frame"], (label["x"], label["y"])

    def hit(points):
        q = nearest_point(points, f)
        if q is None:
            return None
        return q if ((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5 <= TOL_PX else None

    seen = nearest_point(raw, f)
    trk = nearest_point(tracked, f)
    cand = nearest_point(cands, f)
    cand_ok = hit(cands)
    return {
        "seen": seen is not None,
        "tracked": trk is not None,
        "found": cand_ok is not None,
        "tracked_err_ft": None if trk is None else court_error_ft(H, trk, p),
        "cand_err_ft": None if cand is None else court_error_ft(H, cand, p),
    }


def percentile(vals, q):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    k = min(len(vals) - 1, max(0, int(round(q * (len(vals) - 1)))))
    return vals[k]


def pick_sample(pool, n, seed=0):
    """A reproducible sample of n items from pool (list), order preserved."""
    rng = random.Random(seed)
    idx = sorted(rng.sample(range(len(pool)), min(n, len(pool))))
    return [pool[i] for i in idx]
