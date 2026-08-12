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
