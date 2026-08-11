import os
import src.render as render
from src.render import clip_command, manifest_entry, concat_clips


def test_clip_command_builds_h264_ffmpeg_args():
    cmd = clip_command("session.mp4", 10.0, 15.5, "out/rally_001.mp4")
    assert cmd[0] == "ffmpeg"
    assert "session.mp4" in cmd
    assert "out/rally_001.mp4" in cmd
    assert "10.0" in cmd            # seek to start
    assert "5.5" in cmd             # duration = end - start
    assert "libx264" in cmd         # H.264 so clips play inline (mp4v doesn't)


def test_concat_clips_builds_ffmpeg_concat_command(monkeypatch, tmp_path):
    called = {}

    def fake_run(cmd, check):
        called["cmd"] = cmd

    monkeypatch.setattr(render.subprocess, "run", fake_run)
    manifest = [{"file": "rally_001.mp4"}, {"file": "rally_002.mp4"}]
    out = concat_clips(manifest, str(tmp_path))

    assert out == str(tmp_path / "highlight.mp4")
    assert "-f" in called["cmd"] and "concat" in called["cmd"]
    assert str(tmp_path / "highlight.mp4") in called["cmd"]


def test_concat_clips_returns_none_for_empty(tmp_path):
    assert concat_clips([], str(tmp_path)) is None


def test_manifest_entry_carries_court_time_score():
    seg = {"start": 58.0, "end": 77.5, "score": 33}
    e = manifest_entry(seg, rally_id=3, file="rally_003.mp4",
                       court_id="court-1", session_id="2026-08-10T18:00")
    assert e["rally_id"] == 3
    assert e["court_id"] == "court-1"
    assert e["session_id"] == "2026-08-10T18:00"
    assert e["start"] == 58.0 and e["end"] == 77.5
    assert e["duration"] == 19.5
    assert e["score"] == 33
    assert e["file"] == "rally_003.mp4"
