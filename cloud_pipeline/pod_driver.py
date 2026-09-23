"""ADR-093, decision items 1+2: the pod runs itself.

Everything `cloud_pipeline/run_cloud_job.py` used to do by SSH'ing into a
pod step-by-step from the operator's own workstation (and, before that
script even started, the CFR-convert + proxy encode `run_cloud_job.py` did
*locally* with the operator's own NVIDIA card) happens here instead, as one
process running ON the rented pod. Run via the base image's own
`/start.sh` -> `/post_start.sh` hook (Dockerfile.selfdriving deliberately
does NOT make this the container's CMD -- see that file for why: doing so
made every real RunPod pod hang at container start, differential-tested
against the unmodified base image). Nothing SSHes in, and the operator's
workstation never touches a video byte or a GPU cycle for a job that runs
this way.

Reads its whole job from environment variables (set at pod-creation time,
`runpod_pod.create_selfdriving_pod`) rather than a command line, since
that's the one interface RunPod's own pod-creation API gives a caller:

    JOB_ID              -- the console's job row id
    BRAND_ID             the venue's brand id -- leads every key this pod
                           writes to OUTPUT_BUCKET (PIC-153, 2026-09-18)
    BUCKET               R2 bucket holding THIS job's raw segments --
                           private since PIC-153, never the one the public
                           CDN domain fronts
    OUTPUT_BUCKET         separate R2 bucket the finished reel/burst/clips
                           get uploaded to -- the public one, same as
                           before PIC-153. Deliberately not the same value
                           as BUCKET: that conflation is the mistake
                           PIC-153 found.
    LOGO_URL              optional: public CDN URL of the venue's logo, set
                           only when the venue turned "Show logo on reel
                           videos" on in Settings (lib/reelLogo.ts decides).
                           Burnt into every clip's lower-right corner.
    SEGMENT_KEYS_JSON     JSON list of R2 keys, the venue's raw recording
                           segments (already uploaded by the desktop app --
                           this is the actual "delete the operator's
                           machine from the data path" fix: those bytes go
                           venue -> R2 -> pod directly now, never through
                           the operator's own uplink)
    CALIB_JSON            the venue's calib.json, inline (small, no need
                           for its own R2 round trip)
    TARGET_SEC            reel length target
    SESSION_ID
    CONSOLE_URL, RUNNER_TOKEN  same console API job_runner.py already
                           uses (PATCH /api/runner/jobs/<id>) -- reused
                           as-is rather than inventing a second reporting
                           path. Known, accepted gap (ADR-093's own open
                           risks list): this is the operator's
                           account-wide runner token, not a token scoped
                           to this one job. Scoping that is real future
                           work, not done here.
    CLOUDFLARE_R2_ACCOUNT_ID   only the account id, for the endpoint URL.
                           NOT the account's R2 keys (PIC-138, 2026-09-20):
                           a pod used to be handed full read/write/delete
                           across every venue's footage and reels.
    R2_READ_ACCESS_KEY_ID / R2_READ_SECRET_ACCESS_KEY / R2_READ_SESSION_TOKEN
    R2_WRITE_ACCESS_KEY_ID / R2_WRITE_SECRET_ACCESS_KEY / R2_WRITE_SESSION_TOKEN
                           two short-lived credentials the console minted
                           for THIS job (POST /api/runner/jobs/<id>/
                           credentials), each bound to one bucket and
                           expiring ~4h out. READ can only get/head this
                           job's segments plus pipeline/ and weights/ in
                           the private bucket; WRITE can only put under
                           <brand>/reels/ in the public one. Neither can
                           list or delete, and neither can touch another
                           venue. See lib/podGrants.ts in the console.
    RUNPOD_API_KEY         so this pod can delete itself when done. Same
                           gap: this is the full account key, not scoped
                           to "delete only this pod."

Reuses, unmodified: `scripts/pod_infer.py` (subprocess -- the ADR-064/065
byte-identical-output guarantee is pinned to not touching this code), and
`build_reel`/`build_burst_reel` (imported directly, no reason to subprocess
these now that this runs as one process instead of over SSH).

Progress reporting doubles as the cancellation channel: every PATCH to the
console is answered with whether the operator asked to cancel (same
`cancelRequested` mechanic `job_runner.py`'s own `patch_job` already uses)
-- checked between stages, same as `run_cloud_job.py`'s `_check_cancel`.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid

import boto3
import requests

REPO_ROOT = "/workspace"
sys.path.insert(0, REPO_ROOT)

from scripts.check_drift import measure as drift_measure  # noqa: E402
from scripts.rank_and_reel import WEIGHTS, build_reel  # noqa: E402
from scripts.burst_moment_reel import build_burst_reel  # noqa: E402
from scripts.top_rallies_reel import build_top_rallies  # noqa: E402
from src.drift import drift_span, find_bumps  # noqa: E402
from src.rallies import detect_candidates  # noqa: E402
from src.video_quality import BLOCK_BELOW_FPS, check_video  # noqa: E402

WORKDIR = "/workspace/job"
WEIGHTS_R2_KEY = "weights/weights_k14_epoch19.tar"
WEIGHTS_LOCAL = "/workspace/weights_k14_epoch19"
# Static Linux x86_64 builds from BtbN/FFmpeg-Builds (the `linux64-gpl`
# variant), uploaded to R2 once by hand, not per job -- see runpod_pod.py's
# _BOOTSTRAP_CMD comment for why this replaced an `apt-get install ffmpeg`
# that ran on every job. Landing at /usr/local/bin puts them ahead of any
# apt-installed ffmpeg on PATH (Debian convention), so every later bare
# "ffmpeg"/"ffprobe" subprocess call -- here and in src/video_quality.py,
# scripts/rank_and_reel.py -- picks these up with no call-site changes.
#
# PIC-156 (2026-09-19): these REPLACE the ffmpeg-static/ffprobe-static npm
# binaries this originally used. Those are johnvansickle.com portable
# builds, which deliberately ship no NVIDIA encoder -- so `-c:v h264_nvenc
# ... -cq 20` below died on argument parsing ("Unrecognized option 'cq'")
# on the first real pod job, meaning every reel job failed at the convert
# step. Reusing the desktop app's binaries looked free because the desktop
# never encodes anything (recording is -c copy, live view an MJPEG remux,
# per ADR-101) -- the pod is the one consumer that needs an encoder the
# desktop never touches.
#
# Verified before upload, on this project's own RTX 2000 Ada (the same GPU
# model RunPod rents us) rather than by `-version` alone, since a passing
# `-version` is exactly what hid the defect last time: h264_nvenc present
# in -encoders, a real NVENC encode completed, no missing shared libs, and
# both `-vsync cfr` and `-fps_mode cfr` accepted (so the older spelling
# used below still works and needs no change). The tarball was checked
# against BtbN's published checksums.sha256 -- a first attempt was
# byte-perfect on SIZE and still corrupt, so size is not the gate.
#
# The key names carry the binary's own `-version` string including the
# upstream git hash, because BtbN's release tag is the rolling `latest`:
# the R2 object is the real pin, and the hash makes which build it is
# recoverable. ffmpeg and ffprobe are now the matched pair from one build,
# which also retires the odd 7.0.2/4.0.2 version gap the npm packages had.
FFMPEG_R2_KEY = "pipeline/ffmpeg-btbn-nvenc-linux-x64-n8.1.2-gc573a95381"
FFPROBE_R2_KEY = "pipeline/ffprobe-btbn-nvenc-linux-x64-n8.1.2-gc573a95381"
FFMPEG_LOCAL = "/usr/local/bin/ffmpeg"
FFPROBE_LOCAL = "/usr/local/bin/ffprobe"
BURST_TARGET_SEC = 30.0  # matches pod_cut.py's own pin, same reasoning
TOP_RALLIES_N = 10  # matches pod_cut.py's own pin, operator request 2026-09-12

# pod_infer.py's own periodic progress line, e.g. "  300/29400  75 fps  ETA 6.5 min"
# -- printed every 300 frames (~5s at typical throughput), same regex
# run_cloud_job.py's SSH-streaming path already used.
_PROGRESS_RE = re.compile(r"^\s*(\d+)/(\d+)\s+(\d+)\s*fps\s+ETA\s+([\d.]+)\s*min")

# A status PATCH every 5s would be ~700 requests over a long session's
# inference stage -- fine for the console, but no reason to be that
# chatty. This also doubles as the heartbeat that keeps
# claim_next_job's stale-runner rule from reclaiming a job mid-inference
# (job.kind's PATCH route bumps updated_at on every call) -- inference on
# a full session can run far longer than that staleness window, so
# something has to report in periodically for its whole duration, not
# just at stage boundaries.
PROGRESS_PATCH_INTERVAL_SEC = 20

CONSOLE_URL = os.environ.get("CONSOLE_URL", "https://console.picvisionai.com").rstrip("/")
RUNNER_TOKEN = os.environ["RUNNER_TOKEN"]
JOB_ID = os.environ["JOB_ID"]
# BUCKET is where this job's own raw segments are (private since PIC-153,
# 2026-09-18 -- see r2_storage.py-adjacent lib/r2Presign.ts's
# privateIngestBucket on the console side). OUTPUT_BUCKET is the separate,
# public one the finished reel/burst/clips get uploaded to -- conflating
# the two is exactly the mistake PIC-153 found: private data and public
# data sharing one bucket that a CDN domain then fronts in full.
BUCKET = os.environ["BUCKET"]
OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
# Every key this pod writes to OUTPUT_BUCKET leads with this. Required,
# not defaulted to anything -- job_runner.py already refuses to create a
# pod at all if a job has no brand_id (PIC-153's "refuse rather than
# guess" rule applies here too), so reaching this line with none unset
# would mean that guard was bypassed somehow; better to crash loudly here
# than write an un-prefixed key by accident.
BRAND_ID = os.environ["BRAND_ID"]
LOGO_URL = os.environ.get("LOGO_URL") or None


def _log(msg):
    print(f"[pod-driver {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _fetch_logo(url, workdir):
    """Download the venue's logo, or return None if it can't be had.

    A missing logo costs the venue its corner badge; failing the job would
    cost it the whole reel and a billed GPU run -- so this degrades, and
    says so in the log."""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        path = os.path.join(workdir, "logo" + os.path.splitext(url.split("?")[0])[1])
        with open(path, "wb") as f:
            f.write(resp.content)
        _log(f"logo fetched ({len(resp.content)} bytes) -- burning into every clip")
        return path
    except Exception as e:  # noqa: BLE001 -- see docstring
        _log(f"WARNING: could not fetch logo from {url} ({e}) -- rendering without it")
        return None


def _scoped_r2_client(direction):
    """An S3 client on one of the two credentials the console minted.

    Two, not one, because R2 binds a credential to exactly one bucket --
    which is also the private-input / public-output split PIC-153 exists to
    keep. `direction` is "READ" (the private ingest bucket) or "WRITE" (the
    public output bucket).

    A missing variable is a KeyError naming it, deliberately: the only way
    to reach this without them is a runner that did not fetch scoped
    credentials, and falling back to anything broader would silently undo
    the whole point of them.
    """
    account_id = os.environ["CLOUDFLARE_R2_ACCOUNT_ID"]
    return boto3.client(
        "s3", endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ[f"R2_{direction}_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ[f"R2_{direction}_SECRET_ACCESS_KEY"],
        aws_session_token=os.environ[f"R2_{direction}_SESSION_TOKEN"],
        region_name="auto",
    )


def _r2_clients():
    """(input client, output client). The pod reads from one bucket and
    writes to the other, and holds no credential that can do both."""
    return _scoped_r2_client("READ"), _scoped_r2_client("WRITE")


# How hard to try on the one report that can't be dropped (see
# report_final_job_status). Roughly 1+2+4+8+16+32 = ~63s of retrying, which
# covers a console redeploy or a brief network blip without holding a billed
# pod open for anything like a real outage.
FINAL_REPORT_ATTEMPTS = 6
FINAL_REPORT_BACKOFF_SEC = 1.0


def patch_job(**fields):
    """Same contract as job_runner.py's patch_job: True means the console
    wants this job stopped (operator cancelled, or the row moved on
    without us) -- checked by the caller before every stage.

    Progress reports are best-effort on purpose; the report that ENDS a job
    is not -- use report_final_job_status() for that."""
    try:
        r = requests.patch(f"{CONSOLE_URL}/api/runner/jobs/{JOB_ID}",
                           json=fields, headers={"Authorization": f"Bearer {RUNNER_TOKEN}"},
                           timeout=30)
        if r.status_code == 409:
            return True
        r.raise_for_status()
        return bool(r.json().get("cancelRequested"))
    except requests.RequestException as e:
        # The console being briefly unreachable isn't itself a reason to
        # abandon a job already running on a GPU we're paying for -- log
        # and keep going, same as a dropped SSH connection wouldn't have
        # stopped the pod under the old design either.
        _log(f"WARNING: status report failed ({e}), continuing")
        return False


def report_final_job_status(**fields):
    """The last report a pod ever sends (done / error / cancelled), retried.

    Dropping a progress report costs a stale progress bar for 20 seconds.
    Dropping THIS one costs the whole job: by the time it is sent the reels
    are already uploaded to R2, and the console is the only thing that will
    ever know they exist. The pod then self-terminates, `job_runner.py` sees
    a pod that vanished without reporting and marks the job errored, and its
    cleanup deletes the venue's uploaded segments from R2 -- so the operator
    is asked to re-upload a session and re-run a GPU job whose output is
    sitting in the bucket, complete, unreferenced. One momentary 500 from
    the console at exactly the wrong second was enough, because patch_job()
    swallows every failure by design.

    Returns True if the console acknowledged (including a 409: the row
    already moved on, which is an answer, not a failure to deliver)."""
    for attempt in range(1, FINAL_REPORT_ATTEMPTS + 1):
        try:
            r = requests.patch(f"{CONSOLE_URL}/api/runner/jobs/{JOB_ID}",
                               json=fields, headers={"Authorization": f"Bearer {RUNNER_TOKEN}"},
                               timeout=30)
            if r.status_code == 409:
                return True
            r.raise_for_status()
            return True
        except requests.RequestException as e:
            if attempt == FINAL_REPORT_ATTEMPTS:
                # Out of attempts. Say exactly what is now stranded, since
                # this line in the pod's log is the only remaining record
                # that the work was actually finished.
                _log(f"ERROR: could not report the final job status after "
                     f"{FINAL_REPORT_ATTEMPTS} attempts ({e}). Fields: {fields}")
                return False
            delay = FINAL_REPORT_BACKOFF_SEC * (2 ** (attempt - 1))
            _log(f"WARNING: final status report failed ({e}), retrying in {delay:.0f}s "
                 f"[{attempt}/{FINAL_REPORT_ATTEMPTS}]")
            time.sleep(delay)


class Cancelled(Exception):
    pass


def _check_cancel(stage, message):
    # progress=None deliberately included here (unlike the inference
    # heartbeat below): this always marks a real stage change, and the
    # console route only clears the old stage's progress reading when the
    # field is present -- an omitted field would leave the previous
    # stage's frame count showing against this stage's name.
    if patch_job(stage=stage, message=message, progress=None):
        raise Cancelled()


INFERENCE_TIMEOUT_SEC = 7200  # same ceiling run_cloud_job.py's ssh_run(infer_cmd) used


def _run_ffmpeg(args):
    """`-v error` makes ffmpeg print only real errors, not verbose logs --
    but a plain `check=True` with no output capture throws that away,
    leaving nothing but "exit status 1" in the console's error field
    (exactly what happened the first time this ran for real, 2026-09-10).
    Captures stderr and puts it in the exception so a real failure is
    diagnosable from the console alone, no pod SSH access needed (there
    is none)."""
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise FfmpegError(f"{' '.join(args)}\n{result.stderr.strip()}", result.stderr)


class FfmpegError(RuntimeError):
    """`stderr` kept apart from the message because the message also holds
    the command line, and a command that *asked for* h264_nvenc must not
    look like one whose NVENC *failed*."""

    def __init__(self, message, stderr):
        super().__init__(message)
        self.stderr = stderr


def _encode_h264(head, tail):
    """`ffmpeg -y -v error <head> -c:v <encoder> ... <tail>`, on NVENC when
    the card has it and on libx264 when it does not.

    2026-09-21: the runner falls back through eight GPU types when the
    pinned RTX 2000 Ada is busy (runpod_pod.FALLBACK_GPU_TYPES), but the
    ffmpeg build here was only ever verified on the 2000 Ada. Tournament 1
    converted fine on an RTX 6000 Ada; Tournament 2's pod landed on an RTX
    4090 and died with `OpenEncodeSessionEx failed: unsupported device (2)`
    / `No capable devices found`. Why that host could not open an encode
    session was not established (the pod deletes itself) -- so this reacts
    to the failure instead of predicting it from the card name.

    Only a failure that names nvenc in ffmpeg's own stderr falls back: a bad
    input fails the same way on either encoder, and retrying it would just
    double the time to a real error. libx264 -crf 20 is the same quality
    target as nvenc -cq 20; the pod's CPUs make it slower, not unusable.
    The pinned BtbN build was checked to contain libx264 and to produce a
    valid 30fps yuv420p file from this exact argument list."""
    base = ["ffmpeg", "-y", "-v", "error", *head]
    try:
        _run_ffmpeg([*base, "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20", *tail])
    except FfmpegError as e:
        if "nvenc" not in e.stderr.lower():
            raise
        _log("WARNING: NVENC is unavailable on this GPU/host, encoding on the CPU with libx264 "
             "instead (slower, same output format)")
        _run_ffmpeg([*base, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                     "-pix_fmt", "yuv420p", *tail])


def _run_inference_streaming(cmd):
    """Runs pod_infer.py, patching the console with real progress every
    PROGRESS_PATCH_INTERVAL_SEC -- not just at stage start/end. Without
    this, inference (which can run far longer than the console's
    stale-runner reclaim window) would report in exactly once before going
    silent for the whole run, risking another runner claiming this job out
    from under a pod that's still working on it, and leaving the progress
    bar frozen the whole time. Also the one place a cancel mid-inference
    actually has to kill a live process, not just stop before the next
    stage -- inference is the single longest step by far.

    A plain `for line in proc.stdout` blocks on the read syscall itself
    with no timeout -- a stall with zero output (e.g. GPU init hanging
    before the first progress line) would never trip a heartbeat, the
    exact failure mode runpod_pod.py's ssh_run() already documented and
    fixed with a reader thread + queue. Same fix here, so a heartbeat and
    a cancel-check both still happen even if pod_infer.py goes quiet."""
    import queue
    import threading

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1)
    line_q = queue.Queue()

    def _read_lines():
        try:
            for line in proc.stdout:
                line_q.put(line.rstrip("\n"))
        finally:
            line_q.put(None)

    reader = threading.Thread(target=_read_lines, daemon=True)
    reader.start()

    deadline = time.time() + INFERENCE_TIMEOUT_SEC
    last_patch_at = 0.0
    try:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                proc.kill()
                raise TimeoutError(f"inference exceeded {INFERENCE_TIMEOUT_SEC}s")
            try:
                line = line_q.get(timeout=min(remaining, PROGRESS_PATCH_INTERVAL_SEC))
            except queue.Empty:
                line = None  # no output this interval -- still due for a heartbeat below
            else:
                if line is None:  # sentinel: process's stdout closed, it's finished
                    break
                _log(line)

            due = time.time() - last_patch_at >= PROGRESS_PATCH_INTERVAL_SEC
            if not due:
                continue
            m = _PROGRESS_RE.match(line) if line else None
            # Only include progress when this tick actually has a fresh
            # value -- omitting the field (not sending progress=None) on a
            # plain heartbeat leaves the console's last real reading in
            # place instead of flickering it to blank every
            # PROGRESS_PATCH_INTERVAL_SEC.
            fields = {"stage": "inference"}
            if m:
                current, total, _fps, eta_min = m.groups()
                fields["progress"] = {"current": int(current), "total": int(total), "eta_sec": float(eta_min) * 60.0}
            cancel = patch_job(**fields)
            last_patch_at = time.time()
            if cancel:
                proc.terminate()
                proc.wait(timeout=10)
                raise Cancelled()
        returncode = proc.wait(timeout=max(0.0, deadline - time.time()))
    finally:
        if proc.stdout:
            proc.stdout.close()
        reader.join(timeout=5.0)
        if proc.poll() is None:
            proc.kill()
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, cmd)


def _self_terminate(pod_id):
    key = os.environ.get("RUNPOD_API_KEY")
    if not (key and pod_id):
        _log("no RUNPOD_API_KEY/pod id available -- cannot self-terminate, "
             "an external sweep must catch this (ADR-093 open risk)")
        return
    try:
        requests.delete(f"https://rest.runpod.io/v1/pods/{pod_id}",
                        headers={"Authorization": f"Bearer {key}"}, timeout=30)
        _log(f"self-terminated pod {pod_id}")
    except requests.RequestException as e:
        _log(f"WARNING: self-terminate failed ({e}) -- an external sweep must catch this")


def run():
    s3_in, s3_out = _r2_clients()
    os.makedirs(WORKDIR, exist_ok=True)

    # Must land before anything below shells out to "ffmpeg"/"ffprobe" --
    # the first such call is the segment concat a few lines down.
    _check_cancel("setup", "fetching ffmpeg...")
    for local_path, key in ((FFMPEG_LOCAL, FFMPEG_R2_KEY), (FFPROBE_LOCAL, FFPROBE_R2_KEY)):
        s3_in.download_file(BUCKET, key, local_path)
        os.chmod(local_path, 0o755)

    segment_keys = json.loads(os.environ["SEGMENT_KEYS_JSON"])
    calib = json.loads(os.environ["CALIB_JSON"])
    target_sec = float(os.environ.get("TARGET_SEC", "180"))
    session_id = os.environ.get("SESSION_ID", JOB_ID)

    calib_path = os.path.join(WORKDIR, "calib.json")
    with open(calib_path, "w") as f:
        json.dump(calib, f)

    # --- Pull the venue's own raw segments straight from R2. This is the
    # actual fix: under the old design the operator's workstation
    # downloaded these, converted them, and re-uploaded a proxy -- two
    # hops through the operator's own uplink for bytes that never needed
    # to go anywhere near it. ---
    _check_cancel("download", f"downloading {len(segment_keys)} recording segment(s)...")
    seg_dir = os.path.join(WORKDIR, "segments")
    os.makedirs(seg_dir, exist_ok=True)
    local_segments = []
    for key in segment_keys:
        local = os.path.join(seg_dir, os.path.basename(key))
        s3_in.download_file(BUCKET, key, local)
        local_segments.append(local)

    if len(local_segments) == 1:
        raw_video = local_segments[0]
    else:
        list_path = os.path.join(WORKDIR, "concat_list.txt")
        raw_video = os.path.join(WORKDIR, "session_full.mkv")
        with open(list_path, "w") as f:
            for p in sorted(local_segments):
                f.write(f"file '{p}'\n")
        _run_ffmpeg(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                     "-i", list_path, "-c", "copy", raw_video])

    # --- Same input gate run_cloud_job.py ran locally before spending
    # anything on this session -- cheapest check, still first. ---
    _check_cancel("input_check", "checking the recording's frame rate...")
    quality = check_video(raw_video)
    if not quality["passes"]:
        report_final_job_status(error=f"This recording can't be processed: {quality['reason']}")
        return

    _check_cancel("drift_check", "checking for camera drift...")
    samples, _ = drift_measure(raw_video, step_sec=60.0, width=960)
    bumps = find_bumps(samples, min_step_px=5.0)
    if bumps:
        span_x, span_y = drift_span(samples)
        _log(f"WARNING: {len(bumps)} camera bump(s), max span "
             f"{max(span_x, span_y):.0f}px (ADR-049) -- continuing anyway")

    # --- The step that used to need the operator's own NVIDIA card
    # (ADR-093 reason 1). Same ffmpeg recipe run_cloud_job.py's old local
    # version used, except `-vsync cfr` in place of `-fps_mode cfr`
    # (ffmpeg 5.1+). That substitution was originally forced by the pod's
    # apt-installed ffmpeg (Ubuntu 22.04's package predates the newer
    # spelling); that ffmpeg is gone as of PIC-154/PIC-156 and the pinned
    # BtbN build now used accepts BOTH spellings -- verified directly, not
    # assumed. Kept as `-vsync cfr` because it works on both old and new
    # and this is not the change to fold a cosmetic rename into.
    _check_cancel("convert", "converting to 30fps CFR...")
    cfr_video = os.path.join(WORKDIR, "video_cfr.mp4")
    _encode_h264(["-err_detect", "ignore_err", "-i", raw_video],
                 ["-an", "-vsync", "cfr", "-r", "30", cfr_video])

    _check_cancel("proxy", "preparing the inference/upload resolution...")
    if not calib.get("calibration_resolution"):
        _log("WARNING: calib.json has no calibration_resolution -- using full-res")
        proxy_video = cfr_video
    else:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=height", "-of", "csv=p=0", cfr_video],
            capture_output=True, text=True, check=True)
        native_height = int(probe.stdout.strip())
        if native_height <= 1080:
            proxy_video = cfr_video
        else:
            proxy_video = os.path.join(WORKDIR, "video_proxy_1080p.mp4")
            _encode_h264(["-i", cfr_video, "-vf", "scale=-2:1080"], ["-an", proxy_video])

    # --- Weights: same R2-cached tarball every pod-based run already used. ---
    _check_cancel("inference", "fetching model weights...")
    if not os.path.exists(WEIGHTS_LOCAL):
        weights_tar = os.path.join(WORKDIR, "weights.tar")
        s3_in.download_file(BUCKET, WEIGHTS_R2_KEY, weights_tar)
        subprocess.run(["tar", "-xf", weights_tar, "-C", "/workspace", "--no-same-owner"],
                       check=True)

    _log("running TrackNet inference...")
    csv_path = os.path.join(WORKDIR, "predictions.csv")
    infer_cmd = ["python3", os.path.join(REPO_ROOT, "scripts", "pod_infer.py"),
                 "--video", proxy_video, "--model", WEIGHTS_LOCAL,
                 "--output", csv_path, "--calib", calib_path]
    _run_inference_streaming(infer_cmd)

    # --- Cut, same as pod_cut.py did over SSH -- called directly now,
    # same functions, no subprocess/SSH round trip needed for something
    # already running in-process. ---
    _check_cancel("cut", "detecting rallies, ranking, cutting reel...")
    # A stretch with no rallies (a warm-up, a break, an empty court) is a
    # real outcome, far likelier now that a session is sent in 10-20 minute
    # parts (ADR-127): finish with no reels instead of crashing the job
    # (found in the 2026-09-23 auto-split rehearsal, ADR-129).
    if not detect_candidates(proxy_video, csv_path, calib_path)["segments"]:
        _log("no rallies found in this footage; finishing with no reels")
        finish_with_no_rallies()
        return
    reel_dir = os.path.join(WORKDIR, "reel")
    logo_path = _fetch_logo(LOGO_URL, WORKDIR)
    full_result = build_reel(proxy_video, csv_path, calib_path, os.path.join(reel_dir, "full"),
                              target_sec, session_id, weights=WEIGHTS, include_chronological=False,
                              logo_path=logo_path)
    burst_result = build_burst_reel(proxy_video, csv_path, calib_path, os.path.join(reel_dir, "burst"),
                                     BURST_TARGET_SEC, session_id, logo_path=logo_path)
    has_burst = burst_result["chronological"] is not None
    top_result = build_top_rallies(proxy_video, csv_path, calib_path, os.path.join(reel_dir, "top"),
                                    session_id, n=TOP_RALLIES_N, logo_path=logo_path)
    stats = {"full": full_result["stats"], "burst": burst_result["stats"] if has_burst else None,
             "top_rallies": top_result["stats"]}

    _check_cancel("r2_download", "uploading finished reel(s) to R2...")
    reel_id = os.environ.get("REEL_ID")
    burst_reel_id = os.environ.get("BURST_REEL_ID")
    # Brand-prefixed, and uploaded to OUTPUT_BUCKET (the public one), not
    # BUCKET (this job's private input) -- PIC-153, 2026-09-18. Before this,
    # every reel/burst/clip key was a flat reels/<id>.mp4 with no venue
    # attached to it at all; lib/reels.ts (console) still accepts that
    # exact old shape too, for the separate SSH-driven path that wasn't
    # migrated in the same change (see that file's own comment).
    ranked_key = f"{BRAND_ID}/reels/{reel_id}.mp4"
    s3_out.upload_file(os.path.join(reel_dir, "full", "highlight_by_rank.mp4"), OUTPUT_BUCKET, ranked_key)
    reels = []
    # Top-rally clips: unlike full/burst (always exactly 0 or 1 file, ids
    # pre-minted by job_runner.py before this pod even started), the count
    # here is only known now, so each clip mints its own id at upload time.
    for clip in top_result["manifest"]:
        clip_reel_id = str(uuid.uuid4())
        clip_key = f"{BRAND_ID}/reels/{clip_reel_id}.mp4"
        s3_out.upload_file(os.path.join(reel_dir, "top", clip["file"]), OUTPUT_BUCKET, clip_key)
        reels.append({
            "kind": "rally", "reel_id": clip_reel_id, "key": clip_key,
            "rank": clip["rank"],
            "stats": {"total_duration_sec": clip["duration"], "n_chosen": 1},
        })
    reels.append({"kind": "full", "reel_id": reel_id, "key": ranked_key, "stats": stats["full"]})
    if has_burst:
        burst_key = f"{BRAND_ID}/reels/{burst_reel_id}.mp4"
        s3_out.upload_file(os.path.join(reel_dir, "burst", "highlight.mp4"), OUTPUT_BUCKET, burst_key)
        reels.append({"kind": "burst", "reel_id": burst_reel_id, "key": burst_key, "stats": stats["burst"]})

    # Retried, not best-effort: every reel above is already in R2 and this
    # message is the only thing that will ever tell the console they exist.
    # reel_bucket is OUTPUT_BUCKET here, not BUCKET (this job's private
    # input) -- reels.r2_bucket has to name where the reel actually landed,
    # or a later read of that row would look in the wrong bucket.
    report_final_job_status(done=True, stage="done", message="done", progress=None, result={
        "share_id": os.environ.get("SHARE_ID"), "reel_bucket": OUTPUT_BUCKET,
        "reels": reels, "stats": stats,
    })
    _log(f"done: {reels}")


def finish_with_no_rallies():
    """Report a finished job that found no rallies: done, with no reels."""
    return report_final_job_status(done=True, stage="done", message="no rallies found", progress=None, result={
        "share_id": os.environ.get("SHARE_ID"), "reel_bucket": OUTPUT_BUCKET,
        "reels": [], "stats": {"n_candidates": 0},
    })


def main():
    pod_id = os.environ.get("RUNPOD_POD_ID")  # RunPod sets this itself, every pod
    try:
        run()
    except Cancelled:
        _log("cancelled by operator")
        report_final_job_status(cancelled=True, message="cancelled")
    except Exception as e:  # noqa: BLE001 -- report every failure, this pod is billed either way
        _log(f"FAILED: {e}")
        try:
            # Also retried: a failure nobody is told about leaves the job
            # sitting at 'running' until job_runner.py's own deadline, with
            # the real reason only ever printed in this pod's log -- and the
            # pod is about to delete itself.
            report_final_job_status(error=str(e)[:2000])
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        _self_terminate(pod_id)


if __name__ == "__main__":
    main()
