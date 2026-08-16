from src.track import track_ball


def test_follows_smooth_ball_ignores_distractor():
    # in-play ball moves smoothly down column x=100; a distractor sits far at x=900
    frames = [
        [(100, 150, 0.9), (900, 50, 0.5)],
        [(100, 100, 0.9), (900, 50, 0.5)],
        [(100, 50, 0.9), (900, 50, 0.5)],
    ]
    assert track_ball(frames, max_jump=100) == [150, 100, 50]


def test_rejects_teleport_to_far_ball():
    # start on one ball; next frame only a far ball exists -> reject, emit gap
    frames = [[(900, 60, 0.9)], [(100, 150, 0.9)]]
    assert track_ball(frames, max_jump=100) == [60, None]


def test_empty_frames_are_gaps():
    assert track_ball([[], []], max_jump=100) == [None, None]


def test_reacquires_after_long_gap_once_confirmed():
    # lose the ball for reset_after frames; a candidate elsewhere needs a second,
    # spatially-close frame to confirm before it's trusted as the re-acquired ball
    frames = ([[(900, 60, 0.9)]] + [[]] * 15
              + [[(100, 150, 0.9)], [(105, 155, 0.9)]])
    ys = track_ball(frames, max_jump=100, reset_after=15)
    assert ys[0] == 60
    assert ys[-2] == 150   # backfilled once the second frame confirmed it
    assert ys[-1] == 155


def test_single_spurious_blip_after_reset_is_not_accepted():
    # a lone candidate right after a reset must NOT hijack the track with zero
    # validation -- this is the exact false-positive mechanism found 2026-08-16
    # on real footage (see project memory: project-tracknet-false-positive,
    # "within-court noise" section) -- a one-frame spurious detection (e.g. a
    # wall feature, a shoe) slipping through and chaining forward from there.
    frames = ([[(900, 60, 0.9)]] + [[]] * 15
              + [[(100, 150, 0.9)]] + [[]] * 5)
    ys = track_ball(frames, max_jump=100, reset_after=15)
    assert ys[0] == 60
    assert all(y is None for y in ys[1:])   # spurious blip never confirmed
