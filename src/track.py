"""Single-ball tracker: reject out-of-play ball detections by spatial continuity.

The crux problem (EXPERIMENTS 2026-08-10, benchmark 659-666s): in a multi-court
gym the detector finds real balls that aren't in play (adjacent courts, idle
balls). Taking "best ball anywhere per frame" makes the pick hop between them,
flipping sides = phantom crossings. This follows ONE ball: initialise on the
most confident detection, then each frame take the candidate nearest the last
tracked position within max_jump px; anything farther is a teleport (a different
ball) and is rejected.

On a re-check against the existing track (not the post-reset re-acquisition
path below), a candidate is accepted if it's within max_jump px of EITHER the
last confirmed position OR a PREDICTED position (last position plus tracked
velocity times frames elapsed) -- not the predicted position alone. Real ball
motion does two different things this has to handle: it reverses direction
sharply at every hit (every net crossing IS a reversal -- checked against
the existing near/far alternation test, which a predict-only version broke
outright, since the very first prediction after any crossing points the wrong
way), and it also, separately, sometimes needs to be picked back up further
along a straight path after several frames went undetected mid-flight (found
2026-09-04 on real footage, brickwall-SEMI rally_id 1 -- near-net dink
exchanges have short raw-detection dropouts, likely from occlusion/small
apparent size, and a last-position-only check was silently dropping genuine
net crossings that happened during those dropouts, fragmenting one continuous
rally into a lost lead-in plus a truncated report -- PIC-33's known symptom,
this is one real contributing mechanism, not the label lead-in issue tracked
separately as PIC-55). The last-position check alone (today's original
behavior) handles the first case fine, since a reversal doesn't teleport the
ball's *position* even though it flips its velocity; it just can't handle the
second case, where real elapsed distance grows with the gap. The predicted
check alone handles the second case but actively breaks the first, since
predicting through a reversal points away from where the ball actually went.
Checking both and accepting if either is close enough covers both real
behaviors without preferring one over the other.

A first attempt widened the flat radius via elapsed-frame scaling instead of
predicting at all (max_jump * sqrt(frames elapsed)) -- it recovered the
brickwall-SEMI case and improved aggregate recall/fp-rate/boundary-error
across 3 of 4 real test videos, but on the 4th (pb_draft_cup_30fps) it cost a
real quality:1 rally outright: a few frames of background clutter landed
inside the widened radius, pulled `last` onto the clutter, and then the real
ball -- reappearing right where it actually was -- fell outside the (now
wrongly anchored) radius and got lost for good. A radius alone, however wide,
can't distinguish "the ball, further along its real path" from "something
else, merely within some distance" -- prediction can, since real ball motion
continues near its established direction/speed through a short gap and
clutter doesn't line up with it. Checked against that same clutter case: the
prediction lands close to where the real ball reappears, and the three
clutter points do not, so this version correctly rejects them while still
keeping the real ball. Velocity is a simple two-point estimate (this
confirmed position minus the previous one, divided by frames elapsed) -- no
smoothing -- and is unavailable (falls back to comparing against the last
position alone) for exactly one point after a cold start or a reset, since a
direction needs two points to exist. The post-reset confirmation path
(pending, below) does not do any of this prediction -- it only ever has one
point to work from before a candidate is confirmed. Still needs a real
per-frame candidate for the gap counter itself to advance -- a multi-second
stretch with literally zero detections still resets after reset_after frames,
same as before.

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
    last_idx = None     # frame index the confirmed position came from
    last_vel = None      # (vx, vy) per-frame estimate from the last two confirmed
                          # points, or None when only one point is known so far
    pending = None      # (x, y, out_index) of an unconfirmed post-reset candidate
    has_tracked = False
    gap = 0
    for i, cands in enumerate(frames):
        if gap >= reset_after:
            last = None           # lost too long — allow re-acquire elsewhere
            last_idx = None
            last_vel = None
            pending = None        # ...and any stale unconfirmed candidate too
            gap = 0
        if not cands:
            out.append(None)
            xout.append(None)
            gap += 1
            continue
        if last is not None:
            elapsed = i - last_idx
            if last_vel is not None:
                pred = (last[0] + last_vel[0] * elapsed, last[1] + last_vel[1] * elapsed)
            else:
                pred = last        # only one confirmed point so far — no direction yet
            # nearest candidate to EITHER hypothesis: reversed off the last known
            # spot (a real hit, e.g. a net crossing, flips direction every time),
            # or continued past it (a real gap in detection, not a reversal).
            x, y, _ = min(cands, key=lambda d: min(
                (d[0] - last[0]) ** 2 + (d[1] - last[1]) ** 2,
                (d[0] - pred[0]) ** 2 + (d[1] - pred[1]) ** 2))
            dist_last = ((x - last[0]) ** 2 + (y - last[1]) ** 2) ** 0.5
            dist_pred = ((x - pred[0]) ** 2 + (y - pred[1]) ** 2) ** 0.5
            if min(dist_last, dist_pred) <= max_jump:
                last_vel = ((x - last[0]) / elapsed, (y - last[1]) / elapsed)
                last = (x, y)
                last_idx = i
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
            last_idx = i
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
            last_idx = i
            last_vel = ((x - px) / (i - pidx), (y - py) / (i - pidx))
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
