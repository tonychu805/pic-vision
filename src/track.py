"""Single-ball tracker: reject out-of-play ball detections by spatial continuity.

The crux problem (EXPERIMENTS 2026-08-10, benchmark 659-666s): in a multi-court
gym the detector finds real balls that aren't in play (adjacent courts, idle
balls). Taking "best ball anywhere per frame" makes the pick hop between them,
flipping sides = phantom crossings. This follows ONE ball: initialise on the
most confident detection, then each frame take the candidate nearest the last
tracked position within max_jump px; anything farther is a teleport (a different
ball) and is rejected. Needs dense (per-frame) detections so real ball motion
stays under max_jump between frames."""


def track_ball(frames, max_jump, reset_after=15):
    """frames: per-frame candidate lists, each [(x, y, conf), ...] (empty if no
    detection). Returns [y or None] per frame — the tracked ball's image-y, with
    teleporting/out-of-play detections dropped. After reset_after consecutive
    gaps the track is released so a genuinely new rally can be re-acquired."""
    out = []
    last = None      # (x, y) of the tracked ball
    gap = 0
    for cands in frames:
        if last is not None and gap >= reset_after:
            last = None          # lost too long — allow re-acquire elsewhere
            gap = 0
        if not cands:
            out.append(None)
            gap += 1
            continue
        if last is None:
            x, y, _ = max(cands, key=lambda d: d[2])   # start on most confident
            last = (x, y)
            gap = 0
            out.append(y)
            continue
        x, y, _ = min(cands, key=lambda d: (d[0] - last[0]) ** 2 + (d[1] - last[1]) ** 2)
        if ((x - last[0]) ** 2 + (y - last[1]) ** 2) ** 0.5 <= max_jump:
            last = (x, y)
            gap = 0
            out.append(y)
        else:
            out.append(None)     # nearest candidate is too far — reject teleport
            gap += 1
    return out
