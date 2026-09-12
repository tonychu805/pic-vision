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


def _no_real_r2_upload(monkeypatch):
    # run_reel_job() uploads a real deps tarball to R2 before creating a
    # pod -- stood in by every test that calls run_reel_job() (not
    # test_upload_pod_deps_..., which tests this function itself) so a
    # test can't silently start making real R2 calls, the same mistake
    # already made once this session with patch_job() before it was
    # mocked everywhere it needed to be.
    monkeypatch.setattr(job_runner, "_upload_pod_deps", lambda bucket: "https://example.invalid/fake-deps.tar")


def test_a_job_with_no_segments_is_refused_before_any_pod_is_created(monkeypatch):
    created = []
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: created.append(kw) or ("pod-1", "gpu"))
    with pytest.raises(RuntimeError, match="no recording segments"):
        job_runner.run_reel_job({**JOB, "segment_keys": []})
    assert created == [], "must not spend money creating a pod for a job that can't run"


def test_happy_path_creates_one_pod_and_returns_once_it_disappears(monkeypatch):
    _no_real_r2_upload(monkeypatch)
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
    # None = "couldn't tell" -- never confirms progress either way, so the
    # first-checkin timeout never fires here; stood in only to keep this
    # test from making a real network call to the console.
    monkeypatch.setattr(job_runner, "get_job_updated_at", lambda job_id: None)

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
    _no_real_r2_upload(monkeypatch)
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: ("pod-1", "gpu"))
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: False)
    monkeypatch.setattr(job_runner, "get_job_updated_at", lambda job_id: None)
    patched = []
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: patched.append((job_id, fields)) or False)

    job_runner.run_reel_job(JOB)

    assert len(patched) == 1
    reported_job_id, fields = patched[0]
    assert reported_job_id == "job-1"
    assert "error" in fields and "final status" in fields["error"]


def test_env_carries_the_real_job_and_fresh_reel_ids(monkeypatch):
    _no_real_r2_upload(monkeypatch)
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: True)
    monkeypatch.setattr(job_runner, "get_job_updated_at", lambda job_id: None)
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
    assert env["BOOTSTRAP_URL"] == "https://example.invalid/fake-deps.tar"


def test_upload_pod_deps_packages_pod_driver_and_its_real_dependency_closure(monkeypatch):
    # The one thing worth testing for real here, unmocked: a wrong file
    # list silently breaks every future pod (ImportError on the pod, not
    # locally), so this builds a real tarball from the real repo files
    # and checks what's actually in it -- not just that upload_file() got
    # called with some path.
    import tarfile

    uploaded = {}
    monkeypatch.setattr(job_runner.r2_storage, "upload_file",
                        lambda bucket, local_path, key: uploaded.update(
                            bucket=bucket, key=key,
                            members=sorted(tarfile.open(local_path).getnames())))
    monkeypatch.setattr(job_runner.r2_storage, "generate_presigned_url",
                        lambda bucket, key, expires_in=3600: "https://example.invalid/real-deps.tar")

    url = job_runner._upload_pod_deps("test-bucket")

    assert url == "https://example.invalid/real-deps.tar"
    assert uploaded["bucket"] == "test-bucket"
    assert uploaded["key"] == job_runner.POD_DEPS_KEY
    assert "pod_driver.py" in uploaded["members"]
    for rel in job_runner.POD_DEPS_FILES:
        assert rel in uploaded["members"], f"{rel} missing from the deps tarball"


def test_a_pod_that_never_finishes_is_terminated_and_reported_as_an_error(monkeypatch):
    # The one path with no live test yet: a pod that hangs past its
    # deadline (host failure, OOM -- anything pod_driver.py's own
    # exception handling never got a chance to catch).
    _no_real_r2_upload(monkeypatch)
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 0.05)
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: ("pod-1", "gpu"))
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: True)  # never goes away
    monkeypatch.setattr(job_runner, "get_job_updated_at", lambda job_id: None)
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


def test_a_pod_with_no_first_checkin_is_terminated_fast_rather_than_waiting_for_the_full_deadline(monkeypatch):
    # The actual incident this exists for (2026-09-12): a pod stuck
    # retrying its own container start, confirmed live via repeated
    # "start container: begin" log lines with nothing else ever printed
    # -- pod_driver.py never even started, so it never PATCHed anything.
    # A CONFIRMED read (not None) showing the job's updated_at hasn't
    # moved since it was claimed, held past FIRST_CHECKIN_TIMEOUT_SEC, is
    # what's supposed to catch that -- fast, not after JOB_DEADLINE_SEC.
    _no_real_r2_upload(monkeypatch)
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "FIRST_CHECKIN_TIMEOUT_SEC", 0.03)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 10)  # must not be what fires here
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: ("pod-1", "gpu"))
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: True)
    # Same value every read -- confirms the row is genuinely unchanged,
    # not just "we couldn't tell this time".
    monkeypatch.setattr(job_runner, "get_job_updated_at", lambda job_id: "2026-01-01T00:00:00Z")
    terminated = []
    monkeypatch.setattr(job_runner.runpod_pod, "terminate_pod", lambda pod_id: terminated.append(pod_id))
    patched = []
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: patched.append((job_id, fields)))

    job = {**JOB, "updated_at": "2026-01-01T00:00:00Z"}
    job_runner.run_reel_job(job)  # must not raise

    assert terminated == ["pod-1"]
    assert len(patched) == 1
    reported_job_id, fields = patched[0]
    assert reported_job_id == "job-1"
    assert "error" in fields
    assert "no progress" in fields["error"] and "ADR-101" in fields["error"]


def test_a_pod_that_checks_in_is_not_mistaken_for_stuck(monkeypatch):
    # The positive case: a pod that reports real progress must not trip
    # the fast-fail meant for one that never starts at all.
    _no_real_r2_upload(monkeypatch)
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "FIRST_CHECKIN_TIMEOUT_SEC", 0.02)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 10)
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: ("pod-1", "gpu"))
    calls = {"n": 0}

    def fake_exists(pod_id):
        calls["n"] += 1
        return calls["n"] < 3  # "still there" a couple of times, then gone -- a normal finish

    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", fake_exists)
    # Real progress: the value differs from the job's claimed-at baseline.
    monkeypatch.setattr(job_runner, "get_job_updated_at", lambda job_id: "2026-01-01T00:05:00Z")
    terminated = []
    monkeypatch.setattr(job_runner.runpod_pod, "terminate_pod", lambda pod_id: terminated.append(pod_id))
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: True)

    job = {**JOB, "updated_at": "2026-01-01T00:00:00Z"}
    job_runner.run_reel_job(job)  # must not raise

    assert terminated == [], "a pod that's actually reporting progress must not be terminated as stuck"


def test_failed_status_reads_never_count_toward_the_first_checkin_timeout(monkeypatch):
    # A run of None reads (console unreachable) must not be treated the
    # same as a confirmed-unchanged row -- that would terminate a pod
    # that might be perfectly healthy just because job_runner.py itself
    # couldn't reach the console for a while.
    _no_real_r2_upload(monkeypatch)
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "FIRST_CHECKIN_TIMEOUT_SEC", 0.02)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 0.1)
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: ("pod-1", "gpu"))
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: True)
    monkeypatch.setattr(job_runner, "get_job_updated_at", lambda job_id: None)
    terminated = []
    monkeypatch.setattr(job_runner.runpod_pod, "terminate_pod", lambda pod_id: terminated.append(pod_id))
    patched = []
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: patched.append((job_id, fields)))

    job = {**JOB, "updated_at": "2026-01-01T00:00:00Z"}
    job_runner.run_reel_job(job)  # must not raise -- only the real JOB_DEADLINE_SEC path fires

    assert len(patched) == 1
    reported_job_id, fields = patched[0]
    assert "error" in fields
    # The real JOB_DEADLINE_SEC message, not the first-checkin one --
    # proves None reads didn't get mistaken for a confirmed-stuck pod.
    assert "minutes without finishing" in fields["error"]
    assert "ADR-101" not in fields["error"]
