from scripts.ball_court_map import (COURT_H, COURT_W, MARGIN_FT, court_to_px,
                                    project_points)

IDENTITY = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


def test_project_identity_keeps_on_court_points():
    pts = [(5.0, 10.0), None, (20.0, 44.0)]
    assert project_points(pts, IDENTITY) == [(5.0, 10.0), None, (20.0, 44.0)]


def test_points_far_outside_court_are_dropped_but_runoff_is_kept():
    pts = [(-MARGIN_FT, 0.0), (COURT_W + MARGIN_FT + 1, 5.0), (3.0, COURT_H + MARGIN_FT + 1)]
    out = project_points(pts, IDENTITY)
    assert out[0] == (-MARGIN_FT, 0.0)
    assert out[1] is None and out[2] is None


def test_near_baseline_is_drawn_at_the_bottom():
    _, y_near = court_to_px(10, 0, scale=10, pad=0)
    _, y_far = court_to_px(10, COURT_H, scale=10, pad=0)
    assert y_near > y_far
