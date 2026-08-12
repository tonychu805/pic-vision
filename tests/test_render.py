import os
import src.render as render
from src.render import clip_command, manifest_entry, concat_clips, cut_clips


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
        # capture filelist while it still exists (deleted after this call)
        filelist = next(a for a in cmd if "_filelist.txt" in a)
        called["filelist_content"] = open(filelist).read()

    monkeypatch.setattr(render.subprocess, "run", fake_run)
    manifest = [{"file": "rally_001.mp4"}, {"file": "rally_002.mp4"}]
    out = concat_clips(manifest, str(tmp_path))

    assert out == str(tmp_path / "highlight.mp4")
    assert "-f" in called["cmd"] and "concat" in called["cmd"]
    assert str(tmp_path / "highlight.mp4") in called["cmd"]
    # filelist entries must use just the filename so ffmpeg resolves them
    # relative to the filelist's directory (not cwd), avoiding doubled paths
    content = called["filelist_content"]
    assert "rally_001.mp4" in content
    assert str(tmp_path) not in content


def test_concat_clips_returns_none_for_empty(tmp_path):
    assert concat_clips([], str(tmp_path)) is None


def test_cut_clips_applies_padding(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, check):
        calls.append(cmd)

    monkeypatch.setattr(render.subprocess, "run", fake_run)
    segs = [{"start": 60.0, "end": 65.0, "crossings": 5, "score": 5}]
    cut_clips("game.mp4", segs, str(tmp_path), pad_sec=3.0)

    ffmpeg_call = calls[0]
    # -ss is the seek position, -t is the duration
    ss_idx = ffmpeg_call.index("-ss")
    t_idx = ffmpeg_call.index("-t")
    seek = float(ffmpeg_call[ss_idx + 1])
    dur  = float(ffmpeg_call[t_idx + 1])
    assert seek == 57.0          # start - 3s pad
    assert dur  == 11.0          # (65-60) + 6s pad total


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
