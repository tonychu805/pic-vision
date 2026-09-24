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
os.environ.setdefault("OUTPUT_BUCKET", "test-output-bucket")
os.environ.setdefault("BRAND_ID", "test-brand-id")

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


# --- _run_inference_streaming: the reader-thread/queue path added because a
# plain `for line in proc.stdout` would block forever with no heartbeat if
# pod_infer.py ever went quiet -- exercised against a REAL subprocess (a
# tiny Python script standing in for pod_infer.py), not a mocked Popen,
# since the whole point is proving the queue/timeout mechanics actually
# work under a real process, not that a mock does what the mock says.

_FAKE_INFER_SCRIPT = """
import time
print("Video: 900 frames @ 30.0 fps = 30.0s", flush=True)
for i in range(1, 4):
    time.sleep(0.05)
    print(f"  {i * 300}/900  60 fps  ETA {(3 - i) * 0.1:.1f} min", flush=True)
"""

_HANGING_INFER_SCRIPT = """
import time
print("Video: 900 frames @ 30.0 fps = 30.0s", flush=True)
time.sleep(30)  # simulates a stall with zero output -- must not block the reader
"""


def test_inference_streaming_reports_real_progress_from_a_real_subprocess(console_url, monkeypatch):
    monkeypatch.setattr(pod_driver, "PROGRESS_PATCH_INTERVAL_SEC", 0)  # patch on every line for this test
    seen = console_url([(200, '{"cancelRequested": false}')] * 10)
    pod_driver._run_inference_streaming(["python3", "-c", _FAKE_INFER_SCRIPT])
    progress_bodies = [s["body"] for s in seen if b'"progress"' in s["body"]]
    assert len(progress_bodies) >= 1, "at least one real progress line should have been parsed and sent"
    assert b'"current": 300' in progress_bodies[0] or b'"current":300' in progress_bodies[0]


def test_inference_streaming_sends_a_heartbeat_even_with_no_output_yet(console_url, monkeypatch):
    # The hanging script prints one line then goes silent for 30s -- if the
    # reader thread/queue fix regressed back to a plain blocking readline,
    # this test would itself hang instead of completing quickly.
    monkeypatch.setattr(pod_driver, "PROGRESS_PATCH_INTERVAL_SEC", 0.2)
    monkeypatch.setattr(pod_driver, "INFERENCE_TIMEOUT_SEC", 0.6)
    console_url([(200, '{"cancelRequested": false}')] * 10)
    with pytest.raises(TimeoutError):
        pod_driver._run_inference_streaming(["python3", "-c", _HANGING_INFER_SCRIPT])


def test_inference_streaming_kills_the_process_on_a_real_cancel(console_url, monkeypatch):
    monkeypatch.setattr(pod_driver, "PROGRESS_PATCH_INTERVAL_SEC", 0)
    # First heartbeat says continue, second says stop -- proves a
    # mid-inference cancel actually reaches and kills the subprocess
    # rather than only being checked between stages.
    console_url([(200, '{"cancelRequested": false}'), (200, '{"cancelRequested": true}')] + [(200, '{"cancelRequested": false}')] * 8)
    with pytest.raises(pod_driver.Cancelled):
        pod_driver._run_inference_streaming(["python3", "-c", _FAKE_INFER_SCRIPT])


# --- The final report is the one that can't be dropped -------------------
#
# patch_job() swallows every failure by design, which is right for progress
# and wrong for the report that ends a job: by then the reels are already in
# R2 and the console is the only thing that will ever know. A single 500 at
# that moment left the pod self-terminating, job_runner.py marking the job
# errored ("pod disappeared without reporting"), and its cleanup deleting
# the venue's uploaded segments -- asking for a re-upload and a second GPU
# job for output that was already complete.


def test_final_report_retries_until_the_console_answers(console_url, monkeypatch):
    monkeypatch.setattr(pod_driver, "FINAL_REPORT_BACKOFF_SEC", 0)
    seen = console_url([(500, "{}"), (502, "{}"), (200, "{}")])
    assert pod_driver.report_final_job_status(done=True, stage="done") is True
    assert len(seen) == 3, "should have kept trying until one landed"


def test_final_report_gives_up_rather_than_holding_a_billed_pod_forever(console_url, monkeypatch):
    monkeypatch.setattr(pod_driver, "FINAL_REPORT_BACKOFF_SEC", 0)
    monkeypatch.setattr(pod_driver, "FINAL_REPORT_ATTEMPTS", 3)
    seen = console_url([(500, "{}")] * 3)
    assert pod_driver.report_final_job_status(error="boom") is False
    assert len(seen) == 3


def test_final_report_treats_409_as_delivered(console_url, monkeypatch):
    # 409 means the row already moved on (cancelled, or reclaimed) -- an
    # answer, not a delivery failure. Retrying it would be pointless and
    # would delay self-termination on a billed pod.
    monkeypatch.setattr(pod_driver, "FINAL_REPORT_BACKOFF_SEC", 0)
    seen = console_url([(409, "{}")])
    assert pod_driver.report_final_job_status(done=True) is True
    assert len(seen) == 1


def test_progress_reports_are_still_best_effort(console_url):
    # The other half of the contract: a failed *progress* report must not
    # retry or raise, or a console blip would stall a running GPU job.
    seen = console_url([(500, "{}")])
    assert pod_driver.patch_job(stage="inference") is False
    assert len(seen) == 1


# --- PIC-138: the pod holds two scoped credentials and no account key --------
#
# pod_driver.py used to build one S3 client from the account's own R2 keys and
# use it for everything: read every venue's footage, write and DELETE anywhere.
# It now builds two, from credentials the console minted for this one job.
import re  # noqa: E402
import inspect  # noqa: E402


def _scoped_env(monkeypatch):
    for direction in ("READ", "WRITE"):
        monkeypatch.setenv(f"R2_{direction}_ACCESS_KEY_ID", f"{direction}-KEY")
        monkeypatch.setenv(f"R2_{direction}_SECRET_ACCESS_KEY", f"{direction}-SECRET")
        monkeypatch.setenv(f"R2_{direction}_SESSION_TOKEN", f"{direction}-TOKEN")
    monkeypatch.setenv("CLOUDFLARE_R2_ACCOUNT_ID", "acct")


def _creds_of(client):
    # botocore keeps these on the request signer; there is no public getter.
    c = client._request_signer._credentials
    return c.access_key, c.secret_key, c.token


def test_the_pod_builds_a_read_client_and_a_write_client_on_different_credentials(monkeypatch):
    _scoped_env(monkeypatch)
    s3_in, s3_out = pod_driver._r2_clients()
    assert _creds_of(s3_in) == ("READ-KEY", "READ-SECRET", "READ-TOKEN")
    assert _creds_of(s3_out) == ("WRITE-KEY", "WRITE-SECRET", "WRITE-TOKEN")


def test_both_clients_carry_a_session_token(monkeypatch):
    # The whole mechanism: without the token R2 sees a plain access key and
    # secret it has never heard of, and 403s -- or worse, if the two ever
    # happened to be the account's own, quietly works at full privilege.
    _scoped_env(monkeypatch)
    for client in pod_driver._r2_clients():
        assert _creds_of(client)[2], "a scoped credential without its session token is not scoped"


def test_missing_scoped_credentials_fail_loudly_and_never_fall_back(monkeypatch):
    # The account's own keys are deliberately present here. If the pod could
    # reach for them when the scoped ones are missing, a runner that failed
    # to fetch credentials would still produce a working pipeline -- and the
    # security change would be undone with nothing ever failing.
    monkeypatch.setenv("CLOUDFLARE_R2_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CLOUDFLARE_R2_ACCESS_KEY_ID", "ACCOUNT-KEY")
    monkeypatch.setenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "ACCOUNT-SECRET")
    for name in ("R2_READ_ACCESS_KEY_ID", "R2_READ_SECRET_ACCESS_KEY", "R2_READ_SESSION_TOKEN",
                 "R2_WRITE_ACCESS_KEY_ID", "R2_WRITE_SECRET_ACCESS_KEY", "R2_WRITE_SESSION_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(KeyError, match="R2_READ_ACCESS_KEY_ID"):
        pod_driver._r2_clients()


def test_no_code_on_the_pod_reads_the_account_r2_keys():
    # A tripwire on the source, because the failure it guards is silent: a
    # later edit that reads CLOUDFLARE_R2_SECRET_ACCESS_KEY again would work
    # perfectly on a pod that still happened to receive it, and nothing
    # would fail until the day that stopped being true.
    code = "\n".join(
        line for line in inspect.getsource(pod_driver).splitlines()
        if not line.lstrip().startswith("#")
    )
    # Docstring prose may mention the names; code may not READ them.
    reads = re.findall(r"environ(?:\.get)?\s*[\[(]\s*[\"']CLOUDFLARE_R2_(?:ACCESS_KEY_ID|SECRET_ACCESS_KEY)", code)
    assert reads == [], f"pod_driver.py reads the account's R2 keys again: {reads}"


def test_the_shared_files_the_pod_reads_are_covered_by_its_read_credential():
    # MIRRORS lib/podGrants.ts SHARED_READ_PREFIXES in the console repo,
    # which cannot be imported here. The read credential covers this job's
    # segments plus these two folders and nothing else, so a pod dependency
    # that moves to a new prefix is not a test failure anywhere -- it is a
    # job that 403s minutes into a billed GPU run. This is the tripwire.
    granted = ("pipeline/", "weights/")
    for name in ("FFMPEG_R2_KEY", "FFPROBE_R2_KEY", "WEIGHTS_R2_KEY"):
        key = getattr(pod_driver, name)
        assert key.startswith(granted), f"{name}={key!r} is outside the read credential's prefixes {granted}"


def test_every_reel_the_pod_uploads_lands_in_its_venues_reel_folder():
    # The write credential covers <brand>/reels/ and nothing else. Every
    # upload_file call must use a key built under that prefix, or the final
    # upload of a real job 403s -- the most expensive place to find out.
    source = inspect.getsource(pod_driver.run)
    # upload_file(os.path.join(...), OUTPUT_BUCKET, <key var>) -- the join()
    # has its own parentheses, so a plain [^)]* would stop inside it.
    uploads = re.findall(r"s3_out\.upload_file\(os\.path\.join\([^)]*\),\s*OUTPUT_BUCKET,\s*(\w+)\)", source)
    assert len(uploads) == 3, f"expected the full, top-rally and burst uploads, found {uploads}"
    for var in uploads:
        assert re.search(rf'{var}\s*=\s*f"\{{BRAND_ID\}}/reels/', source), f"{var} is not built under <brand>/reels/"


def test_reads_use_the_read_client_and_writes_use_the_write_client():
    # Crossing them is a real bug: the read credential has no PutObject and
    # the write credential has no GetObject, so either mistake 403s a job.
    source = inspect.getsource(pod_driver.run)
    assert not re.search(r"s3_out\.download_file", source)
    assert not re.search(r"s3_in\.upload_file", source)
    assert len(re.findall(r"s3_in\.download_file", source)) == 3
    assert len(re.findall(r"s3_out\.upload_file", source)) == 3


# --- NVENC -> libx264 fallback (2026-09-21) ---------------------------------
# Tournament 2's pod landed on an RTX 4090 and the convert step died with the
# stderr below. Paired: the fallback must fire on that, and must NOT fire when
# NVENC works or when the failure is the input's fault (the same command line
# contains "h264_nvenc" either way, so matching on the message would be wrong).

REAL_NVENC_STDERR = (
    "[h264_nvenc @ 0x623db706e500] OpenEncodeSessionEx failed: unsupported device (2): (no details)\n"
    "[h264_nvenc @ 0x623db706e500] No capable devices found\n"
    "Nothing was written into output file, because at least one of its streams received no packets."
)


def _record_ffmpeg(monkeypatch, outcomes):
    calls = []

    def fake(args):
        calls.append(args)
        outcome = outcomes.pop(0)
        if outcome is not None:
            raise pod_driver.FfmpegError(" ".join(args) + "\n" + outcome, outcome)

    monkeypatch.setattr(pod_driver, "_run_ffmpeg", fake)
    return calls


def _codec(args):
    return args[args.index("-c:v") + 1]


def test_encode_falls_back_to_libx264_when_nvenc_is_unavailable(monkeypatch):
    calls = _record_ffmpeg(monkeypatch, [REAL_NVENC_STDERR, None])
    pod_driver._encode_h264(["-i", "in.mkv"], ["-an", "-vsync", "cfr", "-r", "30", "out.mp4"])
    assert [_codec(c) for c in calls] == ["h264_nvenc", "libx264"]
    # same input and same output on the retry, so the rest of the pipeline sees no difference
    for c in calls:
        assert c[c.index("-i") + 1] == "in.mkv" and c[-1] == "out.mp4"
        assert c[-6:-1] == ["-an", "-vsync", "cfr", "-r", "30"]
    assert "-pix_fmt" in calls[1] and "yuv420p" in calls[1]


def test_encode_does_not_retry_when_nvenc_works(monkeypatch):
    calls = _record_ffmpeg(monkeypatch, [None])
    pod_driver._encode_h264(["-i", "in.mkv"], ["-an", "out.mp4"])
    assert [_codec(c) for c in calls] == ["h264_nvenc"]


def test_encode_does_not_retry_a_failure_that_is_not_about_nvenc(monkeypatch):
    calls = _record_ffmpeg(monkeypatch, ["in.mkv: Invalid data found when processing input"])
    with pytest.raises(pod_driver.FfmpegError, match="Invalid data"):
        pod_driver._encode_h264(["-i", "in.mkv"], ["-an", "out.mp4"])
    assert [_codec(c) for c in calls] == ["h264_nvenc"]


def test_encode_reports_the_libx264_error_if_the_fallback_also_fails(monkeypatch):
    calls = _record_ffmpeg(monkeypatch, [REAL_NVENC_STDERR, "libx264 exploded"])
    with pytest.raises(pod_driver.FfmpegError, match="libx264 exploded"):
        pod_driver._encode_h264(["-i", "in.mkv"], ["-an", "out.mp4"])
    assert len(calls) == 2


def test_a_stretch_with_no_rallies_finishes_done_with_no_reels(console_url, monkeypatch):
    # Not an error: the job is done, the console files no reels, and the
    # session's other parts carry the share page (2026-09-23 rehearsal).
    import json
    monkeypatch.setenv("SHARE_ID", "11111111-1111-4111-8111-111111111111")
    seen = console_url([(200, "{}")])
    assert pod_driver.finish_with_no_rallies() is True
    body = json.loads(seen[0]["body"])
    assert body["done"] is True and "error" not in body
    assert body["message"] == "no rallies found"
    assert body["result"]["reels"] == []
    assert body["result"]["share_id"] == "11111111-1111-4111-8111-111111111111"


# --- Skipping the convert step (ADR-130) ---

H264 = {"codec_name": "h264", "pix_fmt": "yuv420p", "height": 1080}


def _mkv_times(n, start=0.0):
    # A desktop .mkv stores millisecond timestamps: 30fps lands as 33/34 ms steps.
    return [start + round(i / 30, 3) for i in range(n)]


def test_convert_is_skipped_for_a_clean_30fps_h264_recording():
    ok, why = pod_driver.cfr_verdict(H264, _mkv_times(18000))
    assert ok, why


def test_convert_is_kept_for_anything_the_encode_would_change():
    t = _mkv_times(18000)
    cases = {
        "hevc": ({**H264, "codec_name": "hevc"}, t),
        "4:2:2 pixels": ({**H264, "pix_fmt": "yuv422p"}, t),
        "above 1080p": ({**H264, "height": 1620}, t),
        "15fps camera": (H264, [i / 15 for i in range(9000)]),
        "a dropped frame": (H264, t[:500] + t[501:]),
        "a duplicated timestamp": (H264, t[:500] + [t[500]] + t[500:]),
        "starts late": (H264, _mkv_times(18000, start=5.0)),
        "unreadable": (None, []),
    }
    for name, (stream, pts) in cases.items():
        ok, why = pod_driver.cfr_verdict(stream, pts)
        assert not ok, f"{name} should convert, got skip ({why})"


def test_convert_is_kept_when_the_probe_fails(tmp_path):
    ok, why = pod_driver.convert_skippable(str(tmp_path / "missing.mkv"))
    assert not ok and "could not probe" in why


# --- Keeping the machine for the next part (ADR-130) ---

class _Clock:
    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_a_waiting_pod_takes_the_next_part_when_it_arrives():
    c = _Clock()
    answers = iter([{}, {}, {"env": {"JOB_ID": "job-2"}}])
    env = pod_driver.wait_for_next_part("s1", "pod-1", idle_sec=720, accept_until=c.t + 3600,
                                        now=c.now, sleep=c.sleep, ask=lambda s, p: next(answers))
    assert env == {"JOB_ID": "job-2"}
    assert c.t == 1000.0 + 2 * pod_driver.WARM_POLL_SEC


def test_a_waiting_pod_gives_up_after_the_idle_limit():
    c = _Clock()
    asks = []
    env = pod_driver.wait_for_next_part("s1", "pod-1", idle_sec=60, accept_until=c.t + 3600,
                                        now=c.now, sleep=c.sleep, ask=lambda s, p: asks.append(1) or {})
    assert env is None
    assert c.t >= 1060 and len(asks) == 60 // pod_driver.WARM_POLL_SEC


def test_a_pod_near_the_job_deadline_takes_no_more_parts():
    c = _Clock()
    env = pod_driver.wait_for_next_part("s1", "pod-1", idle_sec=720, accept_until=c.t - 1,
                                        now=c.now, sleep=c.sleep, ask=lambda s, p: {"env": {"JOB_ID": "x"}})
    assert env is None


def test_a_second_waiting_pod_is_told_to_stop():
    c = _Clock()
    env = pod_driver.wait_for_next_part("s1", "pod-2", idle_sec=720, accept_until=c.t + 3600,
                                        now=c.now, sleep=c.sleep, ask=lambda s, p: {"stop": True})
    assert env is None and c.t == 1000.0


def _next_part_env(job_id="job-2"):
    return {
        "JOB_ID": job_id, "BRAND_ID": "brand-1", "LOGO_URL": "", "BUCKET": "in-bucket", "OUTPUT_BUCKET": "out-bucket",
        "SEGMENT_KEYS_JSON": '["a/seg.mkv"]', "CALIB_JSON": "{}", "TARGET_SEC": "180", "SESSION_ID": "s",
        "REEL_ID": "r", "BURST_REEL_ID": "b", "SHARE_ID": "sh", "RECORDING_SESSION_ID": "rs",
        "R2_READ_ACCESS_KEY_ID": "k1", "R2_READ_SECRET_ACCESS_KEY": "s1", "R2_READ_SESSION_TOKEN": "t1",
        "R2_WRITE_ACCESS_KEY_ID": "k2", "R2_WRITE_SECRET_ACCESS_KEY": "s2", "R2_WRITE_SESSION_TOKEN": "t2",
    }


def test_taking_the_next_part_reports_to_that_part_and_uses_its_storage_pass(console_url, monkeypatch):
    for k in pod_driver.JOB_ENV_KEYS:
        monkeypatch.setenv(k, "old")
    for g in ("JOB_ID", "BUCKET", "OUTPUT_BUCKET", "BRAND_ID", "LOGO_URL"):
        monkeypatch.setattr(pod_driver, g, getattr(pod_driver, g))
    pod_driver.apply_job_env(_next_part_env("job-2"))
    assert (pod_driver.JOB_ID, pod_driver.BUCKET, pod_driver.OUTPUT_BUCKET) == ("job-2", "in-bucket", "out-bucket")
    assert os.environ["R2_READ_ACCESS_KEY_ID"] == "k1" and os.environ["LOGO_URL"] == ""
    seen = console_url([(200, "{}")])
    pod_driver.patch_job(stage="setup")
    assert seen[0]["path"] == "/api/runner/jobs/job-2"


def test_a_next_part_without_its_storage_pass_is_refused(monkeypatch):
    for g in ("JOB_ID", "BUCKET", "OUTPUT_BUCKET", "BRAND_ID", "LOGO_URL"):
        monkeypatch.setattr(pod_driver, g, getattr(pod_driver, g))
    env = _next_part_env()
    del env["R2_READ_ACCESS_KEY_ID"]
    with pytest.raises(ValueError, match="R2_READ_ACCESS_KEY_ID"):
        pod_driver.apply_job_env(env)
