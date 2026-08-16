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
        assert track[0] == (0.0, 100.0, 150.0)
        assert track[1][1] is None and track[1][2] is None   # invisible frame -> None
        assert track[2] == (2 / 30.0, 100.0, 50.0)
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


def test_rally_segments_rejects_adjacent_court_teleport():
    # Confirmed 2026-08-16 on IMG_7744: an empty tracked court still produced
    # a "rally" because TrackNet's best-guess ball jumped onto a real ball on
    # the adjacent court (X~1400-1900) whose natural up/down motion crossed
    # net_y. track_ball's teleport-rejection (max_jump) must catch this.
    rows = [
        [0, 1, 100, 150],   # near court, below net
        [1, 1, 100, 50],    # near court, above net -> crossing (still tracked)
        [2, 1, 1500, 150],  # teleport to adjacent court -> rejected, not a crossing
        [3, 1, 1500, 50],   # adjacent court -> also rejected (no track to jump from)
        [4, 1, 1500, 150],  # adjacent court -> also rejected
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        path = f.name
    try:
        _write_csv(rows, path)
        segs = rally_segments_from_predictions(
            path, fps=1.0, net_y=100, gap_sec=2.0, min_crossings=2, max_jump=150,
        )
        # only 1 real crossing survives (frame 0->1) -> below min_crossings=2 -> no segment
        assert segs == []
    finally:
        os.unlink(path)


def test_rally_segments_court_gate_survives_reset_after_gap():
    # Confirmed 2026-08-16 on IMG_7744, then re-verified against real
    # regenerated predictions: track_ball's teleport-rejection alone does NOT
    # catch an adjacent-court ball reappearing after real dead time, because
    # dead time (here 20 frames) exceeds reset_after (15) and releases the
    # lock -- track_ball just re-acquires on the adjacent ball as if it were
    # a fresh legitimate track. The synthetic same-frame-teleport test above
    # (test_rally_segments_rejects_adjacent_court_teleport) doesn't exercise
    # this because it has no gap. The court X-gate must reject the adjacent
    # court regardless of gap length.
    rows = [[0, 1, 100, 150], [1, 1, 100, 50]]       # near court: 1 real crossing
    rows += [[f, 0, -1, -1] for f in range(2, 22)]   # 20-frame dead time > reset_after=15
    rows += [                                         # adjacent court reappears
        [22, 1, 1500, 150],
        [23, 1, 1500, 50],
        [24, 1, 1500, 150],
        [25, 1, 1500, 50],
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        path = f.name
    try:
        _write_csv(rows, path)

        # Without the gate: reproduces the confirmed bug -- track_ball resets
        # during the gap and re-acquires on the adjacent court -> phantom rally.
        phantom = rally_segments_from_predictions(
            path, fps=1.0, net_y=100, gap_sec=2.0, min_crossings=2, max_jump=150,
        )
        assert phantom != []
        assert phantom[0]["crossings"] >= 2

        # With the gate: adjacent-court detections (x=1500) never reach
        # track_ball, so the reset can't be exploited -> no phantom rally.
        gated = rally_segments_from_predictions(
            path, fps=1.0, net_y=100, gap_sec=2.0, min_crossings=2, max_jump=150,
            court_x_min=0, court_x_max=800,
        )
        assert gated == []
    finally:
        os.unlink(path)
