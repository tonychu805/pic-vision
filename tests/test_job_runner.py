# The runner fits calibrations only; reel jobs run on the Cloudflare
# orchestrator (ADR-125). Its old reel path (RunPod REST v1, retired
# 2026-11-15) went to archive/ with runpod_pod.py, and its tests with it.
import os

import pytest

os.environ.setdefault("RUNNER_TOKEN", "test-token")
os.environ.setdefault("CLOUDFLARE_R2_ACCESS_KEY_ID", "fake")
os.environ.setdefault("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "fake")
os.environ.setdefault("CLOUDFLARE_R2_ACCOUNT_ID", "fake")

from cloud_pipeline import job_runner  # noqa: E402

JOB = {"id": "job-1", "bucket": "test-bucket", "kind": "calibration",
       "params": {"snapshotKey": "snap.png", "points": [[0, 0]]}}


def test_the_runner_claims_calibrations_only():
    assert job_runner.RUNNER_KINDS == ["calibration"]


def test_a_reel_job_claimed_by_mistake_is_refused_and_reported(monkeypatch, tmp_path):
    patches = []
    monkeypatch.setattr(job_runner, "WORK_DIR", str(tmp_path))
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **f: patches.append((job_id, f)))
    monkeypatch.setattr(job_runner, "run_calibration_job", lambda job: pytest.fail("ran a reel job as a calibration"))
    job_runner.run_one({"id": "job-2", "kind": "reel"})
    assert len(patches) == 1
    assert "orchestrator" in patches[0][1]["error"]


def test_a_calibration_job_still_runs(monkeypatch, tmp_path):
    ran = []
    monkeypatch.setattr(job_runner, "WORK_DIR", str(tmp_path))
    monkeypatch.setattr(job_runner, "run_calibration_job", lambda job: ran.append(job["id"]))
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **f: pytest.fail(f"reported {f}"))
    job_runner.run_one(dict(JOB))
    assert ran == ["job-1"]

def test_the_runner_never_deletes_uploaded_segments(monkeypatch, tmp_path):
    # _cleanup doesn't even read the job's outcome any more: no path through
    # it, success included, may delete a venue's upload.
    monkeypatch.setattr(job_runner.r2_storage, "delete_object",
                        lambda bucket, key: pytest.fail(f"runner deleted {key}"))
    monkeypatch.setattr(job_runner, "WORK_DIR", str(tmp_path))
    job_runner._cleanup(dict(JOB), str(tmp_path / "job-1"))


def test_cleanup_always_removes_the_local_scratch_directory(monkeypatch, tmp_path):
    # Local scratch is unconditional in both directions -- it's rebuildable
    # and it's on our own disk, unlike the venue's upload.
    job_dir = tmp_path / "job-1"
    job_dir.mkdir()
    (job_dir / "log.txt").write_text("some log output")
    monkeypatch.setattr(job_runner, "WORK_DIR", str(tmp_path))
    job_runner._cleanup(dict(JOB), str(job_dir))
    assert not job_dir.exists()
    assert (tmp_path / "logs" / "job-1.log").read_text() == "some log output"


# --- idle backoff (2026-09-20) ----------------------------------------
#
# The loop polled every POLL_SEC forever: ~518k cloud-function calls a
# month doing nothing, which exhausted the Netlify quota and took the
# console, share links and marketing site down for five days. The runner's
# own "claim failed" lines went to journald, which nobody watches.
#
# Paired deliberately: the test that a long idle backs off sits beside the
# test that a busy runner still polls tightly. A backoff that only ever
# slowed down would pass the first alone and quietly add a minute to every
# job pickup.

def test_a_long_idle_backs_off():
    from cloud_pipeline.job_runner import idle_sleep_sec, IDLE_MAX_SEC
    assert idle_sleep_sec(50) == IDLE_MAX_SEC


def test_the_first_few_empty_polls_stay_fast():
    # A job queued moments after the previous one finished is the common
    # case; making that wait a full minute would be a regression.
    from cloud_pipeline.job_runner import idle_sleep_sec, POLL_SEC, IDLE_RAMP_AFTER
    for i in range(IDLE_RAMP_AFTER):
        assert idle_sleep_sec(i) == POLL_SEC


def test_the_ramp_is_monotonic_and_never_below_the_floor():
    from cloud_pipeline.job_runner import idle_sleep_sec, POLL_SEC, IDLE_MAX_SEC
    waits = [idle_sleep_sec(i) for i in range(20)]
    assert waits == sorted(waits)
    assert all(POLL_SEC <= w <= IDLE_MAX_SEC for w in waits)


def test_the_idle_ceiling_actually_cuts_the_call_volume():
    # The number that matters: what an idle month costs. Pinned so a
    # future tweak to IDLE_MAX_SEC has to face the bill it creates.
    from cloud_pipeline.job_runner import IDLE_MAX_SEC
    calls_per_month = 30 * 24 * 3600 / IDLE_MAX_SEC
    assert calls_per_month <= 50_000, f"{calls_per_month:.0f} calls/month while idle"


# --- several jobs at once ---

def test_capacity_is_available_below_the_cap():
    assert job_runner.has_capacity(job_runner.MAX_CONCURRENT_JOBS - 1) is True


def test_capacity_is_exhausted_at_the_cap():
    assert job_runner.has_capacity(job_runner.MAX_CONCURRENT_JOBS) is False


def test_capacity_is_exhausted_past_the_cap():
    # Belt and suspenders: a transient overshoot (e.g. a race in main()'s
    # own bookkeeping) must still read as "no capacity", not wrap around.
    assert job_runner.has_capacity(job_runner.MAX_CONCURRENT_JOBS + 1) is False


# --- RUNNER_KINDS (ADR-125): this runner claims calibrations only ---


def _claim_body(monkeypatch, kinds):
    sent = {}

    class R:
        status_code = 204

    monkeypatch.setattr(job_runner, "RUNNER_KINDS", kinds)
    monkeypatch.setattr(job_runner.requests, "post", lambda url, json=None, **kw: sent.update(json) or R())
    job_runner.claim_job()
    return sent


def test_a_calibration_only_runner_says_so_when_claiming(monkeypatch):
    assert _claim_body(monkeypatch, ["calibration"])["kinds"] == ["calibration"]
