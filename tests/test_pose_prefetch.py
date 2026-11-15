"""pose_video's background prefetch (2026-10-29): same output as the serial
path, errors from either thread surface, and the reader thread never hangs."""
import threading

import cv2
import numpy as np
import pytest

from src import pose


@pytest.fixture
def video(tmp_path):
    path = str(tmp_path / "v.avi")
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 30, (64, 36))
    for i in range(60):
        w.write(np.full((36, 64, 3), i * 4 % 255, np.uint8))
    w.release()
    return path


def _people(img_mean):
    box = np.array([1.0, 2.0, 10.0 + img_mean, 20.0])
    kps = np.full((17, 3), img_mean / 255.0)
    return [(box, kps)]


class Serial:
    """A model with only __call__: pose_video's serial path."""
    def __call__(self, frames):
        return [_people(float(f.mean())) for f in frames]


class Split(Serial):
    """The same model, split like PoseModel: prepare (CPU) + infer (GPU)."""
    def __init__(self, fail_in=None):
        self.fail_in = fail_in
        self.prepare_threads = set()

    def prepare(self, frames):
        self.prepare_threads.add(threading.current_thread().name)
        if self.fail_in == "prepare":
            raise RuntimeError("decode broke")
        return [float(f.mean()) for f in frames]

    def infer(self, prepared):
        if self.fail_in == "infer":
            raise RuntimeError("gpu broke")
        return [_people(m) for m in prepared]


H = np.eye(3)
FRAMES = list(range(3, 20)) + list(range(30, 58, 2))      # gaps, like rally windows


def test_prefetch_matches_the_serial_path_and_runs_off_the_main_thread(video):
    seen = []
    split = Split()
    a = pose.pose_video(video, FRAMES, Serial(), H, batch=4)
    b = pose.pose_video(video, FRAMES, split, H, batch=4, progress=lambda done, total: seen.append((done, total)))
    assert a == b
    assert sorted(map(int, b)) == FRAMES
    assert split.prepare_threads and all(n.startswith("pose-prepare") for n in split.prepare_threads)
    assert seen[-1] == (len(FRAMES), len(FRAMES))


class SlowEarlySplit(Split):
    """Earlier batches take longer to prepare, so parallel workers finish them out of order."""
    def prepare(self, frames):
        import time
        time.sleep(0.05 * max(0, 3 - len(self.prepare_threads)))
        return super().prepare(frames)


def test_parallel_prepare_gives_the_serial_output_in_frame_order(video, monkeypatch):
    monkeypatch.setenv("PIC_VISION_POSE_PREP_WORKERS", "3")
    split = SlowEarlySplit()
    a = pose.pose_video(video, FRAMES, Serial(), H, batch=2)
    b = pose.pose_video(video, FRAMES, split, H, batch=2)
    assert a == b and list(map(int, b)) == FRAMES
    assert len(split.prepare_threads) > 1
    passes = pose.pose_video_passes(video, FRAMES, {"one": Split(), "two": Split()}, H, batch=2)
    assert passes["one"] == passes["two"] == a


@pytest.mark.parametrize("where", ["prepare", "infer"])
def test_errors_surface_and_the_reader_thread_stops(video, where):
    before = {t.name for t in threading.enumerate()}
    with pytest.raises(RuntimeError):
        pose.pose_video(video, FRAMES, Split(fail_in=where), H, batch=2)
    lingering = [t for t in threading.enumerate() if t.name == "pose-prefetch" and t.is_alive()]
    assert not lingering, f"reader thread left running ({before})"


def test_no_frames_is_empty(video):
    assert pose.pose_video(video, [], Split(), H) == {}
