import sys
sys.path.insert(0, "scripts")
from tracklets_first import drop_still, drop_still_v2


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


def test_v2_glint_chained_with_ball_is_still_dropped():
    # glare on every other frame interleaved with a ball nearby: v1 chains them; v2 drops the glare
    glint = [(i, 500.0, 500.0) for i in range(0, 60, 2)]
    ball = [(i, 300.0 + 8 * i, 400.0) for i in range(1, 60, 2)]
    out = kept(drop_still_v2(frames_of(60, glint + ball)))
    assert all(p in out for p in ball)
    assert sum(p in out for p in glint) <= 2


def test_v2_ball_flying_over_glint_survives():
    # the ball passes through the glare site (x=500 at i=60) and continues. Known limit, not tested: a ball
    # whose LAST detection lands on a glare site has no "after" point and is dropped.
    glint = [(i, 500.0, 500.0) for i in range(0, 120, 9) if i not in range(50, 71)]
    ball = [(i, 400.0 + 10 * (i - 50), 500.0) for i in range(50, 71)]
    out = kept(drop_still_v2(frames_of(120, glint + ball)))
    assert all(p in out for p in ball)


def test_v2_isolated_ball_points_kept():
    pts = [(10, 300.0, 300.0), (40, 700.0, 200.0), (80, 900.0, 600.0)]
    assert kept(drop_still_v2(frames_of(100, pts))) == set(pts)
