import sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
from track_score_windows import drop_non_flight


def _n(n=60):
    return [None] * n, [None] * n


def test_sitting_dot_is_dropped():
    ys, xs = _n()
    for i in range(0, 45, 2):
        ys[i], xs[i] = 300.0 + (i % 2), 500.0
    out = drop_non_flight(ys, xs)
    assert all(v is None for v in out)


def test_parabolic_flight_is_kept():
    ys, xs = _n()
    for i in range(0, 40):
        xs[i] = 100.0 + 14.0 * i
        ys[i] = 400.0 - 20.0 * i + 0.5 * i * i
    out = drop_non_flight(ys, xs)
    assert sum(v is not None for v in out) >= 35


def test_sparse_window_left_alone():
    ys, xs = _n()
    for i in (3, 20, 40):
        ys[i], xs[i] = 300.0, 500.0
    assert drop_non_flight(ys, xs) == ys
