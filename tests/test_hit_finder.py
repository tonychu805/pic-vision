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
    monkeypatch.setattr(HF, "find_rallies", lambda *a, **k: (found, {"candidates": 40, "accepted": 12, "frames": 900, "posed": 450}))
    segs, info, _ = pod.hit_finder_segments(None, "v.mp4", "p.csv", {}, [3.0], CROSSING_RALLIES)
    assert segs == found
    assert info["used"] == "hit_finder" and info["rallies"] == 2 and info["crossing_rallies"] == 1


def test_the_pod_falls_back_to_the_crossing_rallies_on_an_error(pod, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("CUDA out of memory")
    monkeypatch.setattr(HF, "find_rallies", boom)
    segs, info, _ = pod.hit_finder_segments(None, "v.mp4", "p.csv", {}, [3.0], CROSSING_RALLIES)
    assert segs == CROSSING_RALLIES
    assert info["used"] == "crossings" and "CUDA out of memory" in info["error"]


def test_the_pod_falls_back_when_the_hit_finder_finds_nothing(pod, monkeypatch):
    monkeypatch.setattr(HF, "find_rallies", lambda *a, **k: ([], {"candidates": 3, "accepted": 0, "frames": 900, "posed": 450}))
    segs, info, _ = pod.hit_finder_segments(None, "v.mp4", "p.csv", {}, [3.0], CROSSING_RALLIES)
    assert segs == CROSSING_RALLIES and info["used"] == "crossings" and "error" not in info


def test_the_hit_finders_whole_frame_poses_come_back_for_badges(pod, monkeypatch):
    def find(*a, keep_full=None, **k):
        keep_full.update({"0": ["p"], "2": ["q"]})
        return [{"start": 2.0, "end": 8.0}], {"candidates": 4, "accepted": 4, "frames": 900, "posed": 450}
    monkeypatch.setattr(HF, "find_rallies", find)
    assert pod.hit_finder_segments(None, "v.mp4", "p.csv", {}, [3.0], CROSSING_RALLIES)[2] == {"0": ["p"], "2": ["q"]}
    monkeypatch.setattr(HF, "find_rallies", lambda *a, **k: ([], {"candidates": 0, "accepted": 0, "frames": 900, "posed": 450}))
    assert pod.hit_finder_segments(None, "v.mp4", "p.csv", {}, [3.0], CROSSING_RALLIES)[2] == {}   # fell back


def test_badges_pose_only_the_rally_frames_the_hit_finder_did_not(pod, monkeypatch, tmp_path):
    import cv2
    import numpy as np
    from src import badges
    video = str(tmp_path / "v.mp4")
    w = cv2.VideoWriter(video, cv2.VideoWriter_fourcc(*"mp4v"), 30, (96, 54))
    for _ in range(120):
        w.write(np.zeros((54, 96, 3), np.uint8))
    w.release()
    segments = [{"start": 1.0, "end": 2.0}]
    frames = pose.pose_frames(segments, 120)
    known = {str(f): ["from the hit finder"] for f in frames if f % 2 == 0}
    posed, measured = [], {}

    def pose_video(video, fs, model, H, progress=None):
        posed.extend(fs)
        return {str(f): ["posed for badges"] for f in fs}
    monkeypatch.setattr(pose, "pose_video", pose_video)
    monkeypatch.setattr(badges, "measure", lambda P, *a: measured.update(P) or {"rallies": [], "swings": []})
    result, poses = pod.measure_badges(None, video, segments, [], {"homography": np.eye(3).tolist()}, known=known)
    assert posed == [f for f in frames if f % 2 == 1]
    assert measured == poses and sorted(map(int, poses)) == frames
    assert all(poses[str(f)] == ["from the hit finder"] for f in frames if f % 2 == 0)
    assert result["pose_frames"] == len(frames) and result["pose_reused"] == len(known)


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


def _video(path, n=12, size=(64, 48)):
    import cv2
    import numpy as np
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, size)
    for i in range(n):
        out.write(np.full((size[1], size[0], 3), i * 10, np.uint8))
    out.release()
    return str(path)


class Brightness:
    """A 'pose model' whose one person sits at the frame's mean brightness: frames are told apart."""

    def prepare(self, frames):
        return [float(f.mean()) for f in frames]

    def infer(self, means):
        return [[([m, m, m + 1, m + 1], [[m, m, 1.0]] * 17)] for m in means]

    def __call__(self, frames):
        return self.infer(self.prepare(frames))


def test_one_decode_gives_each_pass_what_it_would_get_alone(tmp_path):
    import numpy as np
    video, H = _video(tmp_path / "v.mp4"), np.eye(3)
    frames = [0, 2, 4, 6, 8, 10]
    models = {"full": Brightness(), "far": pose.CropModel(Brightness(), (0, 0, 32, 24))}
    together = pose.pose_video_passes(video, frames, models, H, batch=4)
    for name, m in models.items():
        assert together[name] == pose.pose_video(video, frames, m, H, batch=4)
    assert sorted(together["full"], key=int) == [str(f) for f in frames]


def test_one_decode_also_works_for_plain_models(tmp_path):
    import numpy as np
    video = _video(tmp_path / "v.mp4")
    plain = {"a": lambda imgs: [[] for _ in imgs], "b": lambda imgs: [[([0, 0, 1, 1], [[0, 0, 1.0]] * 17)] for _ in imgs]}
    out = pose.pose_video_passes(video, [1, 3], plain, np.eye(3))
    assert out["a"] == {"1": [], "3": []} and len(out["b"]["1"]) == 1


def _baselines(seconds, step):
    """Someone at each baseline for `seconds`, posed every `step` frames."""
    near = {"court": [10.0, 0.0]}
    far = {"court": [10.0, 44.0]}
    n = int(seconds * HF.FPS)
    return ({str(f): [near] for f in range(0, n + 60, step)},
            {str(f): [far] if f < n else [] for f in range(0, n + 60, step)})


def test_a_held_set_up_is_found_at_either_sampling_step():
    for step in (3, 6):
        full, far = _baselines(3.0, step)
        assert HF.serve_setups(full, far, [], step) == [0.0]


def test_a_set_up_shorter_than_the_hold_is_not_found_at_either_step():
    for step in (3, 6):
        full, far = _baselines(1.5, step)
        assert HF.serve_setups(full, far, [], step) == []


def test_the_pod_sizes_thread_pools_before_the_hit_finder(pod, monkeypatch):
    # Same cause as inference (src/cpus.py): host-sized pools thrash on a 5-7 CPU pod.
    from src import cpus
    seen = []
    monkeypatch.setattr(cpus, "limit_threads", lambda: seen.append(1) or {"usable_cpus": 7, "cv2_threads": 7})
    monkeypatch.setattr(HF, "find_rallies", lambda *a, **k: ([{"start": 1.0, "end": 9.0}], {"candidates": 4, "accepted": 4, "frames": 900, "posed": 450}))
    segs, info, _ = pod.hit_finder_segments(None, "v.mp4", "p.csv", {}, [3.0], CROSSING_RALLIES)
    assert seen == [1] and info["threads"]["cv2_threads"] == 7 and info["used"] == "hit_finder"


def test_usable_cpus_never_exceeds_what_the_process_may_run_on():
    import os
    from src import cpus
    n = cpus.usable_cpus()
    assert 1 <= n <= len(os.sched_getaffinity(0)) <= (os.cpu_count() or n)
