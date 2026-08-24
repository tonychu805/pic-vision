import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import rank_and_reel  # noqa: E402


def _fake_track():
    """14 frames, 0.5s apart, constant x=100 (well inside max_jump=150 so
    track_ball keeps the whole run), y alternating 40/60 across net_y=50 --
    a crossing every step, all within GAP_SEC=3.0 of each other, so this is
    exactly one candidate segment with well over MIN_CROSSINGS=6."""
    ys = [40.0, 60.0] * 7
    return [(i * 0.5, 100.0, y, 5.0, 5.0, 0.9) for i, y in enumerate(ys)]


def test_build_reel_reports_go_to_the_original_stdout_stderr_split(
        monkeypatch, tmp_path, capsys):
    # This is the exact split the original (pre-extraction) script had: the
    # ranked table on stdout, everything else on stderr. The extraction into
    # build_reel() must preserve it byte-for-byte -- verified once already by
    # hand (diffing the CLI's output before/after the refactor); this test
    # locks that in against a future regression.
    monkeypatch.setattr(rank_and_reel, "load_predictions", lambda csv, fps: _fake_track())
    monkeypatch.setattr(rank_and_reel, "court_wedge", lambda calib: (lambda x, y: True))
    monkeypatch.setattr(rank_and_reel, "net_line_y", lambda calib: 50.0)

    manifest = [{"file": "rally_001.mp4", "score": 0.5, "start": 0.0, "end": 6.5}]
    monkeypatch.setattr(rank_and_reel, "cut_clips",
                        lambda *a, **k: manifest)
    monkeypatch.setattr(rank_and_reel, "concat_clips",
                        lambda m, out_dir: str(Path(out_dir) / "highlight.mp4"))
    monkeypatch.setattr(rank_and_reel.subprocess, "run", lambda *a, **k: None)

    calib_path = tmp_path / "calib.json"
    calib_path.write_text(json.dumps({}))
    log_path = tmp_path / "log.txt"

    result = rank_and_reel.build_reel(
        "video.mp4", "predictions.csv", str(calib_path), str(tmp_path),
        target_sec=60.0, session_id="test", log_path=str(log_path))

    out, err = capsys.readouterr()
    table_header = "rank   start"
    assert table_header in out and "score" in out     # the ranked table
    assert "candidate rally segments" not in out
    assert "candidate rally segments" in err          # progress messages
    assert "chose 1/1 candidates" in err
    assert table_header not in err

    log_text = log_path.read_text()
    assert "candidate rally segments" in log_text     # both streams land in the log
    assert "score" in log_text

    assert result["manifest"] == manifest
    assert result["chronological"] == str(tmp_path / "highlight.mp4")
    assert result["stats"]["n_candidates"] == 1
    assert result["stats"]["n_chosen"] == 1
    assert result["stats"]["total_duration_sec"] > 0


def test_build_reel_stops_choosing_once_target_sec_is_met(monkeypatch, tmp_path):
    # Two well-separated segments so cluster_crossings keeps them distinct;
    # a tiny target_sec should only afford the first (best-scored) one.
    frames = []
    for base in (0.0, 20.0):
        ys = [40.0, 60.0] * 7
        frames += [(base + i * 0.5, 100.0, y, 5.0, 5.0, 0.9) for i, y in enumerate(ys)]
    monkeypatch.setattr(rank_and_reel, "load_predictions", lambda csv, fps: frames)
    monkeypatch.setattr(rank_and_reel, "court_wedge", lambda calib: (lambda x, y: True))
    monkeypatch.setattr(rank_and_reel, "net_line_y", lambda calib: 50.0)

    seen_scored = {}

    def fake_cut_clips(video, scored, out_dir, **kwargs):
        seen_scored["scored"] = scored
        return [{"file": f"rally_{i:03d}.mp4", "score": s["score"],
                 "start": s["start"], "end": s["end"]}
                for i, s in enumerate(scored, 1)]

    monkeypatch.setattr(rank_and_reel, "cut_clips", fake_cut_clips)
    monkeypatch.setattr(rank_and_reel, "concat_clips",
                        lambda m, out_dir: str(Path(out_dir) / "highlight.mp4"))
    monkeypatch.setattr(rank_and_reel.subprocess, "run", lambda *a, **k: None)

    calib_path = tmp_path / "calib.json"
    calib_path.write_text(json.dumps({}))

    result = rank_and_reel.build_reel(
        "video.mp4", "predictions.csv", str(calib_path), str(tmp_path),
        target_sec=10.0, session_id="test")

    assert len(seen_scored["scored"]) == 1
    assert result["stats"]["n_candidates"] == 2
    assert result["stats"]["n_chosen"] == 1
