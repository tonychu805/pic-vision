from src.track import track_ball, max_jump_for_fps, reset_after_for_fps


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


def test_return_x_default_off_keeps_existing_return_shape():
    frames = [[(100, 150, 0.9)], [(100, 100, 0.9)]]
    assert track_ball(frames, max_jump=100) == [150, 100]


def test_return_x_gives_tracked_x_in_lockstep_with_y():
    # distractor at x=900 must not leak into the tracked x any more than into y
    frames = [
        [(100, 150, 0.9), (900, 50, 0.5)],
        [(100, 100, 0.9), (900, 50, 0.5)],
        [(100, 50, 0.9), (900, 50, 0.5)],
    ]
    ys, xs = track_ball(frames, max_jump=100, return_x=True)
    assert ys == [150, 100, 50]
    assert xs == [100, 100, 100]


def test_return_x_gaps_and_backfill_match_between_y_and_x():
    frames = ([[(900, 60, 0.9)]] + [[]] * 15
              + [[(100, 150, 0.9)], [(105, 155, 0.9)]])
    ys, xs = track_ball(frames, max_jump=100, reset_after=15, return_x=True)
    assert ys[0] == 60 and xs[0] == 900
    assert all(y is None for y in ys[1:-2]) and all(x is None for x in xs[1:-2])
    assert ys[-2] == 150 and xs[-2] == 100   # backfilled together
    assert ys[-1] == 155 and xs[-1] == 105


def test_return_x_pruned_segment_drops_x_too():
    # a short confirmed segment pruned by min_seg_frames must drop its x
    # alongside its y, not leave a dangling x with no matching y
    frames = ([[(100, 150, 0.9)]] + [[]] * 15  # 1-frame segment: gets pruned
              + [[(500, 300, 0.9)], [(505, 305, 0.9)], [(510, 310, 0.9)]])  # 3 frames: kept
    ys, xs = track_ball(frames, max_jump=100, reset_after=15,
                         min_seg_frames=3, return_x=True)
    assert ys[0] is None and xs[0] is None   # first segment (1 frame) pruned
    assert ys[-1] == 310 and xs[-1] == 510   # second segment (3 frames) kept


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


# --- frame-rate-aware thresholds (ADR-086) ---------------------------------
# max_jump is "how far can the ball move between two frames" -- a speed, not a
# distance. It was a flat 150 px/frame tuned entirely on 30fps footage, which
# silently rejected genuine fast-ball motion on a 15fps camera (real: Court 1,
# measured at 15.00 fps -- 9,000 frames in 600s).

def test_30fps_thresholds_are_unchanged():
    # The whole change must be a no-op for every video scored so far, or every
    # tuned parameter and recorded precision/recall number is invalidated.
    assert max_jump_for_fps(30) == 150.0
    assert reset_after_for_fps(30) == 15


def test_half_frame_rate_doubles_the_jump_allowance():
    # At 15fps the ball genuinely travels twice as far between frames.
    assert max_jump_for_fps(15) == 300.0


def test_reset_after_holds_constant_in_seconds_not_frames():
    # 0.5s of missing detections, whatever the frame rate.
    assert reset_after_for_fps(15) == 8      # round(0.5 * 15)
    assert reset_after_for_fps(60) == 30


def test_missing_or_absurd_fps_falls_back_to_30fps_behaviour():
    # A failed probe must degrade to today's behaviour, never to an absurd
    # radius that would accept any background clutter on the frame.
    for bad in (None, 0, -5):
        assert max_jump_for_fps(bad) == 150.0
        assert reset_after_for_fps(bad) == 15


def test_fast_ball_at_15fps_is_kept_but_would_be_lost_at_the_old_flat_threshold():
    # 200px per frame: real motion for a hard drive at 15fps, impossible at 30.
    frames = [[(100, 100, 0.9)], [(300, 100, 0.9)], [(500, 100, 0.9)]]
    assert track_ball(frames, max_jump=150) == [100, None, None]          # old behaviour: dropped
    assert track_ball(frames, max_jump=max_jump_for_fps(15)) == [100, 100, 100]   # kept
