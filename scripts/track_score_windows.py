"""Whole-track scoring over short windows (Test D, PIC-226). Experimental; NOT imported by the pipeline.

Idea (operator, 2026-10-15): fakes (sun glare, reflections, a ball at rest, clothing) are pixel-locked
or crawl; a real ball flies. Score the track over a 1.5 s window, not the single dot.

Rules, fixed BEFORE the run (nothing tuned):
  window      45 frames, step 15; scored only if it holds >= 6 tracked points, else left alone
  piece       consecutive tracked points with <= 3 frames between them, cut where the direction
              turns by more than 90 degrees (a hit or bounce)
  flight      a piece with >= 5 points, RMS residual <= 6 px of a quadratic-in-time fit of x and y,
              path length >= 80 px, median speed >= 4 px/frame
  ball-like   a scored window where >= 50% of its tracked points lie in flight pieces
  drop        a tracked point is dropped when every scored window that contains it is not ball-like
              (points no scored window covers are kept)
"""
import numpy as np

W, STEP, MIN_PTS = 45, 15, 6
GAP, TURN_DEG = 3, 90.0
MIN_PIECE, RMS_PX, MIN_LEN, MIN_SPEED = 5, 6.0, 80.0, 4.0


def _pieces(pts):
    """pts: [(frame, x, y)] sorted. Split at gaps > GAP frames and at turns > TURN_DEG."""
    out, cur = [], []
    for p in pts:
        if cur and p[0] - cur[-1][0] > GAP:
            out.append(cur); cur = []
        if len(cur) >= 2:
            v1 = np.array([cur[-1][1] - cur[-2][1], cur[-1][2] - cur[-2][2]])
            v2 = np.array([p[1] - cur[-1][1], p[2] - cur[-1][2]])
            n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
            if n1 > 1e-6 and n2 > 1e-6:
                ang = np.degrees(np.arccos(np.clip(v1 @ v2 / (n1 * n2), -1, 1)))
                if ang > TURN_DEG:
                    out.append(cur); cur = [cur[-1]]
        cur.append(p)
    if cur:
        out.append(cur)
    return out


def _is_flight(piece):
    if len(piece) < MIN_PIECE:
        return False
    f = np.array([p[0] for p in piece], float); x = np.array([p[1] for p in piece]); y = np.array([p[2] for p in piece])
    length = float(np.sum(np.hypot(np.diff(x), np.diff(y))))
    if length < MIN_LEN:
        return False
    speeds = np.hypot(np.diff(x), np.diff(y)) / np.maximum(np.diff(f), 1)
    if float(np.median(speeds)) < MIN_SPEED:
        return False
    deg = min(2, len(piece) - 2)
    rx = x - np.polyval(np.polyfit(f, x, deg), f); ry = y - np.polyval(np.polyfit(f, y, deg), f)
    return float(np.sqrt(np.mean(rx ** 2 + ry ** 2))) <= RMS_PX


def window_ball_like(pts):
    """pts: tracked points inside one window. None if not scored (too few points)."""
    if len(pts) < MIN_PTS:
        return None
    flying = sum(len(p) for p in _pieces(pts) if _is_flight(p))
    return flying / len(pts) >= 0.5


def drop_non_flight(ys, xs):
    n = len(ys)
    verdict = {}                     # frame -> list of window verdicts covering it
    for s in range(0, max(1, n - W + 1), STEP):
        pts = [(i, xs[i], ys[i]) for i in range(s, min(n, s + W)) if ys[i] is not None and xs[i] is not None]
        v = window_ball_like(pts)
        if v is None:
            continue
        for p in pts:
            verdict.setdefault(p[0], []).append(v)
    out = list(ys)
    for i, vs in verdict.items():
        if not any(vs):
            out[i] = None
    return out
