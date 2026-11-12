# The hit finder on the pod (src/hit_finder.py, staging 2026-11-12).
#
# The port itself was checked against the research code (scripts/hit_detector.py,
# feat/ball-recall-eval) on the nine PGC 720p parts: identical rally lists. What
# is pinned here: the frozen model, the chain rules, the far-court crop, and
# the pod's fallback to the crossing rallies. Each "it works" check sits beside
# its "it does not" pair.
import os

import pytest

os.environ.setdefault("JOB_ID", "test-job-id")
os.environ.setdefault("JOB_TOKEN", "test-token")
os.environ.setdefault("BUCKET", "test-bucket")
os.environ.setdefault("OUTPUT_BUCKET", "test-output-bucket")
os.environ.setdefault("BRAND_ID", "test-brand-id")

from src import hit_finder as HF  # noqa: E402
from src import pose  # noqa: E402


def test_frozen_model_reproduces_sklearns_probabilities():
    m = HF.Model()
    got = m.predict_proba(m.check["rows"])
    assert len(got) > 100
    assert max(abs(a - b) for a, b in zip(got, m.check["proba"])) < 1e-12
    assert (m.cut, m.gap) == (0.7, 3.0)


def test_a_model_for_other_features_is_refused(tmp_path):
    import json
    d = json.load(open(HF.MODEL_PATH))
    d["features"] = list(reversed(d["features"]))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(d))
    with pytest.raises(ValueError):
        HF.Model(str(bad))


def swing(t, side, from_net):
    return {"t": t, "side": side, "from_net": from_net}


def test_four_alternating_swings_with_a_deep_start_make_a_rally():
    C = [swing(10, "near", 20), swing(11, "far", 10), swing(12, "near", 5), swing(13, "far", 5)]
    assert HF.build(C, [0.9] * 4, 0.7, 3.0) == [{"start": 9.5, "end": 14.5}]


def test_three_turns_or_no_deep_start_or_low_scores_make_none():
    C = [swing(10, "near", 20), swing(11, "far", 10), swing(12, "near", 5), swing(13, "far", 5)]
    assert HF.build(C[:3], [0.9] * 3, 0.7, 3.0) == []                    # warm-up length
    assert HF.build([dict(c, from_net=5) for c in C], [0.9] * 4, 0.7, 3.0) == []   # dinking at the kitchen
    assert HF.build(C, [0.9, 0.9, 0.6, 0.9], 0.7, 3.0) == []             # a rejected swing breaks the turns


def two_points():
    return [swing(10, "near", 20), swing(11, "far", 10), swing(12, "near", 5), swing(13, "far", 5),
            swing(15, "near", 20), swing(16, "far", 10), swing(17, "near", 5), swing(18, "far", 5)]


def test_a_quiet_pause_before_a_deep_swing_starts_a_new_point():
    assert HF.build(two_points(), [0.9] * 8, 0.7, 3.0, crossings=[]) == \
        [{"start": 9.5, "end": 14.5}, {"start": 14.5, "end": 19.5}]


def test_the_same_pause_with_the_ball_crossing_the_net_stays_one_rally():
    assert HF.build(two_points(), [0.9] * 8, 0.7, 3.0, crossings=[14.5]) == [{"start": 9.5, "end": 19.5}]


class FakeModel:
    """Finds one person at the top-left of whatever it is given; has the prefetch split."""

    def prepare(self, frames):
        return [f.shape for f in frames]

    def infer(self, shapes):
        return [[([1, 2, 3, 4], [[5, 6, 0.9]] * 17)] for _ in shapes]

    def __call__(self, frames):
        return self.infer(self.prepare(frames))


def test_the_far_crop_returns_frame_pixels_through_either_path():
    import numpy as np
    frames = [np.zeros((720, 1280, 3), np.uint8)] * 2
    crop = pose.CropModel(FakeModel(), (100, 50, 900, 500))
    for out in (crop(frames), crop.infer(crop.prepare(frames))):
        assert len(out) == 2
        box, kps = out[0][0]
        assert box == [101, 52, 103, 54]
        assert kps[0] == [105, 56, 0.9]
    assert crop.prepare(frames) == [(450, 800, 3)] * 2       # the model saw the crop, not the frame


def test_a_plain_model_gives_a_crop_with_no_prefetch_split():
    import numpy as np
    crop = pose.CropModel(lambda frames: [[] for _ in frames], (0, 0, 10, 10))
    assert not hasattr(crop, "prepare")        # pose_video then runs it serially, as for any plain callable
    assert crop([np.zeros((20, 20, 3), np.uint8)]) == [[]]


@pytest.fixture
def pod(monkeypatch, tmp_path):
    from cloud_pipeline import pod_driver
    weights = tmp_path / "pose.torchscript"
    weights.write_bytes(b"x")
    monkeypatch.setattr(pod_driver, "POSE_LOCAL", str(weights))
    monkeypatch.setattr(pod_driver, "_check_cancel", lambda stage, message: None)
    monkeypatch.setattr(pose, "PoseModel", lambda path: "pose model")
    return pod_driver


CROSSING_RALLIES = [{"start": 1.0, "end": 9.0}]


def test_the_pod_uses_the_hit_finders_rallies(pod, monkeypatch):
    found = [{"start": 2.0, "end": 8.0}, {"start": 20.0, "end": 30.0}]
    monkeypatch.setattr(HF, "find_rallies", lambda *a, **k: (found, {"candidates": 40, "accepted": 12, "frames": 900}))
    segs, info = pod.hit_finder_segments(None, "v.mp4", "p.csv", {}, [3.0], CROSSING_RALLIES)
    assert segs == found
    assert info["used"] == "hit_finder" and info["rallies"] == 2 and info["crossing_rallies"] == 1


def test_the_pod_falls_back_to_the_crossing_rallies_on_an_error(pod, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("CUDA out of memory")
    monkeypatch.setattr(HF, "find_rallies", boom)
    segs, info = pod.hit_finder_segments(None, "v.mp4", "p.csv", {}, [3.0], CROSSING_RALLIES)
    assert segs == CROSSING_RALLIES
    assert info["used"] == "crossings" and "CUDA out of memory" in info["error"]


def test_the_pod_falls_back_when_the_hit_finder_finds_nothing(pod, monkeypatch):
    monkeypatch.setattr(HF, "find_rallies", lambda *a, **k: ([], {"candidates": 3, "accepted": 0, "frames": 900}))
    segs, info = pod.hit_finder_segments(None, "v.mp4", "p.csv", {}, [3.0], CROSSING_RALLIES)
    assert segs == CROSSING_RALLIES and info["used"] == "crossings" and "error" not in info


def test_a_cancel_during_the_hit_finder_still_stops_the_job(pod, monkeypatch):
    def cancelled(*a, **k):
        raise pod.Cancelled()
    monkeypatch.setattr(HF, "find_rallies", cancelled)
    with pytest.raises(pod.Cancelled):
        pod.hit_finder_segments(None, "v.mp4", "p.csv", {}, [3.0], CROSSING_RALLIES)


def test_clips_say_they_came_from_the_hit_finder_only_when_it_was_used(pod):
    assert pod.rally_finder({"used": "hit_finder", "rallies": 4}) == "hit_finder"
    assert pod.rally_finder({"used": "crossings", "error": "boom"}) == "crossings"   # fell back
    assert pod.rally_finder(None) == "crossings"                                       # HIT_FINDER off
