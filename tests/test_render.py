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


def test_clip_command_without_a_logo_is_unchanged():
    cmd = clip_command("session.mp4", 10.0, 15.5, "out/rally_001.mp4")
    assert "-filter_complex" not in cmd
    assert cmd.count("-i") == 1


def test_clip_command_with_a_logo_keeps_duration_on_the_output():
    # -t after the logo's -i: placed before it, ffmpeg would read -t as an
    # input option on the LOGO and the clip would run to end of source.
    cmd = clip_command("session.mp4", 10.0, 15.5, "out.mp4", logo_path="logo.png", video_width=1920)
    assert cmd.index("logo.png") < cmd.index("-t")
    assert "overlay=W-w-32:H-h-32" in cmd[cmd.index("-filter_complex") + 1]
    assert "scale=154:" in cmd[cmd.index("-filter_complex") + 1]  # 8% of 1920, even


def test_logo_scales_with_the_video_not_a_fixed_pixel_size():
    f = render.logo_filter(1280)
    assert "scale=102:" in f and "overlay=W-w-21:H-h-21" in f


def _ffmpeg_available():
    import shutil
    return shutil.which("ffmpeg") and shutil.which("ffprobe")


def test_cut_clips_really_burns_the_logo_into_the_lower_right_corner(tmp_path):
    """Real ffmpeg, not a mocked command: the filter string is only proven
    by ffmpeg accepting it and the pixels coming out where they should."""
    import subprocess
    import pytest
    if not _ffmpeg_available():
        pytest.skip("ffmpeg not installed")
    video = str(tmp_path / "src.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=30:d=4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", video], check=True)
    logo = str(tmp_path / "logo.png")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=white:s=100x100",
                    "-frames:v", "1", logo], check=True)

    cut_clips(video, [{"start": 1.0, "end": 2.0}], str(tmp_path / "out"), pad_sec=0.5, logo_path=logo)

    clip = str(tmp_path / "out" / "rally_001.mp4")
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", clip], capture_output=True, text=True, check=True).stdout)
    assert 1.8 < dur < 2.3  # still the padded segment, not the rest of the source

    def luma(x, y):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", clip, "-frames:v", "1",
                              "-vf", f"crop=1:1:{x}:{y},format=gray", "-f", "rawvideo", "-"],
                             capture_output=True, check=True).stdout
        return raw[0]

    # logo is 52px wide (8% of 640), inset 11px: its centre is white...
    assert luma(640 - 11 - 26, 360 - 11 - 26) > 200
    # ...the opposite corner of the frame is untouched black...
    assert luma(20, 20) < 30
    # ...and the logo's own outermost corner pixel has been rounded away.
    assert luma(640 - 12, 360 - 12) < 60
