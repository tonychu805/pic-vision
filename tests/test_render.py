import os
import subprocess

import pytest

import src.render as render
from src.render import clip_command, manifest_entry, concat_clips, cut_clips


@pytest.fixture(autouse=True)
def _cpu_encoder(monkeypatch):
    """Unit tests never probe the real GPU: the encoder is fixed to the CPU."""
    monkeypatch.setattr(render, "_encoder", "cpu")


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

    class FakeResult:
        stdout = "11.0"

    def fake_run(cmd, **kwargs):
        if cmd[0] == "ffprobe":
            return FakeResult()
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

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


# Paired with the above: manifest.json's start/end must describe the file
# actually on disk (the padded cut), not the raw unpadded detection bounds
# -- otherwise a reader of manifest.json (now including pic-vision's
# pod_driver.py, persisted as a rally's part_start_sec/part_end_sec) thinks
# the clip is 2*pad_sec shorter than it really is.
def _fake_run_with_probed_duration(seconds):
    """clip_command's own subprocess.run call is a no-op (cmd[0] == 'ffmpeg');
    probe_duration's is answered with `seconds`, as real ffprobe output."""
    class FakeResult:
        stdout = str(seconds)

    def fake_run(cmd, **kwargs):
        return FakeResult() if cmd[0] == "ffprobe" else subprocess.CompletedProcess(cmd, 0, "", "")
    return fake_run


def test_cut_clips_manifest_reports_the_padded_range_not_the_raw_one(monkeypatch, tmp_path):
    monkeypatch.setattr(render.subprocess, "run", _fake_run_with_probed_duration(11.0))
    segs = [{"start": 60.0, "end": 65.0, "crossings": 5, "score": 5}]
    manifest = cut_clips("game.mp4", segs, str(tmp_path), pad_sec=3.0)
    assert manifest[0]["start"] == 57.0
    assert manifest[0]["end"] == 68.0
    assert manifest[0]["duration"] == 11.0


# The actual bug this closes: a rally ending within pad_sec of the source
# video's own end asks ffmpeg to cut past where the video stops, and ffmpeg
# just ends the file early there instead of failing. manifest.json must
# say what's REALLY in the file (9s here), not the inflated 11s that was
# asked for -- a desktop later trimming its own high-res recording to this
# value needs the truth, not the request.
def test_cut_clips_manifest_reports_the_real_shorter_duration_when_the_source_runs_out(monkeypatch, tmp_path):
    monkeypatch.setattr(render.subprocess, "run", _fake_run_with_probed_duration(9.0))
    segs = [{"start": 60.0, "end": 65.0, "crossings": 5, "score": 5}]
    manifest = cut_clips("game.mp4", segs, str(tmp_path), pad_sec=3.0)
    assert manifest[0]["start"] == 57.0
    assert manifest[0]["end"] == 66.0  # 57 + 9.0 real duration, not 68.0 requested
    assert manifest[0]["duration"] == 9.0


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


# --- clip encoder + parallel cutting (2026-10-27) ---------------------------

def test_clip_command_uses_the_requested_encoder():
    from src import render
    assert "libx264" in clip_command("s.mp4", 1.0, 2.0, "o.mp4")
    cmd = clip_command("s.mp4", 1.0, 2.0, "o.mp4", encoder="nvenc")
    assert "h264_nvenc" in cmd and "libx264" not in cmd and cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    assert set(render.ENCODERS) == {"nvenc", "cpu"}


def test_an_nvenc_failure_falls_back_to_the_cpu_for_good(monkeypatch):
    import subprocess as sp
    from src import render
    calls = []

    def fake_run(cmd, **kw):
        calls.append("h264_nvenc" if "h264_nvenc" in cmd else "libx264")
        if "h264_nvenc" in cmd:
            return sp.CompletedProcess(cmd, 1, "", "OpenEncodeSessionEx failed: unsupported device (nvenc)")
        return sp.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(render, "_encoder", "nvenc")
    monkeypatch.setattr(render.subprocess, "run", fake_run)
    render._encode_clip("s.mp4", 0, 1, "a.mp4", None, None)
    render._encode_clip("s.mp4", 1, 2, "b.mp4", None, None)
    assert calls == ["h264_nvenc", "libx264", "libx264"]
    assert render._encoder == "cpu"


def test_a_non_nvenc_failure_is_not_retried(monkeypatch):
    import subprocess as sp
    import pytest
    from src import render
    monkeypatch.setattr(render, "_encoder", "nvenc")
    monkeypatch.setattr(render.subprocess, "run", lambda cmd, **kw: sp.CompletedProcess(cmd, 1, "", "No such file"))
    with pytest.raises(sp.CalledProcessError):
        render._encode_clip("missing.mp4", 0, 1, "a.mp4", None, None)


def test_cut_clips_in_parallel_keeps_order_and_real_durations(tmp_path, monkeypatch):
    import json
    import subprocess as sp
    from src import render
    video = str(tmp_path / "v.mp4")
    sp.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=320x180:d=8:r=30", "-pix_fmt", "yuv420p", video], check=True)
    monkeypatch.setattr(render, "_encoder", "cpu")
    segs = [{"start": 5.0, "end": 6.0}, {"start": 1.0, "end": 2.0}, {"start": 3.0, "end": 4.0}]
    m = render.cut_clips(video, segs, str(tmp_path / "out"), pad_sec=0.5)
    assert [e["file"] for e in m] == ["rally_001.mp4", "rally_002.mp4", "rally_003.mp4"]
    assert [round(e["start"], 1) for e in m] == [0.5, 2.5, 4.5]
    assert all(abs((e["end"] - e["start"]) - 2.0) < 0.15 for e in m)
    assert json.load(open(tmp_path / "out" / "manifest.json"))["clips"] == m


def test_a_stretch_already_cut_is_reused_not_re_encoded(tmp_path, monkeypatch):
    """The full reel and the per-rally clips cut the same padded stretches."""
    encoded = []
    monkeypatch.setattr(render, "_cut_cache", {})
    monkeypatch.setattr(render, "_encode_clip", lambda video, s, e, out, *a: (encoded.append((s, e)), open(out, "w").write("x")))
    monkeypatch.setattr(render, "probe_duration", lambda p: 3.0)
    monkeypatch.setattr(render, "probe_width", lambda v: 1920)
    a = [{"start": 10.0, "end": 12.0}, {"start": 20.0, "end": 22.0}]
    render.cut_clips("v.mp4", a, str(tmp_path / "full"), pad_sec=0.5)
    render.cut_clips("v.mp4", a + [{"start": 30.0, "end": 32.0}], str(tmp_path / "top"), pad_sec=0.5)
    assert encoded == [(9.5, 12.5), (19.5, 22.5), (29.5, 32.5)]
    assert sorted(os.listdir(tmp_path / "top")) == ["manifest.json", "rally_001.mp4", "rally_002.mp4", "rally_003.mp4"]
    # Paired: a different logo or video is a different clip, never reused.
    render.cut_clips("other.mp4", a[:1], str(tmp_path / "o"), pad_sec=0.5)
    render.cut_clips("v.mp4", a[:1], str(tmp_path / "l"), pad_sec=0.5, logo_path="logo.png")
    assert encoded[3:] == [(9.5, 12.5), (9.5, 12.5)]
