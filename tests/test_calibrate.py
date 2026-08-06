import random

import cv2
import numpy as np

from calibrate import POINTS, solve_assignment, compute_calibration


def _synthetic_clicks():
    """Project the 12 court points through a plausible behind-baseline
    homography to get pixel 'clicks' whose correct labels we know."""
    court = np.array([c for _, c in POINTS], dtype=np.float32)
    src = court[[0, 1, 2, 3]]  # NL, NR, FL, FR
    dst = np.array([(280, 690), (1010, 660), (470, 185), (805, 165)],
                   dtype=np.float32)  # asymmetric behind-baseline trapezoid, court ft -> px
    # (deliberately not left-right symmetric, so the correct assignment is unique)
    H, _ = cv2.findHomography(src, dst)
    proj = cv2.perspectiveTransform(court.reshape(-1, 1, 2), H).reshape(-1, 2)
    return [tuple(map(float, p)) for p in proj]


def test_solve_assignment_recovers_shuffled_order():
    in_order = _synthetic_clicks()
    shuffled = in_order[:]
    random.Random(0).shuffle(shuffled)
    ordered, rmse = solve_assignment(shuffled)
    assert rmse < 0.1
    for k in range(len(POINTS)):
        assert ordered[k] == in_order[k]


def test_compute_calibration_clean_on_ordered_points():
    out = compute_calibration(_synthetic_clicks())
    assert out["reprojection_rmse_ft"] < 0.1


def test_recovers_real_misordered_clicks():
    # The exact 12 points clicked on the PPA frame, in click order.
    # In click order these scored 28.18 ft RMSE; a valid assignment is ~0.5 ft.
    clicks = [(352, 327), (23, 642), (644, 634), (1253, 638),
              (940, 325), (648, 328), (644, 228), (446, 233),
              (848, 229), (798, 178), (646, 174), (492, 175)]
    ordered, rmse = solve_assignment(clicks)
    assert rmse < 1.0
    assert compute_calibration(ordered)["reprojection_rmse_ft"] < 1.0
    # orientation resolved correctly for a behind-baseline view:
    assert ordered[0][1] > ordered[2][1]   # near-left below far-left (larger image-y)
    assert ordered[0][0] < ordered[1][0]   # near-left left of near-right
