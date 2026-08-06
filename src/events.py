"""Dead-time / live-play markers from player court tracks (ADR-026, ADR-037).

First slice: a motion signal. It's the cheapest discriminator and it directly
probes the two hard cases — lobs (high motion, live) and dinks (low motion,
live). More markers (net-crossing, kitchen presence, ball) get added as
Phase 0.6 shows which are worth keeping."""

import numpy as np


def mean_motion(prev, cur):
    """Mean nearest-neighbour displacement (ft) of players between two frames —
    a tracking-free proxy for how much the players are moving. Each current
    player is matched to its nearest previous position."""
    if not prev or not cur:
        return 0.0
    p = np.array(prev, dtype=float)
    c = np.array(cur, dtype=float)
    d = np.linalg.norm(c[:, None, :] - p[None, :, :], axis=2)
    return float(d.min(axis=1).mean())


def motion_series(tracks):
    """Per-frame (time_sec, mean_motion_ft) from court-position tracks
    [(time, [(x, y), ...]), ...]."""
    out = []
    for i in range(1, len(tracks)):
        (_, prev), (t, cur) = tracks[i - 1], tracks[i]
        out.append((t, mean_motion(prev, cur)))
    return out
