import json
import math

import numpy as np

from src.court_crop import court_crop_box, grid_to_calibration

# PDSC Court 3's calibration: clicked on a 2880x1620 live snapshot.
COURT3 = {"calibration_resolution": [2880, 1620], "image_points": [
    [674.2, 1228.2], [2209.0, 1243.9], [1170.1, 757.4], [1700.5, 766.8], [966.1, 945.7], [1910.8, 961.4],
    [1097.9, 829.6], [1775.9, 842.2], [1452.6, 1284.7], [1433.7, 760.6], [1443.2, 964.6], [1433.7, 839.0]]}
GRID = (512, 288)


def test_the_box_is_inside_the_frame_and_sixteen_by_nine():
    for shape in ((1080, 1920, 3), (720, 1280, 3), (1620, 2880, 3)):
        x0, y0, x1, y1 = court_crop_box(COURT3, shape)
        assert 0 <= x0 < x1 <= shape[1] and 0 <= y0 < y1 <= shape[0]
        assert math.isclose((x1 - x0) / (y1 - y0), 16 / 9, rel_tol=0.01)


def test_the_box_holds_every_clicked_court_point_and_the_airspace_above_the_far_baseline():
    shape = (1080, 1920, 3)
    x0, y0, x1, y1 = court_crop_box(COURT3, shape)
    for x, y in COURT3["image_points"]:
        px, py = x * 1920 / 2880, y * 1080 / 1620
        assert x0 <= px <= x1 and y0 <= py <= y1
    far_y = min(p[1] for p in COURT3["image_points"]) * 1080 / 1620
    near_y = max(p[1] for p in COURT3["image_points"]) * 1080 / 1620
    assert y0 <= far_y - 0.7 * (near_y - far_y)            # the court gate's whole airspace


def test_the_box_is_the_same_court_at_any_resolution_of_the_same_view():
    a = court_crop_box(COURT3, (1080, 1920, 3))
    b = court_crop_box(COURT3, (1620, 2880, 3))
    assert all(abs(p * 1.5 - q) <= 3 for p, q in zip(a, b))


def test_a_calibration_without_a_resolution_is_read_in_the_videos_own_pixels():
    own = {"image_points": [[x * 1920 / 2880, y * 1080 / 1620] for x, y in COURT3["image_points"]]}
    assert court_crop_box(own, (1080, 1920, 3)) == court_crop_box(COURT3, (1080, 1920, 3))


def test_a_court_that_fills_the_frame_gets_the_whole_frame():
    full = {"image_points": [[0, 0], [1919, 0], [0, 1079], [1919, 1079]]}
    assert court_crop_box(full, (1080, 1920, 3)) == (0, 0, 1920, 1080)


def test_a_point_on_the_grid_maps_back_to_the_pixel_it_came_from():
    shape, cal = (1080, 1920, 3), (2880, 1620)
    box = court_crop_box(COURT3, shape)
    x0, y0, x1, y1 = box
    rng = np.random.default_rng(1)
    for _ in range(50):
        vx, vy = rng.uniform(x0, x1), rng.uniform(y0, y1)                 # a ball in video pixels inside the crop
        gx, gy = (vx - x0) * GRID[0] / (x1 - x0), (vy - y0) * GRID[1] / (y1 - y0)   # where the model sees it
        cx, cy = grid_to_calibration(gx, gy, box, GRID, shape, cal)
        assert math.isclose(cx, vx * 2880 / 1920, abs_tol=1e-6) and math.isclose(cy, vy * 1620 / 1080, abs_tol=1e-6)


def test_without_a_box_the_mapping_is_the_old_whole_frame_scaling():
    shape, cal = (1080, 1920, 3), (2880, 1620)
    cx, cy = grid_to_calibration(100, 50, None, GRID, shape, cal)
    assert math.isclose(cx, 100 * 2880 / 512) and math.isclose(cy, 50 * 1620 / 288)
    cx, cy = grid_to_calibration(100, 50, None, GRID, shape, None)         # no calibration resolution: video pixels
    assert math.isclose(cx, 100 * 1920 / 512) and math.isclose(cy, 50 * 1080 / 288)
