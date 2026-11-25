import numpy as np
import pytest

from src.two_ball import two_ball_rate

# Identity-like calibration: video pixels are court feet, so tracks read directly.
CALIB = {"calibration_resolution": [20, 44], "homography": np.eye(3).tolist()}
SIZE = (20, 44)
FPS = 30.0


def track(xs, start=0.0):
    return [(start + i / FPS, x, 22.0, None, None, None) if x is not None else (start + i / FPS, None, None, None, None, None)
            for i, x in enumerate(xs)]


def test_one_ball_crossing_court_is_not_a_jump():
    one_ball = track([4 + i * 0.4 for i in range(30)])  # 12 ft in a second, smoothly
    assert two_ball_rate(one_ball, 0, 1, CALIB, SIZE, FPS) == 0


def test_two_balls_alternating_across_the_centre_count_every_switch():
    two_balls = track([3, 17] * 15)  # left pair's ball, right pair's ball, every frame
    assert two_ball_rate(two_balls, 0, 1, CALIB, SIZE, FPS) == pytest.approx(29)


def test_jumps_inside_one_half_are_not_counted():
    same_side = track([1, 9] * 15)
    assert two_ball_rate(same_side, 0, 1, CALIB, SIZE, FPS) == 0


def test_detections_far_apart_in_time_are_not_compared():
    gap = track([3, None, None, None, 17])
    assert two_ball_rate(gap, 0, 1, CALIB, SIZE, FPS) == 0


def test_only_the_clip_window_is_counted():
    t = track([3, 17] * 30)  # 2 s of jumps
    assert two_ball_rate(t, 0, 2, CALIB, SIZE, FPS) == pytest.approx(59 / 2)
    assert two_ball_rate(t, 0, 1, CALIB, SIZE, FPS) == pytest.approx(30)


def test_video_scaled_to_the_calibration():
    # Video at twice the calibration's pixels: x=6 and x=34 px are court 3 and 17 ft.
    t = [(i / FPS, (6.0, 34.0)[i % 2], 44.0, None, None, None) for i in range(30)]
    assert two_ball_rate(t, 0, 1, CALIB, (40, 88), FPS) == pytest.approx(29)


def test_empty_window():
    assert two_ball_rate(track([3, 17]), 5, 5, CALIB, SIZE, FPS) is None
