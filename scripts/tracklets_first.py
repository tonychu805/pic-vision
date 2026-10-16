"""Tracklets before commitment (2026-10-16, PIC-226): drop detections that sit still, judged on short
tracklets built from ALL detections, before track_ball commits to a path.

Operator's design (2026-10-16): link detections into short tracklets first, kill the stationary ones,
let the existing tracker choose among what is left. Differs from the failed fixed mask / dwell tests:
a point is only dropped while it belongs to a still site, and points of a MOVING tracklet are never
dropped, so a ball flying over a reflection survives.

  1. tracklets   each detection joins the open tracklet whose last point is nearest, if within
                 min(150, LINK_PX * gap) px and gap <= MAX_GAP frames; else it starts a new one
  2. moving      a tracklet with >= 2 points whose bounding-box diagonal > STILL_PX
  3. still site  a point NOT in a moving tracklet is dropped when >= STILL_N - 1 other non-moving points
                 lie within STILL_PX of it within +-WINDOW frames (a still site needs STILL_N points
                 in ~6 s; a ball does not come back to the same 12 px that often)
Parameters fixed before any scoring, from physical reasoning, not tuned:
  LINK_PX 40 px/frame, MAX_GAP 5 frames, STILL_PX 12 px, WINDOW 90 frames, STILL_N 6.
"""
import math

LINK_PX, MAX_GAP, STILL_PX, WINDOW, STILL_N = 40.0, 5, 12.0, 90, 6


def _diag(t):
    xs = [p[1] for p in t]; ys = [p[2] for p in t]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def tracklets(frames):
    """frames: per-frame lists [(x, y, conf), ...]. Returns tracklets as lists of (frame, x, y)."""
    out, open_ = [], []
    for i, cands in enumerate(frames):
        for d in cands:
            x, y = d[0], d[1]
            best = None
            for t in open_:
                j, xl, yl = t[-1]
                g = i - j
                if g < 1 or g > MAX_GAP:
                    continue
                dist = math.hypot(x - xl, y - yl)
                if dist <= min(150.0, LINK_PX * g) and (best is None or dist < best[0]):
                    best = (dist, t)
            if best is not None:
                best[1].append((i, x, y))
            else:
                t = [(i, x, y)]
                out.append(t); open_.append(t)
        open_ = [t for t in open_ if i - t[-1][0] < MAX_GAP]
    return out


def drop_still(frames):
    """Same shape as frames, with detections at still sites removed."""
    tl = tracklets(frames)
    loose = [p for t in tl if not (len(t) >= 2 and _diag(t) > STILL_PX) for p in t]
    grid = {}
    for p in loose:
        grid.setdefault((int(p[1] // STILL_PX), int(p[2] // STILL_PX)), []).append(p)
    drop = set()
    for p in loose:
        cx, cy = int(p[1] // STILL_PX), int(p[2] // STILL_PX)
        n = 0
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for q in grid.get((gx, gy), ()):
                    if q is not p and abs(q[0] - p[0]) <= WINDOW and math.hypot(q[1] - p[1], q[2] - p[2]) <= STILL_PX:
                        n += 1
        if n >= STILL_N - 1:
            drop.add(p)
    return [[d for d in c if (i, d[0], d[1]) not in drop] for i, c in enumerate(frames)]
