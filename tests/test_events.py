from src.events import mean_motion, motion_series, n_at_kitchen, kitchen_series


def test_n_at_kitchen_counts_players_near_nvz_lines():
    # near-kitchen (y=14), far-kitchen (y=30), near-baseline (y=5), far-baseline (y=40)
    pos = [(10, 14), (10, 30), (10, 5), (10, 40)]
    assert n_at_kitchen(pos) == 2


def test_kitchen_series_is_per_frame():
    tracks = [(0.0, [(10, 15), (10, 29)]), (0.2, [(10, 5)])]
    assert kitchen_series(tracks) == [(0.0, 2), (0.2, 0)]


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
