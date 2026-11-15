"""Candidate-choosing tracker for Test B (PIC-226). Experimental; NOT imported by the pipeline.

Same structure and gates as src/track.track_ball (max_jump, reset_after,
two-point re-acquisition confirmation) but the candidate in each frame is chosen
by a SCORE instead of "nearest to the last or predicted position":

    motion  = min( dist(c, predicted) / tol(gap),  dist(c, last) / tol0 )
              tol(gap) = tol0 + tol1 * frames since the last confirmed point
              (the second term is the hit-reversal allowance the original has)
    dwell   = number of EARLIER candidate detections (any candidate of any frame,
              not only chosen ones) within R px in the previous `window` frames
    penalty = 0 up to `free` repeats, then grows linearly; a candidate with
              `reject` or more repeats is not usable at all
    score   = motion + penalty

A fixed bright spot is always at distance zero from where it was a moment ago,
so a pure "nearest" rule prefers it; the dwell penalty is what makes a spot
that keeps reappearing cost something, while a ball in flight (never the same
few pixels twice) does not.
"""
import collections


def track_choose(frames, max_jump, reset_after=15, R=6.0, window=30, free=5, reject=15, tol0=20.0, tol1=10.0):
    out = []
    last = last_idx = last_vel = None
    pending = None
    has_tracked = False
    gap = 0
    hist = collections.deque()           # (frame, x, y) of all earlier candidates
    for i, cands in enumerate(frames):
        while hist and i - hist[0][0] > window:
            hist.popleft()
        scored = []
        for (x, y, c) in cands:
            d = sum(1 for (_, hx, hy) in hist if (x - hx) ** 2 + (y - hy) ** 2 <= R * R)
            scored.append((x, y, c, d))
        for (x, y, c) in cands:
            hist.append((i, x, y))
        usable = [(x, y, c, d) for (x, y, c, d) in scored if d < reject]
        if gap >= reset_after:
            last = last_idx = last_vel = pending = None
            gap = 0
        if not usable:
            out.append(None)
            gap += 1
            continue

        def penalty(d):
            return max(0.0, d - free) / max(1.0, free)

        if last is not None:
            elapsed = i - last_idx
            pred = (last[0] + last_vel[0] * elapsed, last[1] + last_vel[1] * elapsed) if last_vel is not None else last
            tol = tol0 + tol1 * elapsed
            def score(cd):
                x, y, c, d = cd
                dp = ((x - pred[0]) ** 2 + (y - pred[1]) ** 2) ** 0.5
                dl = ((x - last[0]) ** 2 + (y - last[1]) ** 2) ** 0.5
                return min(dp / tol, dl / tol0) + penalty(d)
            x, y, _, _ = min(usable, key=score)
            dist = min(((x - pred[0]) ** 2 + (y - pred[1]) ** 2) ** 0.5, ((x - last[0]) ** 2 + (y - last[1]) ** 2) ** 0.5)
            if dist <= max_jump:
                last_vel = ((x - last[0]) / elapsed, (y - last[1]) / elapsed)
                last, last_idx, gap = (x, y), i, 0
                out.append(y)
            else:
                out.append(None)
                gap += 1
            continue
        if not has_tracked:
            x, y, _, _ = min(usable, key=lambda cd: (cd[3], -cd[2]))      # least-repeated, then most confident
            last, last_idx, has_tracked, gap = (x, y), i, True, 0
            out.append(y)
            continue
        if pending is None:
            x, y, _, _ = min(usable, key=lambda cd: (cd[3], -cd[2]))
            pending = (x, y, i)
            out.append(None)
            gap = 0
            continue
        px, py, pidx = pending
        x, y, _, _ = min(usable, key=lambda cd: (cd[0] - px) ** 2 + (cd[1] - py) ** 2)
        if ((x - px) ** 2 + (y - py) ** 2) ** 0.5 <= max_jump:
            out[pidx] = py
            last_vel = ((x - px) / (i - pidx), (y - py) / (i - pidx))
            last, last_idx, pending, gap = (x, y), i, None, 0
            out.append(y)
        else:
            x2, y2, _, _ = min(usable, key=lambda cd: (cd[3], -cd[2]))
            pending = (x2, y2, i)
            out.append(None)
            gap = 0
    return out
