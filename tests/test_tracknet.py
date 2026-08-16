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


def test_court_wedge_follows_the_court_taper():
    """The wedge must reject a point that a flat x-interval would accept: one
    beside the *far* half of the court, where the court is narrow but the near
    baseline (which court_x_range is derived from) is wide."""
    import json, os
    from src.calib import court_wedge, court_x_range
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calib",
                        "IMG_7743_calib.json")
    if not os.path.exists(path):
        return                      # calibration not present in this checkout
    calib = json.load(open(path))
    inside = court_wedge(calib, margin_px=80.0, cap_court_heights=None, spread=0.0)
    xmin, xmax = court_x_range(calib, margin_px=80.0)

    # far end of the court sits around image-y 590 and spans x ~794..1132
    assert inside(960, 592)                 # centre of the far baseline: in
    assert not inside(300, 592)             # far left at that depth: adjacent court
    assert xmin <= 300 <= xmax              # ...which the flat x-gate would accept
    # near baseline is wide, so the same x is legitimate down there
    assert inside(300, 950)


def test_court_wedge_keeps_airspace_above_the_court():
    import json, os
    from src.calib import court_wedge
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calib",
                        "IMG_7743_calib.json")
    if not os.path.exists(path):
        return
    inside = court_wedge(json.load(open(path)), margin_px=80.0,
                         cap_court_heights=None, spread=0.0)
    assert inside(960, 200)                 # lob high over the court centre
    assert not inside(200, 200)             # same height, off to the side


def test_court_wedge_caps_the_ceiling_and_widens_below_it():
    """The default trapezoid rejects ceiling-height detections outright, and
    just under the cap it is wider than the far baseline (so a high ball hit
    from near the camera stays inside)."""
    import json, os
    from src.calib import court_wedge
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calib",
                        "IMG_7743_calib.json")
    if not os.path.exists(path):
        return
    inside = court_wedge(json.load(open(path)))       # tuned defaults
    assert not inside(960, 200)             # ceiling lights: above the cap
    assert inside(960, 500)                 # over the court, below the cap
    # the far baseline spans x~794..1132; just under the cap the band is wider
    assert inside(600, 400)
    assert not inside(150, 400)             # ...but not all the way to the wall
