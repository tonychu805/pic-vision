import csv

from src.ball_threshold import apply_adaptive_threshold

HEADER = ["Frame", "Visibility", "X", "Y", "W", "H", "Conf"]


def _write(path, confs):
    """One frame per entry: a confidence, or None for 'ball not seen'."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for i, c in enumerate(confs):
            w.writerow([i, 0, -1, -1, -1, -1, 0.0] if c is None else [i, 1, 100 + i, 200, 15, 15, c])


def _read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_a_venue_that_detects_well_is_cut_back_to_the_strict_value(tmp_path):
    src, dst = tmp_path / "in.csv", tmp_path / "out.csv"
    _write(src, [0.9] * 30 + [0.4] * 20 + [None] * 50)     # 30% strong, 50% any
    r = apply_adaptive_threshold(src, dst)
    out = _read(dst)
    assert r["cut"] == 0.5 and round(r["rate_at_high"], 2) == 0.30 and round(r["rate_at_low"], 2) == 0.50
    assert sum(1 for x in out if x["Visibility"] == "1") == 30
    assert all(float(x["Conf"]) >= 0.5 for x in out if x["Visibility"] == "1")
    weak = out[30]                                         # a dropped 0.4 detection becomes a plain 'not seen' row
    assert (weak["Visibility"], weak["X"], weak["Conf"]) == ("0", "-1", "0.0")


def test_a_venue_that_detects_poorly_keeps_the_low_threshold_detections(tmp_path):
    src, dst = tmp_path / "in.csv", tmp_path / "out.csv"
    _write(src, [0.9] * 10 + [0.4] * 30 + [None] * 60)     # 10% strong
    r = apply_adaptive_threshold(src, dst)
    assert r["cut"] is None and round(r["rate_at_low"], 2) == 0.40
    assert dst.read_text() == src.read_text()


def test_a_detection_exactly_at_the_strict_value_is_kept(tmp_path):
    src, dst = tmp_path / "in.csv", tmp_path / "out.csv"
    _write(src, [0.5] * 30 + [None] * 70)
    assert apply_adaptive_threshold(src, dst)["cut"] == 0.5
    assert sum(1 for x in _read(dst) if x["Visibility"] == "1") == 30


def test_a_file_without_a_confidence_column_is_left_alone(tmp_path):
    src, dst = tmp_path / "in.csv", tmp_path / "out.csv"
    src.write_text("Frame,Visibility,X,Y\n0,1,10,20\n1,0,-1,-1\n")
    assert apply_adaptive_threshold(src, dst)["cut"] is None
    assert dst.read_text() == src.read_text()


def test_a_file_with_no_frames_does_not_crash(tmp_path):
    src, dst = tmp_path / "in.csv", tmp_path / "out.csv"
    src.write_text(",".join(HEADER) + "\n")
    assert apply_adaptive_threshold(src, dst)["cut"] is None
    assert dst.read_text() == src.read_text()


def test_the_output_can_overwrite_the_input(tmp_path):
    p = tmp_path / "pred.csv"
    _write(p, [0.9] * 30 + [0.4] * 20 + [None] * 50)
    apply_adaptive_threshold(p, p)
    assert sum(1 for x in _read(p) if x["Visibility"] == "1") == 30
