import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import top_rallies_reel  # noqa: E402


def _segment_frames(base, score_bias):
    """A crossing-rich run of frames starting at `base` seconds -- score_bias
    is folded into y's swing amplitude so higher-scored segments have more
    net crossings (peak_crossing_rate) than lower ones, without touching
    duration (kept identical across segments so rank ordering isn't a
    duration artifact)."""
    ys = [40.0, 60.0] * (7 + score_bias)
    return [(base + i * 0.25, 100.0, y, 5.0, 5.0, 0.9) for i, y in enumerate(ys)]


def _fake_track(n_segments):
    frames = []
    for i in range(n_segments):
        frames += _segment_frames(base=i * 20.0, score_bias=i)
    return frames


def test_build_top_rallies_returns_rank_order_not_chronological(monkeypatch, tmp_path):
    # Segment 0 is first chronologically but has the fewest crossings (lowest
    # score); later segments score higher. The manifest cut_clips() would
    # hand back is chronological (rally 1, 2, 3...) -- build_top_rallies must
    # re-sort it into score order before returning.
    monkeypatch.setattr(top_rallies_reel, "load_predictions",
                        lambda csv, fps: _fake_track(3))
    monkeypatch.setattr(top_rallies_reel, "court_wedge", lambda calib: (lambda x, y: True))
    monkeypatch.setattr(top_rallies_reel, "net_line_y", lambda calib: 50.0)

    def fake_cut_clips(video, scored, out_dir, **kwargs):
        # Mirrors cut_clips' real contract: sorted by start time, i.e.
        # chronological, regardless of the caller's own list order.
        by_start = sorted(scored, key=lambda s: s["start"])
        return [{"file": f"rally_{i:03d}.mp4", "score": s["score"],
                 "start": s["start"], "end": s["end"]}
                for i, s in enumerate(by_start, 1)]

    monkeypatch.setattr(top_rallies_reel, "cut_clips", fake_cut_clips)

    calib_path = tmp_path / "calib.json"
    calib_path.write_text(json.dumps({}))

    result = top_rallies_reel.build_top_rallies(
        "video.mp4", "predictions.csv", str(calib_path), str(tmp_path),
        session_id="test", n=10)

    manifest = result["manifest"]
    assert len(manifest) == 3
    # Best-scored (segment index 2, most crossings) must be rank 1, not the
    # chronologically-first clip.
    assert [c["rank"] for c in manifest] == [1, 2, 3]
    scores = [c["score"] for c in manifest]
    assert scores == sorted(scores, reverse=True)
    assert result["stats"]["n_candidates"] == 3
    assert result["stats"]["n_chosen"] == 3


def test_build_top_rallies_caps_at_n_even_with_more_candidates(monkeypatch, tmp_path):
    monkeypatch.setattr(top_rallies_reel, "load_predictions",
                        lambda csv, fps: _fake_track(4))
    monkeypatch.setattr(top_rallies_reel, "court_wedge", lambda calib: (lambda x, y: True))
    monkeypatch.setattr(top_rallies_reel, "net_line_y", lambda calib: 50.0)

    def fake_cut_clips(video, scored, out_dir, **kwargs):
        return [{"file": f"rally_{i:03d}.mp4", "score": s["score"],
                 "start": s["start"], "end": s["end"]}
                for i, s in enumerate(sorted(scored, key=lambda s: s["start"]), 1)]

    monkeypatch.setattr(top_rallies_reel, "cut_clips", fake_cut_clips)

    calib_path = tmp_path / "calib.json"
    calib_path.write_text(json.dumps({}))

    result = top_rallies_reel.build_top_rallies(
        "video.mp4", "predictions.csv", str(calib_path), str(tmp_path),
        session_id="test", n=2)

    assert len(result["manifest"]) == 2
    assert result["stats"]["n_candidates"] == 4
    assert result["stats"]["n_chosen"] == 2


def test_build_top_rallies_returns_all_when_fewer_than_n_qualify(monkeypatch, tmp_path):
    monkeypatch.setattr(top_rallies_reel, "load_predictions",
                        lambda csv, fps: _fake_track(3))
    monkeypatch.setattr(top_rallies_reel, "court_wedge", lambda calib: (lambda x, y: True))
    monkeypatch.setattr(top_rallies_reel, "net_line_y", lambda calib: 50.0)

    def fake_cut_clips(video, scored, out_dir, **kwargs):
        return [{"file": f"rally_{i:03d}.mp4", "score": s["score"],
                 "start": s["start"], "end": s["end"]}
                for i, s in enumerate(sorted(scored, key=lambda s: s["start"]), 1)]

    monkeypatch.setattr(top_rallies_reel, "cut_clips", fake_cut_clips)

    calib_path = tmp_path / "calib.json"
    calib_path.write_text(json.dumps({}))

    result = top_rallies_reel.build_top_rallies(
        "video.mp4", "predictions.csv", str(calib_path), str(tmp_path),
        session_id="test", n=10)

    assert len(result["manifest"]) == 3  # no padding to 10
