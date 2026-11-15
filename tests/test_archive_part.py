"""pod_driver.archive_part: the redacted copy is kept only when the console asks and every frame made it."""
import os

os.environ.setdefault("JOB_ID", "test-job-id")
os.environ.setdefault("JOB_TOKEN", "test-token")
os.environ.setdefault("BUCKET", "test-bucket")
os.environ.setdefault("OUTPUT_BUCKET", "test-output-bucket")
os.environ.setdefault("BRAND_ID", "test-brand-id")

from cloud_pipeline import pod_driver  # noqa: E402
from src import session_archive  # noqa: E402

KEY = "archive/b/j/part.mp4"


class Reply:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class S3:
    def __init__(self):
        self.uploads = []

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        self.uploads.append((os.path.getsize(path), bucket, key))


def setup(monkeypatch, tmp_path, get_status, redact):
    posts = []
    monkeypatch.setattr(pod_driver, "WORKDIR", str(tmp_path))
    monkeypatch.setattr(pod_driver.requests, "get", lambda *a, **k: Reply(get_status, {"key": KEY}))
    monkeypatch.setattr(pod_driver.requests, "post", lambda url, **k: posts.append((url, k["json"])) or Reply(200, {}))
    monkeypatch.setattr(pod_driver.requests, "delete", lambda url, **k: posts.append((url, "DELETE")) or Reply(200, {}))
    monkeypatch.setattr(session_archive, "redact_video", redact)
    return posts


def written(src, dst, poses, workers):
    open(dst, "wb").write(b"x" * 10)
    return {"frames": 300, "seconds": 10.0, "bytes": 10, "version": "v"}


def test_archive_off_here_does_nothing(monkeypatch, tmp_path):
    calls = []
    posts = setup(monkeypatch, tmp_path, 503, lambda *a, **k: calls.append(a))
    s3 = S3()
    pod_driver.archive_part(s3, "video.mp4", {})
    assert calls == [] and s3.uploads == [] and posts == []


def test_a_refused_part_uploads_nothing_releases_its_machine_and_does_not_raise(monkeypatch, tmp_path):
    def refuse(src, dst, poses, workers):
        open(dst, "wb").write(b"partial")
        raise session_archive.ArchiveRefused("no poses")
    posts = setup(monkeypatch, tmp_path, 200, refuse)
    s3 = S3()
    pod_driver.archive_part(s3, "video.mp4", {})
    assert s3.uploads == []
    assert [p[1] for p in posts] == ["DELETE"], "the console is told to stop holding the machine"
    assert not os.path.exists(tmp_path / "archive.mp4")


def test_a_redacted_copy_goes_to_its_key_and_is_reported(monkeypatch, tmp_path):
    posts = setup(monkeypatch, tmp_path, 200, written)
    s3 = S3()
    pod_driver.archive_part(s3, "video.mp4", {"0": []})
    assert s3.uploads == [(10, pod_driver.OUTPUT_BUCKET, KEY)]
    (url, body), = posts
    assert url.endswith("/archive") and body == {"key": KEY, "bytes": 10, "frames": 300, "seconds": 10.0, "version": "v"}
    assert not os.path.exists(tmp_path / "archive.mp4")
