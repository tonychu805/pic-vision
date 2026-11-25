"""pod_driver.stash_for_archive: a finished part leaves its silent proxy, poses and calibration for tonight's copy."""
import gzip
import io
import json
import os
import subprocess

import pytest

os.environ.setdefault("JOB_ID", "test-job-id")
os.environ.setdefault("JOB_TOKEN", "test-token")
os.environ.setdefault("BUCKET", "test-bucket")
os.environ.setdefault("OUTPUT_BUCKET", "test-output-bucket")
os.environ.setdefault("BRAND_ID", "test-brand-id")

from cloud_pipeline import pod_driver  # noqa: E402

LINKS = {"proxy": "https://r2/proxy?sig", "poses": "https://r2/poses?sig", "calib": "https://r2/calib?sig"}
POSES = {"0": [{"box": [1, 2, 3, 4], "kp": [[1, 2, 0.9]] * 17}], "2": []}
CALIB = {"calibration_resolution": [320, 240]}


class Reply:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def video(tmp_path):
    path = str(tmp_path / "proxy.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=1:s=320x240:r=30",
                    "-f", "lavfi", "-i", "sine=d=1", "-c:v", "libx264", "-c:a", "aac", "-shortest", path], check=True)
    return path


def setup(monkeypatch, tmp_path, get_status, put_status=200):
    calls = {"get": 0, "put": {}, "post": []}
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(pod_driver, "WORKDIR", str(work))

    def get(*a, **k):
        calls["get"] += 1
        return Reply(get_status, {"urls": LINKS})

    def put(url, data=None, headers=None, **k):
        calls["put"][url] = data.read() if hasattr(data, "read") else data
        return Reply(put_status)
    monkeypatch.setattr(pod_driver.requests, "get", get)
    monkeypatch.setattr(pod_driver.requests, "put", put)
    monkeypatch.setattr(pod_driver.requests, "post", lambda url, **k: calls["post"].append(k["json"]) or Reply(200, {}))
    return calls, work


@pytest.mark.parametrize("status", [503, 409])
def test_nothing_is_stashed_when_the_console_wants_no_copy(monkeypatch, tmp_path, video, status):
    calls, _ = setup(monkeypatch, tmp_path, status)
    pod_driver.stash_for_archive(video, CALIB, POSES)
    assert calls["put"] == {} and calls["post"] == []


def test_a_part_without_poses_never_asks(monkeypatch, tmp_path, video):
    calls, _ = setup(monkeypatch, tmp_path, 200)
    pod_driver.stash_for_archive(video, CALIB, {})
    assert calls["get"] == 0 and calls["put"] == {}


def test_a_wanted_part_leaves_a_silent_proxy_its_poses_and_calibration(monkeypatch, tmp_path, video):
    calls, work = setup(monkeypatch, tmp_path, 200)
    pod_driver.stash_for_archive(video, CALIB, POSES)
    assert set(calls["put"]) == set(LINKS.values())
    stashed = tmp_path / "stashed.mp4"
    stashed.write_bytes(calls["put"][LINKS["proxy"]])
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(stashed)],
                             capture_output=True, text=True, check=True).stdout.split()
    assert streams == ["video"], "the sound is not kept"
    assert json.load(gzip.open(io.BytesIO(calls["put"][LINKS["poses"]]), "rt")) == POSES
    assert json.loads(calls["put"][LINKS["calib"]]) == CALIB
    assert calls["post"] == [{"frames": 30, "seconds": 1.0}]
    assert os.listdir(work) == [], "nothing left on the machine"


def test_a_failed_upload_reports_nothing_and_does_not_raise(monkeypatch, tmp_path, video):
    calls, work = setup(monkeypatch, tmp_path, 200, put_status=500)
    pod_driver.stash_for_archive(video, CALIB, POSES)
    assert calls["post"] == []
    assert os.listdir(work) == []
