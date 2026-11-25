"""src/archive_job: a venue's nightly copies, one stashed part at a time, nothing unblurred kept on failure."""
import gzip
import io
import json
import os

import requests

from src import archive_job
from src.session_archive import ArchiveRefused

BASE = "https://console/api/runner/jobs/j1/archive"


def item(n):
    return {"input_id": f"in{n}", "proxy_url": f"p{n}", "poses_url": f"q{n}", "calib_url": f"c{n}",
            "upload_url": f"u{n}", "key": f"brand/2026-11/{n}.mp4"}


class Reply:
    def __init__(self, status=200, body=None, raw=b""):
        self.status_code, self._body, self.raw = status, body, io.BytesIO(raw)

    def iter_content(self, size):
        return iter(lambda: self.raw.read(size), b"")
        self.ok = status < 400

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Console:
    """Hands out `items` in order, then done; serves the stashed files; records uploads and reports."""

    def __init__(self, items, broken_downloads=()):
        self.items, self.broken = list(items), set(broken_downloads)
        self.reports, self.uploads = [], []

    def get(self, url, stream=False, **k):
        if url == f"{BASE}/next":
            return Reply(body=self.items.pop(0) if self.items else {"done": True})
        if url in self.broken:
            return Reply(404)
        if url.startswith("q"):
            return Reply(raw=gzip.compress(json.dumps({"0": []}).encode()))
        if url.startswith("c"):
            return Reply(raw=b"{}")
        return Reply(raw=b"video")

    def put(self, url, data=None, **k):
        self.uploads.append((url, data.read()))
        return Reply()

    def post(self, url, json=None, **k):
        assert url == f"{BASE}/report"
        self.reports.append(json)
        return Reply(body={})


def redact_ok(src, dst, calib, poses, workers=None, should_stop=None):
    open(dst, "wb").write(b"blurred")
    return {"frames": 300, "seconds": 10.0, "bytes": 7, "version": "v3"}


def test_every_stashed_part_is_copied_uploaded_and_reported_in_order(tmp_path):
    console = Console([item(1), item(2)])
    kept, failures = archive_job.run("https://console", "j1", "t", deadline=1e12, workdir=str(tmp_path), http=console, redact=redact_ok)
    assert (kept, len(failures)) == (2, 0)
    assert [u for u, _ in console.uploads] == ["u1", "u2"]
    assert [r["input_id"] for r in console.reports] == ["in1", "in2"]
    assert console.reports[0] == {"input_id": "in1", "key": "brand/2026-11/1.mp4", "bytes": 7, "frames": 300,
                                  "seconds": 10.0, "version": "v3"}
    assert os.listdir(tmp_path) == []


def test_a_part_that_fails_is_reported_failed_and_the_night_goes_on(tmp_path):
    console = Console([item(1), item(2)], broken_downloads={"p1"})
    kept, failures = archive_job.run("https://console", "j1", "t", deadline=1e12, workdir=str(tmp_path), http=console, redact=redact_ok)
    assert (kept, len(failures)) == (1, 1)
    assert failures == [console.reports[0]["failed"]], "the reason reaches the job result"
    assert console.reports[0]["input_id"] == "in1" and "failed" in console.reports[0] and "key" not in console.reports[0]
    assert [u for u, _ in console.uploads] == ["u2"]
    assert os.listdir(tmp_path) == []


def test_the_deadline_stops_the_copy_in_progress_and_keeps_nothing(tmp_path):
    clock = {"t": 0.0}

    def redact_until_stopped(src, dst, calib, poses, workers=None, should_stop=None):
        clock["t"] = 100.0
        assert should_stop()
        raise ArchiveRefused("stopped")
    console = Console([item(1), item(2)])
    kept, failures = archive_job.run("https://console", "j1", "t", deadline=50.0, workdir=str(tmp_path),
                                   now=lambda: clock["t"], http=console, redact=redact_until_stopped)
    assert (kept, len(failures)) == (0, 1)
    assert console.uploads == []
    assert len(console.items) == 1, "no further part is asked for after the deadline"


def test_nothing_is_asked_for_once_the_deadline_has_passed(tmp_path):
    console = Console([item(1)])
    assert archive_job.run("https://console", "j1", "t", deadline=0.0, workdir=str(tmp_path),
                           now=lambda: 1.0, http=console, redact=redact_ok) == (0, [])
    assert len(console.items) == 1


def test_the_job_reports_in_at_once_and_reports_done_at_the_end(monkeypatch):
    patches = []

    class Ok:
        status_code, ok = 200, True

        def raise_for_status(self):
            pass
    monkeypatch.setattr(archive_job.requests, "patch", lambda url, json=None, **k: patches.append(json) or Ok())
    monkeypatch.setattr(archive_job, "run", lambda *a, **k: (3, ["ArchiveRefused: no poses"]))
    monkeypatch.setenv("JOB_ID", "j1")
    monkeypatch.setenv("JOB_TOKEN", "t")
    monkeypatch.setenv("ARCHIVE_DEADLINE", "1e12")
    assert archive_job.main() == 0
    assert patches[0]["stage"] == "archiving", "the orchestrator sees the machine started"
    assert patches[-1]["done"] is True and patches[-1]["result"] == {"archive_kept": 3, "archive_failed": 1,
                                                               "archive_failures": ["ArchiveRefused: no poses"]}


def test_a_download_r2_sends_gzipped_on_the_fly_is_saved_decoded(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    calib = json.dumps({"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}).encode()

    class R2Like(BaseHTTPRequestHandler):
        def do_GET(self):
            body = gzip.compress(calib)
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    server = HTTPServer(("127.0.0.1", 0), R2Like)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        archive_job._download(f"http://127.0.0.1:{server.server_port}/calib.json", tmp_path / "calib.json", requests)
    finally:
        server.shutdown()
    assert json.loads((tmp_path / "calib.json").read_text()) == json.loads(calib)
