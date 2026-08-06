import json

import cv2
import numpy as np

from src.players import foot_point, to_court, load_calibration, frame_step


def test_frame_step_subsamples():
    assert frame_step(30, 5) == 6      # 30fps sampled at 5fps -> every 6th frame
    assert frame_step(30, 30) == 1     # same rate -> every frame
    assert frame_step(30, 60) == 1     # never below 1


def test_foot_point_is_bottom_center():
    assert foot_point((10, 20, 30, 80)) == (20.0, 80.0)


def test_to_court_projects_pixel_to_court_feet():
    court = np.array([(0, 0), (20, 0), (0, 44), (20, 44)], np.float32)
    img = np.array([(300, 680), (1000, 660), (470, 185), (805, 165)], np.float32)
    h_img2court, _ = cv2.findHomography(img, court)  # image px -> court ft
    x, y = to_court([(805, 165)], h_img2court)[0]     # this pixel is court corner (20, 44)
    assert abs(x - 20.0) < 0.5 and abs(y - 44.0) < 0.5


def test_load_calibration_returns_homography(tmp_path):
    h = [[1.0, 0.0, 2.0], [0.0, 1.0, 3.0], [0.0, 0.0, 1.0]]
    p = tmp_path / "calib.json"
    p.write_text(json.dumps({"homography": h}))
    loaded = load_calibration(str(p))
    assert loaded.shape == (3, 3)
    assert loaded[0][2] == 2.0
