from scripts.ball_trail_overlay import gated_points, trail_segments


def _track(rows):
    # (x, y, conf) or None per frame -> load_predictions-shaped tuples
    return [(i / 30.0,) + ((r[0], r[1], 5, 5, r[2]) if r else (None,) * 5)
            for i, r in enumerate(rows)]


def test_gate_drops_off_court_and_low_conf_but_keeps_missing_conf():
    track = _track([(10, 10, 0.9), (500, 10, 0.9), (20, 20, 0.1), (30, 30, None), None])
    pts = gated_points(track, lambda x, y: x < 100, min_conf=0.5)
    assert pts == [(10, 10), None, None, (30, 30), None]


def test_adjacent_frames_are_joined():
    pts = [(0, 0), (5, 0), (10, 0)]
    segs = trail_segments(pts, 2, trail_frames=10)
    assert [(a, b) for a, b, _ in segs] == [((5, 0), (10, 0)), ((0, 0), (5, 0))]


def test_occlusion_gap_is_not_interpolated():
    pts = [(0, 0), None, (10, 0)]
    assert trail_segments(pts, 2, trail_frames=10, max_gap_frames=1) == []


def test_jump_breaks_trail():
    pts = [(0, 0), (400, 0)]
    assert trail_segments(pts, 1, trail_frames=10, max_jump=150) == []


def test_trail_respects_length():
    pts = [(i, 0) for i in range(20)]
    segs = trail_segments(pts, 19, trail_frames=3)
    assert len(segs) == 3
