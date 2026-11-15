import sys
sys.path.insert(0, ".")
import numpy as np
from src.bounce_eval import court_error_ft, near_half, nearest_point, pick_sample, project, recover

# a synthetic homography: 10 px = 1 ft, no perspective
H = np.array([[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1.0]])


def test_project_and_error():
    assert project(H, 100, 220) == (10.0, 22.0)
    assert abs(court_error_ft(H, (0, 0), (30, 40)) - 5.0) < 1e-9


def test_nearest_point_window():
    pts = {10: (1, 1), 14: (2, 2)}
    assert nearest_point(pts, 12, tol=3) == (1, 1)   # 10 and 14 both 2 away; first wins
    assert nearest_point(pts, 20, tol=3) is None


def test_recover_found_seen_and_missing():
    label = {"frame": 100, "x": 50.0, "y": 50.0, "visible": True}
    near = {101: (55.0, 50.0)}
    r = recover(label, raw=near, tracked=near, cands=near, H=H)
    assert r["seen"] and r["tracked"] and r["found"]
    assert abs(r["cand_err_ft"] - 0.5) < 1e-9
    far = {101: (200.0, 50.0)}   # a candidate 15 ft away does not count as found
    r = recover(label, raw=far, tracked=far, cands=far, H=H)
    assert r["seen"] and not r["found"] and r["cand_err_ft"] > 10
    r = recover(label, raw={}, tracked={}, cands={}, H=H)
    assert not (r["seen"] or r["tracked"] or r["found"]) and r["tracked_err_ft"] is None


def test_near_half_and_sample_is_reproducible():
    assert near_half(H, 10, 100) and not near_half(H, 10, 300)
    pool = list(range(50))
    assert pick_sample(pool, 10, seed=1) == pick_sample(pool, 10, seed=1)
    assert len(set(pick_sample(pool, 10, seed=1))) == 10
