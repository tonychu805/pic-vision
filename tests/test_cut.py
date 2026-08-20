import json

import src.cut as cut


def test_cut_rallies_from_predictions_forwards_scored_segments(monkeypatch):
    # fake TrackNet predictions -> segments, and ffmpeg cut; assert the glue
    monkeypatch.setattr(cut, "rally_segments_from_predictions",
                        lambda csv_path, fps, net_y, **kw: [
                            {"start": 58.0, "end": 77.5, "crossings": 16}])
    captured = {}

    def fake_cut_clips(video, segments, out_dir, court_id=None, session_id=None,
                       pad_sec=3.0):
        captured.update(video=video, segments=segments, out_dir=out_dir,
                        court_id=court_id, session_id=session_id)
        return ["manifest"]

    monkeypatch.setattr(cut, "cut_clips", fake_cut_clips)
    monkeypatch.setattr(cut, "concat_clips", lambda manifest, out_dir: None)

    result = cut.cut_rallies_from_predictions(
        "s.mp4", "preds.csv", fps=30.0, net_y=260, out_dir="/tmp/x",
        gap_sec=3.0, min_crossings=3,
        court_id="court-1", session_id="sess-1",
    )

    seg = captured["segments"][0]
    assert seg["score"] == 16                       # crossings surfaced as score
    assert seg["start"] == 58.0 and seg["end"] == 77.5 and seg["crossings"] == 16
    assert captured["video"] == "s.mp4" and captured["out_dir"] == "/tmp/x"
    assert captured["court_id"] == "court-1" and captured["session_id"] == "sess-1"
    assert result == ["manifest"]


def test_cut_rallies_from_predictions_handles_no_rallies(monkeypatch):
    monkeypatch.setattr(cut, "rally_segments_from_predictions",
                        lambda csv_path, fps, net_y, **kw: [])
    captured = {}
    monkeypatch.setattr(cut, "cut_clips",
                        lambda video, segments, out_dir, **kw:
                        captured.update(segments=segments) or [])
    monkeypatch.setattr(cut, "concat_clips", lambda manifest, out_dir: None)

    result = cut.cut_rallies_from_predictions(
        "s.mp4", "preds.csv", fps=30.0, net_y=260, out_dir="/tmp/x",
        gap_sec=3.0, min_crossings=3,
    )
    assert captured["segments"] == []               # empty -> empty manifest
    assert result == []


def _capture_gate_kwargs(monkeypatch, argv):
    captured = {}
    monkeypatch.setattr(cut, "cut_rallies_from_predictions",
                        lambda *a, **kw: captured.update(kw) or [])
    cut.main(argv)
    return captured


def test_main_defaults_to_court_wedge_when_calib_given(monkeypatch, tmp_path):
    # CLAUDE.md: court_wedge is the preferred gate; a plain --calib run with
    # no explicit override must use it, not the older flat court_x_range.
    calib_path = tmp_path / "calib.json"
    calib_path.write_text(json.dumps({"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}))
    sentinel = object()
    monkeypatch.setattr(cut, "court_wedge", lambda calib, **kw: sentinel)

    captured = _capture_gate_kwargs(monkeypatch, [
        "--video", "s.mp4", "--predictions", "preds.csv",
        "--calib", str(calib_path), "--net-y", "260",
        "--fps", "30", "--out", str(tmp_path / "out"),
    ])

    assert captured["in_court"] is sentinel
    assert captured["court_x_min"] is None and captured["court_x_max"] is None


def test_main_flat_court_gate_opts_out_of_wedge(monkeypatch, tmp_path):
    calib_path = tmp_path / "calib.json"
    calib_path.write_text(json.dumps({"image_points": [
        [280, 690], [1010, 660], [470, 185], [805, 165],
        [340, 610], [950, 590], [500, 260], [770, 245],
        [645, 675], [635, 175], [620, 435], [630, 420],
    ]}))

    captured = _capture_gate_kwargs(monkeypatch, [
        "--video", "s.mp4", "--predictions", "preds.csv",
        "--calib", str(calib_path), "--net-y", "260", "--flat-court-gate",
        "--fps", "30", "--out", str(tmp_path / "out"),
    ])

    assert captured["in_court"] is None
    assert captured["court_x_min"] == 280 - 50.0
    assert captured["court_x_max"] == 1010 + 50.0


def test_main_explicit_court_x_range_overrides_wedge(monkeypatch, tmp_path):
    calib_path = tmp_path / "calib.json"
    calib_path.write_text(json.dumps({"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}))
    calls = []
    monkeypatch.setattr(cut, "court_wedge", lambda calib, **kw: calls.append(1))

    captured = _capture_gate_kwargs(monkeypatch, [
        "--video", "s.mp4", "--predictions", "preds.csv",
        "--calib", str(calib_path), "--net-y", "260",
        "--court-x-min", "100", "--court-x-max", "900",
        "--fps", "30", "--out", str(tmp_path / "out"),
    ])

    assert calls == []                               # wedge never even built
    assert captured["in_court"] is None
    assert captured["court_x_min"] == 100.0 and captured["court_x_max"] == 900.0
