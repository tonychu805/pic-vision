# run_reel_job()'s actual work (create a pod, wait for it) is a thin
# wrapper around runpod_pod's real API calls, already exercised for real
# against RunPod (2026-09-10, DECISIONS.md ADR-093). What's worth pinning
# here without spending real pod-minutes is the two decisions this
# function makes on its own: refuse a job with nothing to process, and --
# never yet exercised, live or otherwise -- the deadline watchdog that's
# the only thing standing between a hung pod and billing forever
# (ADR-093's still-open "who kills an orphaned pod" risk).
import os

import pytest

os.environ.setdefault("RUNNER_TOKEN", "test-token")
os.environ.setdefault("CLOUDFLARE_R2_ACCESS_KEY_ID", "fake")
os.environ.setdefault("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "fake")
os.environ.setdefault("CLOUDFLARE_R2_ACCOUNT_ID", "fake")
os.environ.setdefault("RUNPOD_API_KEY", "fake")

from cloud_pipeline import job_runner  # noqa: E402

JOB = {
    "id": "job-1", "bucket": "test-bucket", "calib": {"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]},
    "segment_keys": ["segments/a.mkv", "segments/b.mkv"], "target_sec": 300, "session_id": "sess-1",
}


def test_a_job_with_no_segments_is_refused_before_any_pod_is_created(monkeypatch):
    created = []
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: created.append(kw) or ("pod-1", "gpu"))
    with pytest.raises(RuntimeError, match="no recording segments"):
        job_runner.run_reel_job({**JOB, "segment_keys": []})
    assert created == [], "must not spend money creating a pod for a job that can't run"


def test_happy_path_creates_one_pod_and_returns_once_it_disappears(monkeypatch):
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 10)
    exists_calls = {"n": 0}
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: ("pod-1", "NVIDIA RTX 2000 Ada Generation"))

    def fake_exists(pod_id):
        exists_calls["n"] += 1
        assert pod_id == "pod-1"
        return exists_calls["n"] < 3  # "still there" twice, then gone

    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", fake_exists)
    terminated = []
    monkeypatch.setattr(job_runner.runpod_pod, "terminate_pod", lambda pod_id: terminated.append(pod_id))
    # A real job that finished on its own already reported done/error/
    # cancelled itself, so the console's status != 'running' guard turns
    # this into a no-op 409 -- stood in for here rather than let the test
    # hit the real console.
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: True)

    job_runner.run_reel_job(JOB)  # must not raise
    assert exists_calls["n"] == 3
    assert terminated == [], "a pod that finished on its own must not also be force-terminated"


def test_a_pod_that_disappears_without_ever_reporting_is_marked_errored(monkeypatch):
    # 2026-09-10, found for real: a pod terminated out from under this loop
    # (not via the deadline path) left its console job stuck at
    # status='running' forever -- nothing checked whether it had actually
    # reported a terminal status before treating its disappearance as
    # success. This is the fix: unconditionally try to mark it errored:
    # if it DID report already, the console's own guard makes this a no-op.
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: ("pod-1", "gpu"))
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: False)
    patched = []
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: patched.append((job_id, fields)) or False)

    job_runner.run_reel_job(JOB)

    assert len(patched) == 1
    reported_job_id, fields = patched[0]
    assert reported_job_id == "job-1"
    assert "error" in fields and "final status" in fields["error"]


def test_env_carries_the_real_job_and_fresh_reel_ids(monkeypatch):
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: True)
    captured = {}
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: captured.update(kw) or ("pod-1", "gpu"))
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: False)

    job_runner.run_reel_job(JOB)

    env = captured["env"]
    assert env["JOB_ID"] == "job-1"
    assert env["BUCKET"] == "test-bucket"
    assert env["SESSION_ID"] == "sess-1"
    assert env["TARGET_SEC"] == "300"
    import json
    assert json.loads(env["SEGMENT_KEYS_JSON"]) == JOB["segment_keys"]
    assert json.loads(env["CALIB_JSON"]) == JOB["calib"]
    # Every id present and none blank -- these are what let the console's
    # PATCH route insert the reels rows the moment the pod reports done.
    for key in ("REEL_ID", "BURST_REEL_ID", "SHARE_ID"):
        assert env[key], f"{key} must be a real minted id"
    assert env["REEL_ID"] != env["BURST_REEL_ID"] != env["SHARE_ID"]


def test_a_pod_that_never_finishes_is_terminated_and_reported_as_an_error(monkeypatch):
    # The one path with no live test yet: a pod that hangs past its
    # deadline (host failure, OOM -- anything pod_driver.py's own
    # exception handling never got a chance to catch).
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 0.05)
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: ("pod-1", "gpu"))
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: True)  # never goes away
    terminated = []
    monkeypatch.setattr(job_runner.runpod_pod, "terminate_pod", lambda pod_id: terminated.append(pod_id))
    patched = []
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: patched.append((job_id, fields)))

    job_runner.run_reel_job(JOB)  # must not raise -- the deadline path handles this itself

    assert terminated == ["pod-1"], "a hung pod must be terminated, not left running (and billing)"
    assert len(patched) == 1
    reported_job_id, fields = patched[0]
    assert reported_job_id == "job-1"
    assert "error" in fields and "minutes" in fields["error"]
