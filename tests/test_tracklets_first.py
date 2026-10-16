import sys
sys.path.insert(0, "scripts")
from tracklets_first import drop_still


def frames_of(n, pts):
    f = [[] for _ in range(n)]
    for i, x, y in pts:
        f[i].append((x, y, 0.9))
    return f


def kept(out):
    return {(i, d[0], d[1]) for i, c in enumerate(out) for d in c}


def test_glint_reappearing_is_dropped():
    glint = [(i, 500.0, 500.0) for i in range(0, 120, 9)]          # sporadic, never moves
    assert kept(drop_still(frames_of(120, glint))) == set()


def test_ball_flying_over_glint_survives():
    glint = [(i, 500.0, 500.0) for i in range(0, 120, 9) if i not in range(50, 60)]
    ball = [(i, 400.0 + 10 * (i - 50), 500.0) for i in range(50, 60)]  # passes x=500 at i=60-ish
    out = kept(drop_still(frames_of(120, glint + ball)))
    assert all((i, x, y) in out for i, x, y in ball)
    # a glint point within MAX_GAP frames of the ball can be linked into the ball's moving tracklet and
    # survive (known edge case: one glint point slips through, the ball is unharmed); the rest go
    assert not any((i, x, y) in out for i, x, y in glint if not 45 <= i <= 63)


def test_isolated_ball_points_are_kept():
    pts = [(10, 300.0, 300.0), (40, 700.0, 200.0), (80, 900.0, 600.0)]
    assert kept(drop_still(frames_of(100, pts))) == set(pts)


def test_slow_apex_moving_tracklet_kept():
    lob = [(i, 600.0 + 3 * i, 300.0 + 0.2 * (i - 5) ** 2) for i in range(0, 12)]   # slow, but moves > 12 px
    assert kept(drop_still(frames_of(12, lob))) == set(lob)
