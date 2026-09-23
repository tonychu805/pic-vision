# run_reel_job()'s actual work (create a pod, wait for it) is a thin
# wrapper around runpod_pod's real API calls, already exercised for real
# against RunPod (2026-09-10, DECISIONS.md ADR-093). What's worth pinning
# here without spending real pod-minutes is the two decisions this
# function makes on its own: refuse a job with nothing to process, and --
# never yet exercised, live or otherwise -- the deadline watchdog that's
# the only thing standing between a hung pod and billing forever
# (ADR-093's still-open "who kills an orphaned pod" risk).
import os
import time

import pytest

os.environ.setdefault("RUNNER_TOKEN", "test-token")
os.environ.setdefault("CLOUDFLARE_R2_ACCESS_KEY_ID", "fake")
os.environ.setdefault("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "fake")
os.environ.setdefault("CLOUDFLARE_R2_ACCOUNT_ID", "fake")
os.environ.setdefault("RUNPOD_API_KEY", "fake")

from cloud_pipeline import job_runner  # noqa: E402

JOB = {
    "id": "job-1", "bucket": "test-bucket", "brand_id": "11111111-1111-1111-1111-111111111111",
    "calib": {"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]},
    "segment_keys": ["segments/a.mkv", "segments/b.mkv"], "target_sec": 300, "session_id": "sess-1",
}


FAKE_CREDENTIALS = {
    "readBucket": "test-bucket",
    "writeBucket": "test-public-bucket",
    "read": {"accessKeyId": "READ-KEY", "secretAccessKey": "READ-SECRET", "sessionToken": "READ-TOKEN"},
    "write": {"accessKeyId": "WRITE-KEY", "secretAccessKey": "WRITE-SECRET", "sessionToken": "WRITE-TOKEN"},
    "expiresAt": "2099-01-01T00:00:00.000Z",
}


def _state(updated_at, cancel_requested=False):
    """What get_job_state() returns for a confirmed read of the job row."""
    return {"updated_at": updated_at, "cancel_requested": cancel_requested}


def _no_real_network(monkeypatch, credentials=None):
    # run_reel_job() uploads a real deps tarball to R2 AND asks the console
    # for this job's scoped credentials (PIC-138) before creating a pod --
    # both stood in by every test that calls run_reel_job() (not the tests
    # of those functions themselves) so a test can't silently start making
    # real network calls. Not a hypothetical: when the credentials call was
    # added, the first existing test to reach it made a REAL request to the
    # production console and got a genuine 401 back, because its token is
    # fake. Nothing leaked, but only because the token was fake.
    monkeypatch.setattr(job_runner, "_upload_pod_deps", lambda bucket: "https://example.invalid/fake-deps.tar")
    monkeypatch.setattr(job_runner, "fetch_pod_credentials",
                        lambda job_id: credentials if credentials is not None else FAKE_CREDENTIALS)


def test_a_job_with_no_segments_is_refused_before_any_pod_is_created(monkeypatch):
    created = []
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: created.append(kw) or ("pod-1", "gpu"))
    with pytest.raises(RuntimeError, match="no recording segments"):
        job_runner.run_reel_job({**JOB, "segment_keys": []})
    assert created == [], "must not spend money creating a pod for a job that can't run"


def test_a_job_with_no_brand_id_is_refused_rather_than_guessing_a_reel_key(monkeypatch):
    # PIC-153 (2026-09-18): a reel key with no brand prefix, or a wrong
    # one, either breaks lib/reels.ts's validation or -- worse -- silently
    # lands in the wrong venue's data. Refusing outright beats guessing.
    _no_real_network(monkeypatch)
    created = []
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: created.append(kw) or ("pod-1", "gpu"))
    with pytest.raises(RuntimeError, match="no brand_id"):
        job_runner.run_reel_job({**JOB, "brand_id": None})
    assert created == [], "must not spend money creating a pod for a job it can't safely finish"


def test_the_pod_receives_the_brand_id_and_a_separate_output_bucket(monkeypatch):
    # BUCKET (job["bucket"]) is where this job's raw segments actually
    # are -- the private bucket, since PIC-153. OUTPUT_BUCKET is the
    # separate, public one the finished reel goes to. Conflating the two
    # would either write a private bucket key the public CDN can't serve,
    # or (the dangerous direction) write raw footage into the public one.
    # The output bucket now comes back from the console with the
    # credentials (each is bound to exactly one bucket, so the runner must
    # not be able to disagree with it), not from an env var of the runner's.
    _no_real_network(monkeypatch, {**FAKE_CREDENTIALS, "readBucket": "the-private-bucket", "writeBucket": "the-public-bucket"})
    monkeypatch.setenv("R2_INGEST_BUCKET", "an-env-var-that-must-now-be-ignored")
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    captured = {}
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: captured.update(kw) or ("pod-1", "gpu"))
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: False)
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: None)

    job_runner.run_reel_job({**JOB, "bucket": "the-private-bucket", "brand_id": "brand-xyz"})

    assert captured["env"]["BRAND_ID"] == "brand-xyz"
    assert captured["env"]["BUCKET"] == "the-private-bucket"
    assert captured["env"]["OUTPUT_BUCKET"] == "the-public-bucket"


def test_happy_path_creates_one_pod_and_returns_once_it_disappears(monkeypatch):
    _no_real_network(monkeypatch)
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
    monkeypatch.setattr(job_runner, "get_job_state", lambda job_id: None)

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
    _no_real_network(monkeypatch)
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: ("pod-1", "gpu"))
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: False)
    monkeypatch.setattr(job_runner, "get_job_state", lambda job_id: None)
    patched = []
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: patched.append((job_id, fields)) or False)

    job_runner.run_reel_job(JOB)

    assert len(patched) == 1
    reported_job_id, fields = patched[0]
    assert reported_job_id == "job-1"
    assert "error" in fields and "final status" in fields["error"]


def test_env_carries_the_real_job_and_fresh_reel_ids(monkeypatch):
    _no_real_network(monkeypatch)
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: True)
    monkeypatch.setattr(job_runner, "get_job_state", lambda job_id: None)
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
    _no_real_network(monkeypatch)
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 0.05)
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: ("pod-1", "gpu"))
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: True)  # never goes away
    monkeypatch.setattr(job_runner, "get_job_state", lambda job_id: None)
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
    _no_real_network(monkeypatch)
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "FIRST_CHECKIN_TIMEOUT_SEC", 0.03)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 10)  # must not be what fires here
    created = []
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: created.append(kw["image"]) or ("pod-1", "gpu"))
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: True)
    # Same value every read -- confirms the row is genuinely unchanged,
    # not just "we couldn't tell this time".
    monkeypatch.setattr(job_runner, "get_job_state", lambda job_id: _state("2026-01-01T00:00:00Z"))
    terminated = []
    monkeypatch.setattr(job_runner.runpod_pod, "terminate_pod", lambda pod_id: terminated.append(pod_id))
    patched = []
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: patched.append((job_id, fields)))

    job = {**JOB, "updated_at": "2026-01-01T00:00:00Z"}
    job_runner.run_reel_job(job)  # must not raise

    # Every attempt's pod is killed -- a stuck container still bills.
    assert terminated == ["pod-1", "pod-1"]
    # ...and the second one uses the backup image (2026-09-18), so a
    # missing or broken primary tag is survivable without a code change.
    assert created == job_runner.runpod_pod.POD_IMAGES
    # One error, reported only once both attempts are spent: a job that
    # would have succeeded on the retry must never flash an error at the
    # venue on its way there.
    assert len(patched) == 1
    reported_job_id, fields = patched[0]
    assert reported_job_id == "job-1"
    assert "error" in fields
    assert "no progress" in fields["error"] and "ADR-101" in fields["error"]


def test_a_stuck_first_attempt_is_rescued_by_the_retry(monkeypatch):
    # The case worth having: the first pod never checks in, the second
    # one does and finishes normally. The venue gets its reel and never
    # hears about any of it.
    _no_real_network(monkeypatch)
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "FIRST_CHECKIN_TIMEOUT_SEC", 0.03)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 10)
    created = []
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: created.append(kw["image"]) or (f"pod-{len(created)}", "gpu"))
    # The first pod stays put and silent; the second reports in, then
    # disappears the way a finished pod does.
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: pod_id == "pod-1")
    reads = {"n": 0}

    def updated_at(job_id):
        reads["n"] += 1
        # Unchanged while pod-1 is up; moves once pod-2 exists.
        return _state("2026-01-01T00:00:00Z" if len(created) < 2 else "2026-01-01T00:05:00Z")

    monkeypatch.setattr(job_runner, "get_job_state", updated_at)
    monkeypatch.setattr(job_runner.runpod_pod, "terminate_pod", lambda pod_id: None)
    patched = []
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: patched.append(fields))

    job_runner.run_reel_job({**JOB, "updated_at": "2026-01-01T00:00:00Z"})

    assert created == job_runner.runpod_pod.POD_IMAGES, "should have moved on to the backup image"
    # The rescued attempt ends the ordinary way -- the pod vanishes, and
    # this loop sends its usual "disappeared" line, which the console drops
    # with a 409 when the pod has already reported done itself. What must
    # NOT appear is the stuck-container error: the first attempt's failure
    # is the retry's business, not the venue's.
    assert not any("ADR-101" in (f.get("error") or "") for f in patched), \
        f"a rescued job must not report the stuck-container failure: {patched}"


def test_a_pod_that_checks_in_is_never_retried(monkeypatch):
    # The other half: a working job must not create a second pod. Getting
    # this wrong would double the GPU bill on every successful run.
    _no_real_network(monkeypatch)
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "FIRST_CHECKIN_TIMEOUT_SEC", 5)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 10)
    created = []
    calls = {"exists": 0}

    def pod_exists(pod_id):
        calls["exists"] += 1
        return calls["exists"] < 3  # finishes on the third poll

    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: created.append(kw["image"]) or ("pod-1", "gpu"))
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", pod_exists)
    monkeypatch.setattr(job_runner, "get_job_state", lambda job_id: _state("2026-01-01T00:05:00Z"))
    monkeypatch.setattr(job_runner.runpod_pod, "terminate_pod", lambda pod_id: None)
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: None)

    job_runner.run_reel_job({**JOB, "updated_at": "2026-01-01T00:00:00Z"})

    assert created == [job_runner.runpod_pod.POD_IMAGES[0]], "one pod, on the primary image"


def test_a_pod_that_checks_in_is_not_mistaken_for_stuck(monkeypatch):
    # The positive case: a pod that reports real progress must not trip
    # the fast-fail meant for one that never starts at all.
    _no_real_network(monkeypatch)
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
    monkeypatch.setattr(job_runner, "get_job_state", lambda job_id: _state("2026-01-01T00:05:00Z"))
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
    _no_real_network(monkeypatch)
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "FIRST_CHECKIN_TIMEOUT_SEC", 0.02)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 0.1)
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: ("pod-1", "gpu"))
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: True)
    monkeypatch.setattr(job_runner, "get_job_state", lambda job_id: None)
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


# --- _cleanup: the runner never deletes a venue's upload (ADR-125) ---
#
# Deleting after success moved to the console, which can honour a venue's
# choice to keep footage for training (lib/footageRetention.ts, whose tests
# hold the paired "still deletes by default" half). What must hold here is
# that no outcome -- success included -- makes this process delete one.


@pytest.mark.parametrize("status", ["done", "error", "cancelled", None])
def test_the_runner_never_deletes_uploaded_segments_whatever_the_outcome(monkeypatch, tmp_path, status):
    monkeypatch.setattr(job_runner, "get_job_status", lambda job_id: status)
    monkeypatch.setattr(job_runner.r2_storage, "delete_object",
                        lambda bucket, key: pytest.fail(f"runner deleted {key} after a {status} job"))
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


# --- PIC-138: a pod runs on scoped credentials, never the account's keys ----
#
# A pod used to be handed the account's full R2 keys: read, write and delete
# across every venue's footage and reels. It is disposable, internet-facing
# hardware running ffmpeg and TensorFlow over footage a stranger recorded, so
# "compromised pod" has to be survivable.
#
# Paired deliberately, per CLAUDE.md ("remove the secret, then prove it still
# works"). The test that no account key reaches the pod sits beside the test
# that the scoped credentials DO -- removal alone would pass with no
# credentials at all, which is a pod that cannot reach R2.

PARENT_SECRET = "ACCOUNT-SECRET-THAT-MUST-NEVER-REACH-A-POD"


def _run_and_capture_pod_env(monkeypatch, credentials=None):
    _no_real_network(monkeypatch, credentials)
    monkeypatch.setenv("CLOUDFLARE_R2_ACCESS_KEY_ID", "ACCOUNT-KEY-ID")
    monkeypatch.setenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", PARENT_SECRET)
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: True)
    monkeypatch.setattr(job_runner, "get_job_state", lambda job_id: None)
    captured = {}
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: captured.update(kw) or ("pod-1", "gpu"))
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: False)
    job_runner.run_reel_job(JOB)
    return captured["env"]


def test_no_account_r2_key_reaches_the_pod(monkeypatch):
    env = _run_and_capture_pod_env(monkeypatch)
    assert "CLOUDFLARE_R2_ACCESS_KEY_ID" not in env
    assert "CLOUDFLARE_R2_SECRET_ACCESS_KEY" not in env
    everything = " ".join(f"{k}={v}" for k, v in env.items())
    assert PARENT_SECRET not in everything, "the account secret is in the pod's environment"
    assert "ACCOUNT-KEY-ID" not in everything


def test_the_pod_does_receive_the_scoped_credentials(monkeypatch):
    # The paired half. Without it the test above passes for a pod holding
    # nothing -- one that fails at its first download.
    env = _run_and_capture_pod_env(monkeypatch)
    assert env["R2_READ_ACCESS_KEY_ID"] == "READ-KEY"
    assert env["R2_READ_SECRET_ACCESS_KEY"] == "READ-SECRET"
    assert env["R2_READ_SESSION_TOKEN"] == "READ-TOKEN"
    assert env["R2_WRITE_ACCESS_KEY_ID"] == "WRITE-KEY"
    assert env["R2_WRITE_SECRET_ACCESS_KEY"] == "WRITE-SECRET"
    assert env["R2_WRITE_SESSION_TOKEN"] == "WRITE-TOKEN"
    # Needed for the endpoint URL and not a secret, so it stays.
    assert env["CLOUDFLARE_R2_ACCOUNT_ID"]


def test_the_read_and_write_credentials_are_kept_apart(monkeypatch):
    # Each is bound to one bucket by R2. Crossing them would hand the
    # reel-writing credential to the code that reads footage, or the
    # reverse, and the pod would 403 on its first real call.
    env = _run_and_capture_pod_env(monkeypatch)
    read_values = {v for k, v in env.items() if k.startswith("R2_READ_")}
    write_values = {v for k, v in env.items() if k.startswith("R2_WRITE_")}
    assert read_values.isdisjoint(write_values)


def test_the_console_decides_both_buckets_not_the_runner(monkeypatch):
    creds = {**FAKE_CREDENTIALS, "readBucket": "test-bucket", "writeBucket": "console-chosen-output"}
    monkeypatch.setenv("R2_INGEST_BUCKET", "runner-env-var-must-lose")
    env = _run_and_capture_pod_env(monkeypatch, creds)
    assert env["OUTPUT_BUCKET"] == "console-chosen-output"


def test_a_credential_for_a_different_input_bucket_is_refused_before_any_pod(monkeypatch):
    # The job row says its footage is in one bucket; the console issued a
    # read credential for another. Something upstream has drifted, and the
    # honest response is to stop, not to guess which is right.
    _no_real_network(monkeypatch, {**FAKE_CREDENTIALS, "readBucket": "some-other-bucket"})
    created = []
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: created.append(kw) or ("pod-1", "gpu"))
    with pytest.raises(RuntimeError, match="refusing rather than guessing"):
        job_runner.run_reel_job(JOB)
    assert created == [], "must not spend money on a pod whose credentials do not match its job"


def test_a_console_refusal_stops_the_job_before_a_pod_exists(monkeypatch):
    monkeypatch.setattr(job_runner, "_upload_pod_deps", lambda bucket: "https://example.invalid/x")

    def refuse(job_id):
        raise RuntimeError("console refused pod credentials for job job-1: job is done, not running")

    monkeypatch.setattr(job_runner, "fetch_pod_credentials", refuse)
    created = []
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: created.append(kw) or ("pod-1", "gpu"))
    with pytest.raises(RuntimeError, match="console refused"):
        job_runner.run_reel_job(JOB)
    assert created == [], "no fallback to the account keys, and no pod"


def test_scoped_r2_env_maps_every_field():
    env = job_runner.scoped_r2_env(FAKE_CREDENTIALS)
    assert sorted(env) == sorted([
        "R2_READ_ACCESS_KEY_ID", "R2_READ_SECRET_ACCESS_KEY", "R2_READ_SESSION_TOKEN",
        "R2_WRITE_ACCESS_KEY_ID", "R2_WRITE_SECRET_ACCESS_KEY", "R2_WRITE_SESSION_TOKEN",
    ])


def test_a_credential_outlives_the_deadline_that_ends_its_pod():
    # MIRRORS lib/podGrants.ts's POD_CREDENTIAL_TTL_SEC (4h) in the console
    # repo, which cannot be imported here. A credential that expires before
    # its pod does fails the job at the final upload -- the most expensive
    # place to find out. If this fires, check that file before changing it.
    CONSOLE_CREDENTIAL_TTL_SEC = 4 * 3600
    assert job_runner.JOB_DEADLINE_SEC < CONSOLE_CREDENTIAL_TTL_SEC


# --- fetch_pod_credentials against a REAL local server ----------------------
#
# Same reasoning test_pod_driver.py's _fake_console already gives: a mocked
# `requests.post` would agree with whatever this file assumed about the
# console. A real socket cannot.

import json  # noqa: E402
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, HTTPServer  # noqa: E402


def _serve(responses):
    """responses: list of (status, body_dict) answered in order, last repeats."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append({"path": self.path, "auth": self.headers.get("Authorization")})
            status, body = responses[min(len(seen) - 1, len(responses) - 1)]
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST  # the job-state read is a GET

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


@pytest.fixture
def console(monkeypatch):
    servers = []

    def start(responses):
        server, seen = _serve(responses)
        servers.append(server)
        monkeypatch.setattr(job_runner, "CONSOLE_URL", f"http://127.0.0.1:{server.server_address[1]}")
        return seen

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def _no_wait(_seconds):
    pass


def test_fetch_returns_what_the_console_issued_and_authenticates_as_the_runner(console):
    seen = console([(200, FAKE_CREDENTIALS)])
    assert job_runner.fetch_pod_credentials("job-1", _sleep=_no_wait) == FAKE_CREDENTIALS
    assert seen == [{"path": "/api/runner/jobs/job-1/credentials", "auth": f"Bearer {job_runner.RUNNER_TOKEN}"}]


def test_a_refusal_is_final_and_asked_only_once(console):
    # 4xx is the console saying no on purpose (job not running, segments not
    # where the key shape says). Asking again cannot change the answer, and
    # retrying would just hammer an endpoint that mints credentials.
    seen = console([(409, {"error": "job is done, not running"})])
    with pytest.raises(RuntimeError, match="job is done, not running"):
        job_runner.fetch_pod_credentials("job-1", _sleep=_no_wait)
    assert len(seen) == 1


def test_a_transient_console_error_is_retried_and_can_recover(console):
    seen = console([(503, {"error": "busy"}), (503, {"error": "busy"}), (200, FAKE_CREDENTIALS)])
    assert job_runner.fetch_pod_credentials("job-1", _sleep=_no_wait) == FAKE_CREDENTIALS
    assert len(seen) == 3


def test_a_console_that_stays_down_gives_up_after_a_bounded_number_of_tries(console):
    seen = console([(500, {"error": "boom"})])
    with pytest.raises(RuntimeError, match="after 3 attempts"):
        job_runner.fetch_pod_credentials("job-1", _sleep=_no_wait)
    assert len(seen) == job_runner.CREDENTIAL_ATTEMPTS


def test_an_unreachable_console_is_retried_then_reported(monkeypatch):
    monkeypatch.setattr(job_runner, "CONSOLE_URL", "http://127.0.0.1:1")  # nothing listens on port 1
    with pytest.raises(RuntimeError, match="could not reach the console"):
        job_runner.fetch_pod_credentials("job-1", _sleep=_no_wait)


def test_a_failure_message_never_carries_a_credential_from_the_response(console):
    # run_one() writes str(exception) into the job row, which the venue can
    # read. A credential in an exception message would be a credential in a
    # database column.
    poisoned = {"error": "nope", "read": {"secretAccessKey": "LEAKED-SECRET"}, "debug": "LEAKED-SECRET"}
    console([(409, poisoned)])
    with pytest.raises(RuntimeError) as excinfo:
        job_runner.fetch_pod_credentials("job-1", _sleep=_no_wait)
    assert "LEAKED-SECRET" not in str(excinfo.value)


def test_a_successful_fetch_prints_nothing(console, capsys):
    console([(200, FAKE_CREDENTIALS)])
    job_runner.fetch_pod_credentials("job-1", _sleep=_no_wait)
    out = capsys.readouterr()
    for secret in ("READ-SECRET", "WRITE-SECRET", "READ-TOKEN", "WRITE-TOKEN"):
        assert secret not in out.out + out.err


# --- Cancel has to work when the pod never starts (2026-09-20) -----------------
#
# The operator clicked Stop on a job whose pod's container never started
# (ADR-101). Cancel reaches a job only through the POD: every status PATCH the
# pod sends is answered with whether the operator asked to cancel. A pod that
# never starts sends nothing, so the click was recorded and then ignored --
# and the runner went on to create a SECOND pod for a job that was already
# cancelled. Both billed, about 12 minutes of GPU between them.
#
# Paired throughout. Every "must cancel" sits beside a "must not": a failed
# read must not cancel (PIC-157: a check that failed is not a check that
# came back negative), and a pod that HAS checked in must be left to cancel
# itself gracefully rather than being hard-killed from here.

BASELINE = "2026-01-01T00:00:00Z"


class _Pods:
    """Stand-in for RunPod, recording what the runner did to it."""

    def __init__(self, monkeypatch, stays_up=lambda pod_id: True):
        self.created, self.terminated, self.patched = [], [], []
        monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                            lambda **kw: self.created.append(kw["image"]) or (f"pod-{len(self.created)}", "gpu"))
        monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: stays_up(pod_id))
        monkeypatch.setattr(job_runner.runpod_pod, "terminate_pod", lambda pod_id: self.terminated.append(pod_id))
        monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: self.patched.append(fields) or False)
        _no_real_network(monkeypatch)
        monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
        monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 10)

    def run(self):
        job_runner.run_reel_job({**JOB, "updated_at": BASELINE})

    @property
    def cancelled_patches(self):
        return [f for f in self.patched if f.get("cancelled") is True]

    @property
    def error_patches(self):
        return [f for f in self.patched if "error" in f]


def test_a_cancel_while_the_pod_is_silent_stops_the_pod_and_ends_the_job_cancelled(monkeypatch):
    pods = _Pods(monkeypatch)
    # Both slow paths are made FATAL here, so only a prompt cancel can pass.
    # An earlier version left a 5s first-check-in timeout in place and passed
    # with the wait-loop cancel branch deleted: the timeout fired, terminated
    # the pod, and the RETRY's pre-create check caught the cancel -- the right
    # outcome, five seconds late, by a different path. (Found by deleting the
    # branch and watching this stay green.) With the timeout out of reach and
    # a short job deadline, the only way to a clean `cancelled` is the branch.
    monkeypatch.setattr(job_runner, "FIRST_CHECKIN_TIMEOUT_SEC", 1000)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 1.0)
    # The operator's Stop lands AFTER the pod exists -- the whole point. (A
    # flag that is true from the start is a different case, covered below:
    # the pre-create check stops it before any pod is made.)
    monkeypatch.setattr(job_runner, "get_job_state",
                        lambda job_id: _state(BASELINE, cancel_requested=bool(pods.created)))
    pods.run()
    assert pods.terminated == ["pod-1"], "the billing pod must be stopped"
    assert len(pods.created) == 1
    assert len(pods.cancelled_patches) == 1
    # Cancelled, not errored: "the pod disappeared" is what the runner would
    # otherwise report, and it tells the operator something that isn't true.
    assert pods.error_patches == []


def test_a_cancel_that_arrives_while_the_first_pod_is_stuck_does_not_create_a_second(monkeypatch):
    # The reported incident, exactly. The first pod is stuck and the fast-fail
    # terminates it; the operator's Stop lands while that is happening. The
    # retry used to create a second pod for the cancelled job.
    pods = _Pods(monkeypatch)
    monkeypatch.setattr(job_runner, "FIRST_CHECKIN_TIMEOUT_SEC", 0.03)
    cancelled_now = {"v": False}
    monkeypatch.setattr(job_runner.runpod_pod, "terminate_pod",
                        lambda pod_id: (pods.terminated.append(pod_id), cancelled_now.update(v=True)))
    monkeypatch.setattr(job_runner, "get_job_state",
                        lambda job_id: _state(BASELINE, cancel_requested=cancelled_now["v"]))
    pods.run()
    assert len(pods.created) == 1, f"a second pod was created for a cancelled job: {pods.created}"
    assert len(pods.cancelled_patches) == 1
    assert pods.error_patches == [], "a cancelled job must not be reported as a stuck-container failure"


def test_a_cancel_before_any_pod_exists_creates_none(monkeypatch):
    # Between the claim and the pod there is a deps upload and a credentials
    # fetch -- long enough for a Stop to land.
    pods = _Pods(monkeypatch)
    monkeypatch.setattr(job_runner, "get_job_state", lambda job_id: _state(BASELINE, cancel_requested=True))
    pods.run()
    assert pods.created == []
    assert pods.terminated == [], "there is nothing to terminate"
    assert len(pods.cancelled_patches) == 1


def test_a_stuck_pod_that_was_not_cancelled_is_still_retried(monkeypatch):
    # The paired half. A cancel check that fired on the timeout itself would
    # pass every test above and quietly turn the ADR-101 retry into a cancel.
    pods = _Pods(monkeypatch, stays_up=lambda pod_id: pod_id == "pod-1")
    monkeypatch.setattr(job_runner, "FIRST_CHECKIN_TIMEOUT_SEC", 0.03)
    monkeypatch.setattr(job_runner, "get_job_state", lambda job_id: _state(BASELINE if len(pods.created) < 2 else "later"))
    pods.run()
    assert len(pods.created) == 2, "an un-cancelled stuck pod must still get its one retry"
    assert pods.cancelled_patches == []


def test_an_unreadable_job_is_never_treated_as_cancelled(monkeypatch):
    # PIC-157's rule: a check that FAILED is not a check that came back
    # negative -- and equally not one that came back positive. A console
    # blip must not kill a healthy pod.
    pods = _Pods(monkeypatch)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 0.15)  # ends via the deadline, never via a cancel
    monkeypatch.setattr(job_runner, "get_job_state", lambda job_id: None)
    pods.run()
    assert pods.cancelled_patches == [], "an unreadable job row must not be read as a cancel"
    assert len(pods.created) == 1


def test_a_cancel_after_the_pod_has_checked_in_is_left_to_the_pod(monkeypatch):
    # Once updated_at has moved the pod is up and talking to the console; it
    # sees the cancel on its own status PATCHes and stops gracefully,
    # reporting its own final result. Hard-killing it from here would
    # pre-empt that -- so this loop deliberately does not.
    polls = {"n": 0}

    def pod_up_for_a_few_polls(pod_id):
        polls["n"] += 1
        return polls["n"] < 4

    pods = _Pods(monkeypatch, stays_up=pod_up_for_a_few_polls)
    # Not cancelled while the pod is being created; once it exists it has
    # checked in (updated_at moved) AND the operator has clicked Stop.
    monkeypatch.setattr(job_runner, "get_job_state",
                        lambda job_id: _state("2026-01-01T00:05:00Z", cancel_requested=True) if pods.created
                        else _state(BASELINE))
    pods.run()
    assert pods.terminated == [], "a pod that has checked in must not be hard-killed by the runner's cancel check"
    assert pods.cancelled_patches == []


# --- get_job_state against a real local server --------------------------------

def test_get_job_state_returns_both_fields(console):
    console([(200, {"stage": "queued", "status": "running", "updated_at": BASELINE, "cancel_requested": True})])
    assert job_runner.get_job_state("job-1") == {"updated_at": BASELINE, "cancel_requested": True}


def test_a_console_that_predates_the_field_reads_as_not_cancelled(console):
    # Deploy order: the console change goes out first, but a runner talking
    # to an older console must still work, and fail in the safe direction.
    console([(200, {"stage": "queued", "status": "running", "updated_at": BASELINE})])
    assert job_runner.get_job_state("job-1") == {"updated_at": BASELINE, "cancel_requested": False}


def test_a_failed_read_is_none_not_a_guess(console, monkeypatch):
    console([(500, {"error": "boom"})])
    assert job_runner.get_job_state("job-1") is None
    console([(404, {"error": "job not found"})])
    assert job_runner.get_job_state("job-1") is None
    monkeypatch.setattr(job_runner, "CONSOLE_URL", "http://127.0.0.1:1")
    assert job_runner.get_job_state("job-1") is None


# --- GPU capacity exhaustion is retried with backoff, not failed outright ---
#
# Before this, every fallback GPU type coming back unavailable (a real,
# confirmed-recoverable RunPod state -- runpod_pod.py's own history,
# 2026-08-26) failed the job immediately with RunPod's raw API error text
# as the message. Paired throughout: a job that eventually gets a pod must
# never show an error on its way there, same rule as the stuck-container
# retry above.

def _capacity_pods(monkeypatch, fail_times):
    """create_selfdriving_pod raises RuntimeError `fail_times` times, then
    succeeds. fail_times=None means it never succeeds."""
    calls = {"n": 0}

    def fake(**kw):
        calls["n"] += 1
        if fail_times is None or calls["n"] <= fail_times:
            raise RuntimeError("could not create self-driving pod on any GPU type: no instances currently available")
        return ("pod-1", "gpu")

    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod", fake)
    return calls


def test_gpu_capacity_exhaustion_is_retried_and_can_recover(monkeypatch):
    _no_real_network(monkeypatch)
    monkeypatch.setattr(job_runner, "GPU_CAPACITY_RETRY_DELAYS_SEC", [0.01, 0.01, 0.01])
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 10)
    calls = _capacity_pods(monkeypatch, fail_times=2)  # fails twice, then a pod exists
    # pod_exists -> False on the very next poll is the ordinary "it finished
    # and reported its own status" shape (see test_happy_path_... above) --
    # this test is only about whether create_selfdriving_pod got its retry,
    # not about what happens after a pod exists.
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: False)
    monkeypatch.setattr(job_runner, "get_job_state", lambda job_id: None)
    patched = []
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: patched.append(fields) or False)

    job_runner.run_reel_job(JOB)  # must not raise

    assert calls["n"] == 3, "should have retried past both failures and gotten a pod on the third"
    assert not any("no GPU capacity available" in (f.get("error") or "") for f in patched), \
        f"a job that eventually got a pod must never report the permanent capacity-exhaustion failure: {patched}"
    assert any("waiting for GPU capacity" in (f.get("message") or "") for f in patched)


def test_gpu_capacity_exhaustion_that_never_recovers_is_reported_through_run_one(monkeypatch, tmp_path):
    # run_reel_job() itself raises (checked directly below) -- this checks
    # the full path a real failure actually takes: run_one()'s top-level
    # catch is what turns that into the job's own `error` field, the same
    # place an operator or venue would actually read it from.
    _no_real_network(monkeypatch)
    monkeypatch.setattr(job_runner, "GPU_CAPACITY_RETRY_DELAYS_SEC", [0.01, 0.01])
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 10)
    monkeypatch.setattr(job_runner, "WORK_DIR", str(tmp_path))
    _capacity_pods(monkeypatch, fail_times=None)
    monkeypatch.setattr(job_runner, "get_job_state", lambda job_id: None)
    # run_one()'s own `finally` calls _cleanup(), which reads the job's
    # status back from the console -- stubbed so this stays offline, same
    # reasoning as _no_real_network above.
    monkeypatch.setattr(job_runner, "get_job_status", lambda job_id: "error")
    patched = []
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: patched.append(fields) or False)

    job_runner.run_one(dict(JOB))  # must not raise -- run_one's own job

    error_patches = [f["error"] for f in patched if "error" in f]
    assert len(error_patches) == 1
    assert "no GPU capacity available" in error_patches[0]
    assert "RunPod" in error_patches[0], "the message should say this is RunPod capacity, not this project's bug"


def test_gpu_capacity_exhaustion_message_is_clear_and_actionable(monkeypatch):
    _no_real_network(monkeypatch)
    monkeypatch.setattr(job_runner, "GPU_CAPACITY_RETRY_DELAYS_SEC", [0.01, 0.01])
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 10)
    _capacity_pods(monkeypatch, fail_times=None)
    monkeypatch.setattr(job_runner, "get_job_state", lambda job_id: None)
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: False)

    with pytest.raises(RuntimeError, match="no GPU capacity available"):
        job_runner.run_reel_job(JOB)


def test_gpu_capacity_wait_never_retries_past_the_jobs_own_deadline(monkeypatch):
    # A retry schedule that ignores the job's overall deadline could keep a
    # pod-less job "waiting" indefinitely past JOB_DEADLINE_SEC -- it must
    # give up at least as promptly as any other failure mode does.
    _no_real_network(monkeypatch)
    monkeypatch.setattr(job_runner, "GPU_CAPACITY_RETRY_DELAYS_SEC", [1000, 1000, 1000])
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 0.05)  # far shorter than any retry delay
    calls = _capacity_pods(monkeypatch, fail_times=None)
    monkeypatch.setattr(job_runner, "get_job_state", lambda job_id: None)
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: False)

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="no GPU capacity available"):
        job_runner.run_reel_job(JOB)
    elapsed = time.monotonic() - started

    assert elapsed < 5, f"must not wait out a 1000s retry delay past a 0.05s deadline: {elapsed}s"
    assert calls["n"] == 1, "must not even attempt a second retry once the deadline is already passed"


def test_a_cancel_during_the_gpu_capacity_wait_ends_the_job_cancelled_not_errored(monkeypatch):
    _no_real_network(monkeypatch)
    monkeypatch.setattr(job_runner, "GPU_CAPACITY_RETRY_DELAYS_SEC", [0.01, 0.01, 0.01])
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    monkeypatch.setattr(job_runner, "JOB_DEADLINE_SEC", 10)
    calls = _capacity_pods(monkeypatch, fail_times=None)  # never succeeds on its own
    # Cancelled from the second read onward -- i.e. partway through the wait,
    # not before the very first attempt (that path is already covered by the
    # existing "cancel before any pod exists" test).
    reads = {"n": 0}

    def state(job_id):
        reads["n"] += 1
        return _state(BASELINE, cancel_requested=reads["n"] >= 2)

    monkeypatch.setattr(job_runner, "get_job_state", state)
    patched = []
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: patched.append(fields) or False)

    job_runner.run_reel_job({**JOB, "updated_at": BASELINE})  # must not raise

    assert calls["n"] <= 2, "must stop retrying once the operator has cancelled"
    assert any(f.get("cancelled") is True for f in patched)
    assert not any("error" in f for f in patched), "a cancel must not also be reported as an error"


def test_a_pod_created_on_the_first_try_reports_no_waiting_message(monkeypatch):
    # The paired half of the retry tests above: the ordinary, overwhelming
    # majority case must not show a "waiting for GPU capacity" message it
    # never actually needed.
    _no_real_network(monkeypatch)
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    _capacity_pods(monkeypatch, fail_times=0)
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: False)
    monkeypatch.setattr(job_runner, "get_job_state", lambda job_id: None)
    patched = []
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: patched.append(fields) or False)

    job_runner.run_reel_job(JOB)

    assert not any("waiting for GPU capacity" in (f.get("message") or "") for f in patched)


# --- job_runner.py can run more than one reel job at once (2026-09-22) -----
#
# The console's claim_next_job already used FOR UPDATE SKIP LOCKED so
# concurrent claims can't collide; this runner was the only side still
# serial. has_capacity() is the one piece of that worth a direct test --
# main()'s own loop (like its claim/idle-backoff loop before it) has no
# dedicated test, same precedent as idle_sleep_sec vs. main() itself.

def test_capacity_is_available_below_the_cap():
    assert job_runner.has_capacity(job_runner.MAX_CONCURRENT_JOBS - 1) is True


def test_capacity_is_exhausted_at_the_cap():
    assert job_runner.has_capacity(job_runner.MAX_CONCURRENT_JOBS) is False


def test_capacity_is_exhausted_past_the_cap():
    # Belt and suspenders: a transient overshoot (e.g. a race in main()'s
    # own bookkeeping) must still read as "no capacity", not wrap around.
    assert job_runner.has_capacity(job_runner.MAX_CONCURRENT_JOBS + 1) is False


def _capture_pod_env(monkeypatch, job):
    _no_real_network(monkeypatch, FAKE_CREDENTIALS)
    monkeypatch.setattr(job_runner, "POD_POLL_SEC", 0.01)
    captured = {}
    monkeypatch.setattr(job_runner.runpod_pod, "create_selfdriving_pod",
                        lambda **kw: captured.update(kw) or ("pod-1", "gpu"))
    monkeypatch.setattr(job_runner.runpod_pod, "pod_exists", lambda pod_id: False)
    monkeypatch.setattr(job_runner, "patch_job", lambda job_id, **fields: None)
    job_runner.run_reel_job(job)
    return captured["env"]


def test_the_pod_gets_the_logo_the_console_chose(monkeypatch):
    env = _capture_pod_env(monkeypatch, {**JOB, "logo_url": "https://cdn.picvisionai.com/b/brand-logos/x.png"})
    assert env["LOGO_URL"] == "https://cdn.picvisionai.com/b/brand-logos/x.png"


def test_no_logo_from_the_console_means_no_logo_on_the_pod(monkeypatch):
    # null (toggle off / no upload / SVG) and an older console that never
    # sends the field at all must both reach the pod as "no logo".
    assert _capture_pod_env(monkeypatch, {**JOB, "logo_url": None})["LOGO_URL"] == ""
    assert _capture_pod_env(monkeypatch, dict(JOB))["LOGO_URL"] == ""


# --- RUNNER_KINDS (ADR-125): the workstation keeps only calibrations at cutover ---


def _claim_body(monkeypatch, kinds):
    sent = {}

    class R:
        status_code = 204

    monkeypatch.setattr(job_runner, "RUNNER_KINDS", kinds)
    monkeypatch.setattr(job_runner.requests, "post", lambda url, json=None, **kw: sent.update(json) or R())
    job_runner.claim_job()
    return sent


def test_an_unrestricted_runner_claims_exactly_as_before(monkeypatch):
    # The paired half: without RUNNER_KINDS nothing changes, so an existing
    # runner can't silently stop picking up a kind of job.
    assert "kinds" not in _claim_body(monkeypatch, None)


def test_a_calibration_only_runner_says_so_when_claiming(monkeypatch):
    assert _claim_body(monkeypatch, ["calibration"])["kinds"] == ["calibration"]
