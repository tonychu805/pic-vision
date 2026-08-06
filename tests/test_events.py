from src.events import mean_motion, motion_series


def test_mean_motion_single_player():
    assert mean_motion([(0.0, 0.0)], [(3.0, 4.0)]) == 5.0


def test_mean_motion_empty_frame_is_zero():
    assert mean_motion([], [(1.0, 1.0)]) == 0.0
    assert mean_motion([(1.0, 1.0)], []) == 0.0


def test_mean_motion_matches_nearest():
    prev = [(0.0, 0.0), (10.0, 10.0)]
    cur = [(0.0, 1.0), (10.0, 11.0)]  # each moved 1 ft from its nearest
    assert mean_motion(prev, cur) == 1.0


def test_motion_series_length_and_times():
    tracks = [(0.0, [(0.0, 0.0)]), (0.2, [(1.0, 0.0)]), (0.4, [(1.0, 0.0)])]
    s = motion_series(tracks)
    assert [t for t, _ in s] == [0.2, 0.4]
    assert s[0][1] == 1.0 and s[1][1] == 0.0
