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


# ---- v2 (2026-10-16, Test E2). Test E failed because glare points chained into tracklets with ball points and
# the whole chain was exempt as "moving" (EXPERIMENTS.md Test E). v2 judges stillness PER POINT and has no
# tracklet exemption; what protects a moving ball is the motion of its own neighbours in time:
#   a point p is dropped when >= STILL_N - 1 other detections lie within STILL_PX of it within +-WINDOW frames
#   (a still site) AND p does not lie ON a moving path: there is no pair of detections a (frame p-1..p-3) and
#   b (frame p+1..p+3), more than STILL_PX apart and within LINK_PX per frame of each other, whose straight
#   line interpolated to p's frame passes within STILL_PX of p. A ball crossing a glare site is on such a
#   line; a glare point next to a passing ball is not. Known limit: a ball whose last (or first) detection
#   before a gap lands on a glare site has no confirming neighbour and is dropped.
# Same constants as v1, fixed before any chunk-3 label existed.


def _on_path(p, by_frame):
    i = p[0]
    for ja in range(i - 3, i):
        for a in by_frame.get(ja, ()):
            for jb in range(i + 1, i + 4):
                for b in by_frame.get(jb, ()):
                    span = math.hypot(b[1] - a[1], b[2] - a[2])
                    if not (STILL_PX < span <= LINK_PX * (jb - ja)):
                        continue
                    u = (i - ja) / (jb - ja)
                    if math.hypot(a[1] + u * (b[1] - a[1]) - p[1], a[2] + u * (b[2] - a[2]) - p[2]) <= STILL_PX:
                        return True
    return False


def drop_still_v2(frames):
    pts = [(i, d[0], d[1]) for i, c in enumerate(frames) for d in c]
    grid, by_frame = {}, {}
    for p in pts:
        grid.setdefault((int(p[1] // STILL_PX), int(p[2] // STILL_PX)), []).append(p)
        by_frame.setdefault(p[0], []).append(p)
    drop = set()
    for p in pts:
        cx, cy = int(p[1] // STILL_PX), int(p[2] // STILL_PX)
        n = sum(1 for gx in (cx - 1, cx, cx + 1) for gy in (cy - 1, cy, cy + 1) for q in grid.get((gx, gy), ())
                if q is not p and abs(q[0] - p[0]) <= WINDOW and math.hypot(q[1] - p[1], q[2] - p[2]) <= STILL_PX)
        if n < STILL_N - 1:
            continue
        if not _on_path(p, by_frame):
            drop.add(p)
    return [[d for d in c if (i, d[0], d[1]) not in drop] for i, c in enumerate(frames)]
