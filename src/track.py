"""Single-ball tracker: reject out-of-play ball detections by spatial continuity.

The crux problem (EXPERIMENTS 2026-08-10, benchmark 659-666s): in a multi-court
gym the detector finds real balls that aren't in play (adjacent courts, idle
balls). Taking "best ball anywhere per frame" makes the pick hop between them,
flipping sides = phantom crossings. This follows ONE ball: initialise on the
most confident detection, then each frame take the candidate nearest the last
tracked position within max_jump px; anything farther is a teleport (a different
ball) and is rejected. Needs dense (per-frame) detections so real ball motion
stays under max_jump between frames.

Re-acquisition after a reset requires confirmation (see track_ball docstring):
a single stray candidate right after a reset used to be accepted with zero
validation, letting a one-frame spurious detection hijack the track and chain
forward from there (found 2026-08-16 on real footage — see project memory
project-tracknet-false-positive, "within-court noise" section). The initial
cold start (very first frame ever) still accepts immediately, since there is
no prior track to protect and a bad pick there is just a normal teleport-reject
away from being corrected."""


def track_ball(frames, max_jump, reset_after=15, min_seg_frames=None,
               min_seg_span=None, return_x=False):
    """frames: per-frame candidate lists, each [(x, y, conf), ...] (empty if no
    detection). Returns [y or None] per frame — the tracked ball's image-y, with
    teleporting/out-of-play detections dropped. After reset_after consecutive
    gaps the track is released so a genuinely new rally can be re-acquired —
    but re-acquisition needs a second, spatially-close candidate within
    reset_after frames to confirm before it's accepted (the first candidate is
    held as `pending` and backfilled once confirmed).

    min_seg_frames / min_seg_span: if given, a confirmed run between resets
    ("segment") is dropped entirely when it's shorter than min_seg_frames
    frames, or when its bounding-box diagonal (max x spread and y spread
    combined) is under min_seg_span px. Targets two cases confirmation alone
    doesn't catch, because each is a smooth, self-consistent trajectory in its
    own right: a ball resting on the floor (near-zero movement over a long
    stretch) and a sparsely-visible adjacent-court ball (often only a handful
    of confirmed frames before the next gap). Off by default (None) to keep
    existing behavior unchanged.

    return_x: the tracked x was always computed in lockstep with y (same
    teleport-rejection, post-reset confirmation, and segment pruning), just
    never returned (PIC-27) -- every caller had to fall back to raw,
    unconfirmed x from the predictions CSV for anything needing a real 2-D
    trajectory. Off by default so every existing caller's return shape is
    unchanged; pass True to get (ys, xs) instead of just ys."""
    out = []
    xout = []          # parallel x-track, used only for segment pruning below
    last = None        # (x, y) of the confirmed tracked ball
    pending = None      # (x, y, out_index) of an unconfirmed post-reset candidate
    has_tracked = False
    gap = 0
    for i, cands in enumerate(frames):
        if gap >= reset_after:
            last = None           # lost too long — allow re-acquire elsewhere
            pending = None        # ...and any stale unconfirmed candidate too
            gap = 0
        if not cands:
            out.append(None)
            xout.append(None)
            gap += 1
            continue
        if last is not None:
            x, y, _ = min(cands, key=lambda d: (d[0] - last[0]) ** 2 + (d[1] - last[1]) ** 2)
            if ((x - last[0]) ** 2 + (y - last[1]) ** 2) ** 0.5 <= max_jump:
                last = (x, y)
                gap = 0
                out.append(y)
                xout.append(x)
            else:
                out.append(None)     # nearest candidate is too far — reject teleport
                xout.append(None)
                gap += 1
            continue
        if not has_tracked:
            # cold start: no prior track to protect against a bad pick — accept
            x, y, _ = max(cands, key=lambda d: d[2])   # start on most confident
            last = (x, y)
            has_tracked = True
            gap = 0
            out.append(y)
            xout.append(x)
            continue
        # post-reset: require a second nearby candidate before trusting this one
        if pending is None:
            x, y, _ = max(cands, key=lambda d: d[2])
            pending = (x, y, i)
            out.append(None)
            xout.append(None)
            gap = 0
            continue
        px, py, pidx = pending
        x, y, _ = min(cands, key=lambda d: (d[0] - px) ** 2 + (d[1] - py) ** 2)
        if ((x - px) ** 2 + (y - py) ** 2) ** 0.5 <= max_jump:
            out[pidx] = py         # confirmed — backfill the pending frame
            xout[pidx] = px
            last = (x, y)
            pending = None
            gap = 0
            out.append(y)
            xout.append(x)
        else:
            # doesn't confirm the old pending — treat this as a fresh candidate
            x2, y2, _ = max(cands, key=lambda d: d[2])
            pending = (x2, y2, i)
            out.append(None)
            xout.append(None)
            gap = 0

    if min_seg_frames is not None or min_seg_span is not None:
        out = _prune_weak_segments(out, xout, min_seg_frames, min_seg_span)
        xout = [x if y is not None else None for x, y in zip(xout, out)]
    return (out, xout) if return_x else out


def _prune_weak_segments(ys, xs, min_frames, min_span):
    """Drop confirmed segments (maximal runs of non-None values) that are
    either too short (min_frames) or too spatially static (min_span, the
    bounding-box diagonal of the segment's positions) to trust."""
    n = len(ys)
    out = list(ys)
    i = 0
    while i < n:
        if out[i] is None:
            i += 1
            continue
        j = i
        while j < n and out[j] is not None:
            j += 1
        drop = min_frames is not None and (j - i) < min_frames
        if not drop and min_span is not None:
            seg_xs, seg_ys = xs[i:j], ys[i:j]
            dx = max(seg_xs) - min(seg_xs)
            dy = max(seg_ys) - min(seg_ys)
            drop = (dx * dx + dy * dy) ** 0.5 < min_span
        if drop:
            for k in range(i, j):
                out[k] = None
        i = j
    return out
