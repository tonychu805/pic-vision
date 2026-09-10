# The bulk of pod_driver.py (R2 downloads, ffmpeg, GPU inference) can't be
# meaningfully unit-tested any more than run_cloud_job.py's equivalent
# steps could -- it needs a real pod. What IS testable without one is the
# one piece every stage depends on: the cancellation channel. A cancel
# request has to actually stop a running pod (which is billed per minute),
# so this is worth pinning even though the rest needs a real RunPod job to
# verify (cloud_pipeline/pod_driver.py's own module docstring explains the
# HTTPS-reporting design this exercises).
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

os.environ.setdefault("JOB_ID", "test-job-id")
os.environ.setdefault("RUNNER_TOKEN", "test-token")
os.environ.setdefault("BUCKET", "test-bucket")

from cloud_pipeline import pod_driver  # noqa: E402


def _fake_console(responses):
    """A real local HTTP server standing in for the console's
    PATCH /api/runner/jobs/<id> route -- same reasoning as
    bandwidth.test.js's withServer(): a mocked request object would only
    prove the mock, not that patch_job() sends what the real route expects."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_PATCH(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            status, payload = responses.pop(0)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload.encode())

        def log_message(self, *a):
            pass  # keep test output clean

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, seen


@pytest.fixture
def console_url(monkeypatch):
    def _start(responses):
        server, seen = _fake_console(responses)
        monkeypatch.setattr(pod_driver, "CONSOLE_URL", f"http://127.0.0.1:{server.server_port}")
        return seen, server
    started = []

    def start(responses):
        seen, server = _start(responses)
        started.append(server)
        return seen
    yield start
    for s in started:
        s.shutdown()


def test_patch_job_sends_the_job_id_and_bearer_token(console_url):
    seen = console_url([(200, '{"cancelRequested": false}')])
    result = pod_driver.patch_job(stage="convert", message="converting...")
    assert result is False
    assert len(seen) == 1
    assert seen[0]["path"] == "/api/runner/jobs/test-job-id"
    assert seen[0]["auth"] == "Bearer test-token"
    assert b'"stage": "convert"' in seen[0]["body"] or b'"stage":"convert"' in seen[0]["body"]


def test_patch_job_treats_409_as_a_cancel_signal(console_url):
    # A 409 means the console reclaimed this job (another runner, or an
    # operator cancel) -- same contract job_runner.py's own patch_job uses.
    console_url([(409, "")])
    assert pod_driver.patch_job(stage="cut") is True


def test_patch_job_treats_explicit_cancelRequested_as_a_cancel_signal(console_url):
    console_url([(200, '{"cancelRequested": true}')])
    assert pod_driver.patch_job(stage="inference") is True


def test_console_unreachable_does_not_stop_a_running_gpu_job(monkeypatch):
    # Pointed at a port nothing is listening on -- the console being briefly
    # unreachable must not read as "cancel", or a network blip would kill a
    # job already running (and being billed for) on a real GPU pod.
    monkeypatch.setattr(pod_driver, "CONSOLE_URL", "http://127.0.0.1:1")
    assert pod_driver.patch_job(stage="inference") is False


def test_check_cancel_raises_when_the_console_says_stop(console_url):
    console_url([(200, '{"cancelRequested": true}')])
    with pytest.raises(pod_driver.Cancelled):
        pod_driver._check_cancel("cut", "detecting rallies...")


def test_check_cancel_is_silent_when_the_console_says_continue(console_url):
    console_url([(200, '{"cancelRequested": false}')])
    pod_driver._check_cancel("cut", "detecting rallies...")  # must not raise
