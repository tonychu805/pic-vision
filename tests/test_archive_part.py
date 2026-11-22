"""pod_driver.archive_part: the redacted copy is kept only when the console asks and every frame made it."""
import os

os.environ.setdefault("JOB_ID", "test-job-id")
os.environ.setdefault("JOB_TOKEN", "test-token")
os.environ.setdefault("BUCKET", "test-bucket")
os.environ.setdefault("OUTPUT_BUCKET", "test-output-bucket")
os.environ.setdefault("BRAND_ID", "test-brand-id")

from cloud_pipeline import pod_driver  # noqa: E402
from src import session_archive  # noqa: E402

KEY = "b/part.mp4"
PUT_URL = "https://archive.example/b/part.mp4?X-Amz-Signature=s"


class Reply:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def setup(monkeypatch, tmp_path, get_status, redact):
    posts, uploads = [], []
    monkeypatch.setattr(pod_driver, "WORKDIR", str(tmp_path))
    monkeypatch.setattr(pod_driver.requests, "get", lambda *a, **k: Reply(get_status, {"key": KEY, "url": PUT_URL}))
    monkeypatch.setattr(pod_driver.requests, "put",
                        lambda url, data=None, headers=None, **k: uploads.append((url, len(data.read()), headers)) or Reply(200))
    monkeypatch.setattr(pod_driver.requests, "post", lambda url, **k: posts.append((url, k["json"])) or Reply(200, {}))
    monkeypatch.setattr(pod_driver.requests, "delete", lambda url, **k: posts.append((url, "DELETE")) or Reply(200, {}))
    monkeypatch.setattr(session_archive, "redact_video", redact)
    return posts, uploads


def written(src, dst, calib, poses, workers, **kwargs):
    open(dst, "wb").write(b"x" * 10)
    return {"frames": 300, "seconds": 10.0, "bytes": 10, "version": "v"}


def test_archive_off_here_does_nothing(monkeypatch, tmp_path):
    calls = []
    posts, uploads = setup(monkeypatch, tmp_path, 503, lambda *a, **k: calls.append(a))
    pod_driver.archive_part("video.mp4", {}, {})
    assert calls == [] and uploads == [] and posts == []


def test_a_refused_part_uploads_nothing_releases_its_machine_and_does_not_raise(monkeypatch, tmp_path):
    def refuse(src, dst, calib, poses, workers, **kwargs):
        open(dst, "wb").write(b"partial")
        raise session_archive.ArchiveRefused("no poses")
    posts, uploads = setup(monkeypatch, tmp_path, 200, refuse)
    pod_driver.archive_part("video.mp4", {}, {})
    assert uploads == []
    assert [p[1] for p in posts] == ["DELETE"], "the console is told to stop holding the machine"
    assert not os.path.exists(tmp_path / "archive.mp4")


def test_a_redacted_copy_goes_through_its_upload_link_and_is_reported(monkeypatch, tmp_path):
    posts, uploads = setup(monkeypatch, tmp_path, 200, written)
    pod_driver.archive_part("video.mp4", {}, {"0": []})
    assert uploads == [(PUT_URL, 10, {"Content-Type": "video/mp4"})], "the link, never the reels bucket"
    (url, body), = posts
    assert url.endswith("/archive") and body == {"key": KEY, "bytes": 10, "frames": 300, "seconds": 10.0, "version": "v"}
    assert not os.path.exists(tmp_path / "archive.mp4")


def test_the_archive_asks_the_console_whether_the_next_part_is_waiting(monkeypatch):
    asked = []

    def get(url, params=None, **k):
        asked.append(params)
        return Reply(200, {"waiting": True})
    monkeypatch.setattr(pod_driver.requests, "get", get)
    assert pod_driver.next_part_waiting("https://c/api/runner/jobs/j/archive", {}) is True
    assert asked == [{"probe": "next-part"}]
    monkeypatch.setattr(pod_driver.requests, "get", lambda *a, **k: Reply(200, {"waiting": False}))
    assert pod_driver.next_part_waiting("u", {}) is False
    monkeypatch.setattr(pod_driver.requests, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert pod_driver.next_part_waiting("u", {}) is False, "an unreachable console never stops a copy"


def test_a_copy_stopped_for_the_next_part_uploads_nothing_and_releases_the_machine(monkeypatch, tmp_path):
    def stopped(src, dst, calib, poses, workers, should_stop=None, **k):
        assert should_stop is not None
        raise session_archive.ArchiveRefused("stopped: the session's next part is waiting")
    posts, uploads = setup(monkeypatch, tmp_path, 200, stopped)
    pod_driver.archive_part("video.mp4", {}, {})
    assert uploads == [] and [p[1] for p in posts] == ["DELETE"]


def test_a_failed_upload_records_nothing_and_releases_the_machine(monkeypatch, tmp_path):
    posts, _ = setup(monkeypatch, tmp_path, 200, written)
    monkeypatch.setattr(pod_driver.requests, "put", lambda *a, **k: Reply(403))
    pod_driver.archive_part("video.mp4", {}, {"0": []})
    assert [p[1] for p in posts] == ["DELETE"], "no record of a file that isn't there"
    assert not os.path.exists(tmp_path / "archive.mp4")
