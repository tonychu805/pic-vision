import sys
sys.path.insert(0, "scripts")
from track_choose import track_choose


def frames_with(ball, spot=None, n=40):
    """ball: fn(i)->(x,y) or None; spot: fixed (x,y) detected every frame."""
    out = []
    for i in range(n):
        c = []
        b = ball(i)
        if b is not None:
            c.append((b[0], b[1], 0.55))
        if spot is not None:
            c.append((spot[0], spot[1], 0.62))      # the spot is MORE confident than the ball
        out.append(c)
    return out


def test_registered_parameters_leave_a_fixed_spot_only_after_it_repeats_15_times():
    # Behaviour of the pre-registered setting (free 5, reject 15): at cold start the more
    # confident spot is taken, it is dropped once it has repeated 15 times, and the tracker
    # then re-acquires the moving ball. Slow, but it does get there.
    ball = lambda i: (300.0 + 12 * i, 400.0 - 4 * i)
    ys = track_choose(frames_with(ball, spot=(330.0, 380.0)), max_jump=150)
    on_spot = [i for i, y in enumerate(ys) if y == 380.0]
    assert on_spot and max(on_spot) < 20          # nothing on the spot after it is rejected
    tracked = [y for y in ys if y is not None]
    assert tracked[-1] < 300                       # and it ends up following the ball


def test_density_adjusted_parameters_prefer_the_ball_within_a_few_frames():
    # Detection density is ~20-30% of frames, so 15 repeats in 30 frames is rarely reachable;
    # the adjusted variant (free 1, reject 4) must leave the spot in a few frames.
    ball = lambda i: (300.0 + 12 * i, 400.0 - 4 * i)
    ys = track_choose(frames_with(ball, spot=(330.0, 380.0)), max_jump=150, free=1, reject=4)
    on_spot = [i for i, y in enumerate(ys) if y == 380.0]
    assert max(on_spot, default=-1) < 8
    assert sum(1 for y in ys[10:] if y is not None) >= 25


def test_a_ball_slowing_at_the_top_of_an_arc_is_not_rejected():
    # moves, then hovers within 2 px for 4 frames, then moves on
    def ball(i):
        if i < 10:
            return (100.0 + 10 * i, 300.0 - 5 * i)
        if i < 14:
            return (200.0 + 0.5 * (i - 10), 250.0)
        return (200.0 + 10 * (i - 13), 250.0 + 5 * (i - 13))
    ys = track_choose(frames_with(ball, n=30), max_jump=150)
    assert sum(1 for y in ys if y is not None) >= 25


def test_a_hit_that_reverses_direction_is_followed():
    def ball(i):
        return (100.0 + 15 * i, 300.0) if i < 10 else (250.0 - 15 * (i - 10), 300.0)
    ys = track_choose(frames_with(ball, n=22), max_jump=150)
    assert sum(1 for y in ys if y is not None) >= 18


def test_a_spot_reappearing_many_times_is_eventually_unusable():
    spot = (500.0, 300.0)
    ys = track_choose([[(spot[0], spot[1], 0.9)] for _ in range(40)], max_jump=150, free=5, reject=15)
    # a lone fixed spot starts tracked, then stops being usable once it has repeated 15 times
    assert ys[-1] is None


def test_no_candidates_gives_none():
    assert track_choose([[], [], []], max_jump=150) == [None, None, None]
