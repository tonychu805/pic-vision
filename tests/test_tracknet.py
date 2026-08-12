import csv
import os
import tempfile

from src.tracknet import load_predictions, rally_segments_from_predictions


def _write_csv(rows, path):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Frame", "Visibility", "X", "Y"])
        writer.writerows(rows)


def test_load_predictions_visible_frames():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        path = f.name
    try:
        _write_csv([[0, 1, 100, 150], [1, 0, -1, -1], [2, 1, 100, 50]], path)
        track = load_predictions(path, fps=30.0)
        assert len(track) == 3
        assert track[0] == (0.0, 150.0)
        assert track[1][1] is None      # invisible frame -> None
        assert track[2] == (2 / 30.0, 50.0)
    finally:
        os.unlink(path)


def test_load_predictions_timestamps_scale_with_fps():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        path = f.name
    try:
        _write_csv([[60, 1, 0, 200]], path)
        track = load_predictions(path, fps=60.0)
        assert abs(track[0][0] - 1.0) < 1e-9   # frame 60 @ 60fps = 1.0s
    finally:
        os.unlink(path)


def test_rally_segments_from_predictions_detects_crossing_burst():
    # ball alternates above/below net_y=100 -> crossings -> one rally
    rows = [
        [0, 1, 0, 150],   # near
        [1, 1, 0, 50],    # far  -> crossing
        [2, 1, 0, 150],   # near -> crossing
        [3, 1, 0, 50],    # far  -> crossing
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        path = f.name
    try:
        _write_csv(rows, path)
        segs = rally_segments_from_predictions(
            path, fps=1.0, net_y=100, gap_sec=2.0, min_crossings=2
        )
        assert len(segs) == 1
        assert segs[0]["crossings"] == 3
    finally:
        os.unlink(path)


def test_rally_segments_from_predictions_sparse_crossings_dropped():
    # only 1 crossing -> below min_crossings=2 -> no segment
    rows = [[0, 1, 0, 150], [1, 1, 0, 50]]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        path = f.name
    try:
        _write_csv(rows, path)
        segs = rally_segments_from_predictions(
            path, fps=1.0, net_y=100, gap_sec=2.0, min_crossings=2
        )
        assert segs == []
    finally:
        os.unlink(path)
