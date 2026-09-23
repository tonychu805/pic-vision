"""Operator-side job runner (ADR-084, thin agent).

Polls the cloud console for queued jobs. Reel jobs (ADR-093) are handed
straight to a self-driving RunPod pod (cloud_pipeline/pod_driver.py): this
process packages pod_driver.py + its dependency closure as a tarball,
uploads it to R2, creates the pod against the stock, unmodified
DEFAULT_IMAGE with a `dockerStartCmd` that fetches and runs that tarball
(runpod_pod.py's create_selfdriving_pod), and then just waits for the pod
to disappear (self-terminate) or hit a deadline -- it never downloads a
video, runs ffmpeg, or holds an SSH connection anymore. The pod reports
its own progress to the console over HTTPS (PATCH /api/runner/jobs/<id>)
and inserts the finished `reels` rows itself via that same route; this
process never sees a video byte for a reel job.

Deliberately NOT a custom baked image (tried first, abandoned 2026-09-10):
see runpod_pod.py's create_selfdriving_pod for why -- a derived image
reliably hung at container start on RunPod across 8 real attempts, for a
reason never identified, despite working perfectly in local Docker every
time.

Calibration fits still run right here (kind = "calibration"): the operator
clicked 14 points on a snapshot in the console; the fit is
save_calibration.build_calibration(), unchanged, and the result goes back
onto the camera row for every later reel job to use. That's CPU-only,
seconds long, and never needed a pod in the first place.

Needs, from .env: RUNNER_TOKEN (same value set on the console), the
CLOUDFLARE_R2_* keys and RUNPOD_API_KEY the pipeline already needs.
Optional: CONSOLE_URL, RUNNER_WORK_DIR, RUNNER_ID.

    make runner            # or: .venv/bin/python -m cloud_pipeline.job_runner
"""
import concurrent.futures
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import uuid

import requests
from dotenv import load_dotenv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
load_dotenv(os.path.join(REPO_ROOT, ".env"))

from cloud_pipeline import pod_deps, r2_storage, runpod_pod  # noqa: E402
from cloud_pipeline.save_calibration import build_calibration  # noqa: E402

CONSOLE_URL = os.environ.get("CONSOLE_URL", "https://console.picvisionai.com").rstrip("/")
RUNNER_TOKEN = os.environ.get("RUNNER_TOKEN")
WORK_DIR = os.environ.get("RUNNER_WORK_DIR", os.path.join(REPO_ROOT, "cloud_pipeline", "jobs", "runner"))
RUNNER_ID = os.environ.get("RUNNER_ID", socket.gethostname())

POLL_SEC = 5

# Backoff while there is nothing to do (2026-09-20). This loop used to
# poll every POLL_SEC forever: 17,280 calls a day, ~518k a month, against
# a Netlify function, doing nothing. That alone exceeded the account's
# quota and took console/share/marketing down for five days before anyone
# noticed -- the runner's own "claim failed" lines went to journald, which
# is not a place anybody watches.
#
# Backs off to IDLE_MAX_SEC after IDLE_RAMP_AFTER consecutive empty
# claims, and snaps straight back to POLL_SEC the moment a job appears, so
# a busy period still polls tightly. Worst case a job waits IDLE_MAX_SEC
# before being picked up, which is nothing against a ~10 minute reel job --
# but it IS something against a calibration, which a person is watching a
# spinner for (58s observed, 2026-09-20). The console's "may not be running"
# threshold is coupled to this: RUNNER_IDLE_POLL_MS in
# pic-vision-cloud-console/lib/calibrationTiming.ts. Change one, change both.
IDLE_RAMP_AFTER = 3
IDLE_MAX_SEC = 60

TERMINAL_STAGES = ("done", "error", "cancelled")


def idle_sleep_sec(consecutive_idle_polls):
    """How long to wait after an empty claim.

    Pure, so the ramp is testable without a clock or a console. The first
    few empty polls stay fast -- a job queued moments after the previous
    one finished is the common case, and making that wait a minute would
    be a regression for no saving.
    """
    if consecutive_idle_polls < IDLE_RAMP_AFTER:
        return POLL_SEC
    return IDLE_MAX_SEC

# How often to ask RunPod whether the pod is still there, and how long to
# wait before deciding it's stuck rather than just slow. 15s is cheap
# against RunPod's own API (unlike the old MIRROR_SEC=3, which was reading
# a local file); 3 hours covers convert+proxy+inference+cut on the
# longest realistic session with real margin -- pod_driver.py's own
# inference step alone is capped at 7200s (2h), and every step before or
# after it is minutes, not hours. A pod that hasn't self-terminated by
# then almost certainly hit something pod_driver.py's own exception
# handling didn't catch (a host failure, an OOM kill) -- ADR-093's still-
# open "who kills an orphaned pod" risk, covered here rather than left to
# an operator noticing a stuck billing pod by hand.
POD_POLL_SEC = 15
JOB_DEADLINE_SEC = 3 * 3600

# ADR-101 documented a real, previously-unexplained RunPod failure mode:
# a pod that gets created but never reports any progress at all -- stuck
# retrying its own container start on a bad host, confirmed there via
# manual observation (repeated "start container: begin" with no further
# output), root cause never identified. Every real successful cold start
# measured for this same image landed under ~160s; 8 minutes is generous
# margin above that and comfortably under claim_next_job's own 15-minute
# stale-'running' reclaim window, so this fires well before that RPC
# could reclaim the same job out from under this still-live wait loop.
# This does not explain *why* a pod gets stuck -- nothing here can, since
# the container never runs any of this project's own code -- it only
# stops the operator from waiting up to JOB_DEADLINE_SEC to find out.
FIRST_CHECKIN_TIMEOUT_SEC = 8 * 60

# RunPod's own live inventory across every fallback GPU type can be
# exhausted at once (confirmed real, 2026-08-26 -- runpod_pod.py's own
# history: all 5 types on that day's list came back "no instances
# available" simultaneously) -- and it comes back, often within minutes.
# Before this, that raised straight away as a job failure with RunPod's
# raw API error text as the message, no retry: a transient capacity gap
# looked identical to a real bug. A short, spaced-out number of retries
# turns a wait for capacity into a visible status message instead of an
# unexplained hard failure, without turning this into an unbounded poll --
# see _create_pod_with_capacity_retry.
GPU_CAPACITY_RETRY_DELAYS_SEC = [60, 180, 300]  # ~1, 3, 5 min

# Reel jobs used to run one at a time: main() claimed a job and blocked on
# run_one() -- which can take from minutes to JOB_DEADLINE_SEC's full 3
# hours -- before claiming the next. Nothing about a reel job needs that:
# since ADR-093 this process never touches a video byte or runs ffmpeg for
# one, it only creates a pod and polls the console every POD_POLL_SEC, so
# N jobs in flight cost N cheap HTTP polls, not N times the local work. The
# console's own claim_next_job already uses `FOR UPDATE SKIP LOCKED`
# specifically so concurrent claims can't collide (app/api/runner/jobs/
# claim/route.ts) -- this was the only side not using that.
#
# The cap is NOT RunPod's account limit: checked 2026-09-22 (GraphQL
# `myself.spendLimit`), this account's hourly spend ceiling is $80, nowhere
# near reachable at these GPU prices and this scale. It exists so the
# number of simultaneously-billing pods, open polling loops, and RunPod API
# calls stays predictable while this is new, not because anything
# downstream enforces a lower number -- raise it once real multi-venue
# usage shows more headroom is needed. Real GPU scarcity is a separate,
# per-job concern already handled by _create_pod_with_capacity_retry above
# -- more concurrent jobs means more contention for the same fallback pool,
# which is exactly why that retry exists.
MAX_CONCURRENT_JOBS = 4


def has_capacity(in_flight_count):
    """Whether the runner should claim another job right now. Pure so the
    cap itself is testable without threads, a real claim, or a console."""
    return in_flight_count < MAX_CONCURRENT_JOBS


def _log(msg):
    print(f"[runner {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _headers():
    return {"Authorization": f"Bearer {RUNNER_TOKEN}"}


def claim_job():
    r = requests.post(f"{CONSOLE_URL}/api/runner/jobs/claim",
                      json={"runnerId": RUNNER_ID}, headers=_headers(), timeout=30)
    if r.status_code == 204:
        return None
    r.raise_for_status()
    return r.json()["job"]


def patch_job(job_id, **fields):
    """Mirror fields onto the console's job row. Returns True when the
    console wants this job cancelled -- either because the operator asked,
    or because the row is no longer `running` (409: reclaimed by another
    runner after we went quiet, or cancelled outright) and anything we do
    from here on is wasted."""
    r = requests.patch(f"{CONSOLE_URL}/api/runner/jobs/{job_id}",
                       json=fields, headers=_headers(), timeout=30)
    if r.status_code == 409:
        return True
    r.raise_for_status()
    return bool(r.json().get("cancelRequested"))


def get_job_status(job_id):
    """Best-effort read of a job's current status -- None on any failure.

    None means "could not find out", never "it failed": _cleanup treats an
    unknown status the same as a failure, i.e. it keeps the segments. The
    cost of being wrong that way is some storage; the cost of the other
    way is a venue re-uploading a 2.5GB session.
    """
    try:
        r = requests.get(f"{CONSOLE_URL}/api/runner/jobs/{job_id}", headers=_headers(), timeout=30)
        r.raise_for_status()
        return r.json().get("status")
    except Exception:  # noqa: BLE001 - never crash cleanup over a status read
        return None


def get_job_state(job_id):
    """Best-effort read of a job's updated_at and cancel_requested -- None
    on any failure (network hiccup, 404).

    None means "could not find out", never "no progress" and never "not
    cancelled": a transient read error must not be mistaken for a stuck pod,
    and must not be mistaken for a cancel either. The caller only acts on a
    CONFIRMED read -- same rule as get_job_status above, and as PIC-157's:
    a check that failed is not a check that came back negative.

    A console that predates `cancel_requested` in this response simply omits
    it, which reads as "not cancelled" -- the behaviour before the field
    existed, and the safe direction to fail.
    """
    try:
        r = requests.get(f"{CONSOLE_URL}/api/runner/jobs/{job_id}", headers=_headers(), timeout=30)
        r.raise_for_status()
        body = r.json()
        return {
            "updated_at": body.get("updated_at"),
            "cancel_requested": bool(body.get("cancel_requested")),
        }
    except Exception:  # noqa: BLE001 - a failed status check must not crash the wait loop
        return None


def _cancel_job(job_id, pod_id=None):
    """Stop a job the operator cancelled before any pod could act on it.

    Cancel normally reaches a job through the POD: every status PATCH the
    pod sends is answered with whether the operator asked to cancel, and the
    pod stops itself. That needs the pod's container to have started. A pod
    that never starts (ADR-101) sends nothing, so the operator's Stop was
    recorded and then ignored -- on 2026-09-20 the runner waited out its
    full first-check-in timeout, then created a SECOND pod for a job that
    had already been cancelled, and both billed.

    The pod is terminated FIRST (that is what stops the billing), and the job
    is then marked cancelled -- not errored, which is what "the pod
    disappeared" would otherwise report and which tells the operator
    something that isn't true. Segments are kept either way (PIC-157).
    """
    if pod_id:
        runpod_pod.terminate_pod(pod_id)
    patch_job(job_id, cancelled=True, message="cancelled by operator before the pod started")
    _log(f"job {job_id}: cancelled by the operator before its pod started"
         + (f" -- pod {pod_id} terminated" if pod_id else " -- no pod was created"))
    return "cancelled"


# The file list and the tarball build live in cloud_pipeline/pod_deps.py,
# shared with the CI build (.github/workflows/pod-deps.yml, ADR-125) so the
# two can't drift. Re-exported here for the existing tests.
POD_DEPS_FILES = pod_deps.POD_DEPS_FILES
POD_DEPS_KEY = "pipeline/pod_deps.tar"


def _upload_pod_deps(bucket):
    """Fresh every job, not cached like ensure_weights_in_r2() -- this
    tarball is source code, and a stale copy would silently run old code
    on the pod. It's a few hundred KB of Python, not 130MB of weights;
    the upload cost of never risking staleness is negligible."""
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
        tar_path = tmp.name
    try:
        pod_deps.build(tar_path)
        r2_storage.upload_file(bucket, tar_path, POD_DEPS_KEY)
    finally:
        os.remove(tar_path)
    return r2_storage.generate_presigned_url(bucket, POD_DEPS_KEY, expires_in=3600)


# The credentials endpoint (PIC-138) gets a few tries on a transient
# failure, because failing here is cheap -- no pod exists yet, so nothing is
# billing -- but a single console hiccup should not cost a venue a retry.
# A 4xx is never retried: those are the console saying "no" on purpose
# (job not running, segments not where the key shape says), and asking again
# cannot change the answer.
CREDENTIAL_ATTEMPTS = 3
CREDENTIAL_BACKOFF_SEC = 2.0


def fetch_pod_credentials(job_id, _sleep=time.sleep):
    """Ask the console for this job's two scoped R2 credentials.

    A pod used to be handed the account's own R2 keys: read, write and
    delete across every venue's footage and reels. It now runs with two
    credentials the console minted for THIS job -- one that can only read
    this job's segments (plus the shared tools and weights), one that can
    only write under this venue's reel folder -- each expiring in about
    four hours (POST /api/runner/jobs/<id>/credentials, PIC-138).

    There is deliberately NO fallback to the account keys in this process's
    environment. If this fails the job fails, before a pod exists. Quietly
    falling back to broader credentials would keep the pipeline working
    while undoing the whole point, and nobody would ever notice.

    Nothing from a success response is ever logged, and errors carry only
    the console's own `error` string: run_one() writes str(exception) into
    the job row, which is readable by the venue, so a credential in an
    exception message would be a credential in a database column.
    """
    url = f"{CONSOLE_URL}/api/runner/jobs/{job_id}/credentials"
    last = None
    for attempt in range(1, CREDENTIAL_ATTEMPTS + 1):
        try:
            r = requests.post(url, headers=_headers(), timeout=30)
        except requests.RequestException as e:
            last = f"could not reach the console ({type(e).__name__})"
        else:
            if r.status_code == 200:
                return r.json()
            try:
                reason = r.json().get("error") or f"HTTP {r.status_code}"
            except ValueError:
                reason = f"HTTP {r.status_code}"
            if r.status_code < 500:
                raise RuntimeError(f"console refused pod credentials for job {job_id}: {reason}")
            last = f"console error {r.status_code}: {reason}"
        if attempt < CREDENTIAL_ATTEMPTS:
            _sleep(CREDENTIAL_BACKOFF_SEC * attempt)
    raise RuntimeError(f"could not get pod credentials for job {job_id} after {CREDENTIAL_ATTEMPTS} attempts: {last}")


def scoped_r2_env(credentials):
    """The pod's R2 environment, from what the console issued.

    Its own function so a test can hold the two halves of the security
    change side by side: that no account key is in the pod's environment,
    AND that the scoped credentials are. Asserting only the first would
    pass with no credentials at all -- a pod that cannot reach R2.
    """
    env = {}
    for direction, key in (("READ", "read"), ("WRITE", "write")):
        cred = credentials[key]
        env[f"R2_{direction}_ACCESS_KEY_ID"] = cred["accessKeyId"]
        env[f"R2_{direction}_SECRET_ACCESS_KEY"] = cred["secretAccessKey"]
        env[f"R2_{direction}_SESSION_TOKEN"] = cred["sessionToken"]
    return env


def run_reel_job(job):
    """ADR-093: hand the whole job to a self-driving pod and wait for it to
    disappear. Everything past this function -- downloading the venue's
    segments, converting, running inference, cutting, uploading, and
    telling the console about all of it -- happens on the pod
    (cloud_pipeline/pod_driver.py), not here. This process holds no video,
    runs no ffmpeg, and opens no SSH connection for a reel job anymore."""
    job_id = job["id"]
    segment_keys = job.get("segment_keys") or []
    if not segment_keys:
        raise RuntimeError("job has no recording segments")

    bootstrap_url = _upload_pod_deps(job["bucket"])

    # job["brand_id"] comes from the claim response (app/api/runner/jobs/
    # claim/route.ts), not from the jobs row itself -- jobs has no brand_id
    # column, only agent_id, and this process never talks to Supabase
    # directly to join it (ADR-084, thin agent: HTTP to the console only).
    # Required, not optional: a job that somehow claims without one would
    # otherwise need pod_driver.py to guess where to put a brand-prefixed
    # reel key, and guessing there is exactly the kind of thing that
    # reopens PIC-153 rather than fixing it.
    brand_id = job.get("brand_id")
    if not brand_id:
        raise RuntimeError(f"job {job_id} has no brand_id -- refusing rather than guessing a reel key")

    # Scoped, expiring credentials for THIS job (PIC-138), fetched before
    # anything is created so a refusal costs nothing.
    #
    # The console also decides both buckets, and they come back with the
    # credentials because each credential is bound to exactly one bucket: a
    # runner that disagreed with the console about where output goes would
    # hold a write credential for a bucket the pod is not writing to, and
    # find out at the final upload. job["bucket"] is the PRIVATE ingest
    # bucket (PIC-153) where this job's segments are; it must be the one the
    # read credential was issued for, or something upstream has drifted.
    credentials = fetch_pod_credentials(job_id)
    if credentials["readBucket"] != job["bucket"]:
        raise RuntimeError(
            f"job {job_id} records input bucket {job['bucket']!r} but the console issued "
            f"credentials for {credentials['readBucket']!r} -- refusing rather than guessing"
        )
    output_bucket = credentials["writeBucket"]

    # Minted here, not on the pod: the console needs these ids to exist
    # (in the pod's final result) as soon as the pod reports done, and
    # there's no coordination reason they can't just be handed to the pod
    # instead of round-tripped through it.
    env = {
        "JOB_ID": job_id,
        "BRAND_ID": brand_id,
        # The venue's logo, only if it chose "Show logo on reel videos" --
        # the claim response's logo_url is already null otherwise
        # (lib/reelLogo.ts in the console). Empty means no logo.
        "LOGO_URL": job.get("logo_url") or "",
        "BUCKET": job["bucket"],
        "OUTPUT_BUCKET": output_bucket,
        "BOOTSTRAP_URL": bootstrap_url,
        "SEGMENT_KEYS_JSON": json.dumps(segment_keys),
        "CALIB_JSON": json.dumps(job["calib"]),
        "TARGET_SEC": str(job.get("target_sec") or 180),
        "SESSION_ID": job.get("session_id") or job_id,
        "REEL_ID": str(uuid.uuid4()),
        "BURST_REEL_ID": str(uuid.uuid4()),
        "SHARE_ID": str(uuid.uuid4()),
        "CONSOLE_URL": CONSOLE_URL,
        "RUNNER_TOKEN": RUNNER_TOKEN,
        # The account id alone -- it only builds the endpoint URL and is
        # not a secret. The account's R2 KEYS no longer go to the pod:
        # what it reads and writes with is scoped_r2_env() below.
        "CLOUDFLARE_R2_ACCOUNT_ID": os.environ["CLOUDFLARE_R2_ACCOUNT_ID"],
        **scoped_r2_env(credentials),
        # Still the full account key, and still the global runner token
        # above: PIC-138's remaining two thirds. Neither can be narrowed
        # the same way -- see the ticket for the sequencing.
        "RUNPOD_API_KEY": os.environ["RUNPOD_API_KEY"],
    }

    # Captured before pod creation, from the row's own state as of the
    # claim (claim_next_job's own UPDATE sets updated_at=now() as part of
    # claiming it) -- the baseline the first-checkin check below compares
    # against. Nothing in this wait loop itself ever PATCHes the job, so
    # any change at all can only mean pod_driver.py actually started and
    # ran its own first _check_cancel() call.
    baseline_updated_at = job.get("updated_at")

    # One deadline for the whole job, not per attempt -- a retry must not
    # be able to double how long a venue waits, or how long a GPU can bill.
    deadline = time.monotonic() + JOB_DEADLINE_SEC

    for attempt, image in enumerate(runpod_pod.POD_IMAGES, start=1):
        outcome = _run_pod_attempt(job_id, env, image, baseline_updated_at, deadline, attempt)
        if outcome != "no_checkin":
            return
        if attempt < len(runpod_pod.POD_IMAGES) and time.monotonic() < deadline:
            # A stuck attempt is the one failure worth retrying by itself:
            # it means the container never ran a line of our code, so
            # nothing has been half-done and nothing has been uploaded.
            # The second attempt uses the backup image, which covers both
            # shapes of this failure at once -- see runpod_pod.POD_IMAGES.
            _log(f"job {job_id}: retrying once on the backup image")
            continue
        patch_job(job_id, error=(
            f"pod reported no progress within {FIRST_CHECKIN_TIMEOUT_SEC // 60} minutes "
            f"of being created, on {attempt} attempt{'s' if attempt != 1 else ''} "
            "-- terminated as a likely stuck container start (see DECISIONS.md ADR-101)"))
        return


class _CapacityWaitCancelled(Exception):
    """The operator cancelled the job while it was waiting for GPU
    capacity, before any pod existed to see the cancel itself."""


def _create_pod_with_capacity_retry(job_id, env, image, deadline):
    """create_selfdriving_pod(), retried with backoff when EVERY fallback
    GPU type comes back unavailable. That is RunPod's live marketplace
    inventory being briefly exhausted, not this job or this image -- unlike
    the stuck-container retry in run_reel_job's caller (which switches to a
    backup IMAGE because the first is suspected broken), so this retries
    the exact same fallback list after a short wait instead.

    Never retries past the job's own deadline. Checks for an operator
    cancel between attempts and during each wait (in POD_POLL_SEC slices,
    same cadence as the post-creation wait loop) -- a wait built from
    GPU_CAPACITY_RETRY_DELAYS_SEC can run several minutes, long enough that
    a Stop click should not sit ignored until a pod exists to see it.

    Raises _CapacityWaitCancelled if the operator cancelled, or the
    original RuntimeError (chained) with a clear, operator-facing message
    if every attempt is spent without ever getting a pod.
    """
    attempts = len(GPU_CAPACITY_RETRY_DELAYS_SEC) + 1
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return runpod_pod.create_selfdriving_pod(
                name=f"cloud-pipeline-{env['SESSION_ID']}", env=env, image=image,
                gpu_type_ids=runpod_pod.FALLBACK_GPU_TYPES)
        except RuntimeError as e:
            last_error = e
        if attempt == attempts:
            break
        delay = GPU_CAPACITY_RETRY_DELAYS_SEC[attempt - 1]
        if time.monotonic() + delay >= deadline:
            break
        _log(f"job {job_id}: no GPU capacity on any of "
             f"{len(runpod_pod.FALLBACK_GPU_TYPES)} fallback types "
             f"(attempt {attempt}/{attempts}) -- retrying in {delay}s")
        patch_job(job_id, message=f"waiting for GPU capacity (attempt {attempt}/{attempts})...")
        remaining = delay
        while remaining > 0:
            step = min(POD_POLL_SEC, remaining)
            time.sleep(step)
            remaining -= step
            state = get_job_state(job_id)
            if state is not None and state["cancel_requested"]:
                raise _CapacityWaitCancelled()
    raise RuntimeError(
        f"no GPU capacity available on any of {len(runpod_pod.FALLBACK_GPU_TYPES)} "
        f"card types after {attempts} attempts over roughly "
        f"{sum(GPU_CAPACITY_RETRY_DELAYS_SEC) // 60} minutes -- RunPod has no free "
        "instances of any fallback type right now; this is not a bug, try again "
        "once capacity frees up"
    ) from last_error


def _run_pod_attempt(job_id, env, image, baseline_updated_at, deadline, attempt):
    """One pod, start to finish. Returns:

      "finished"   the pod is gone; the job has already been reported on
                   (by the pod itself, or by this function)
      "no_checkin" the pod never reported anything at all -- terminated
                   here, job NOT yet marked errored, caller decides
                   whether to try again
      "deadline"   the whole job's deadline passed; terminated and errored
      "cancelled"  the operator cancelled before the pod ever checked in;
                   any pod terminated and the job marked cancelled. Never
                   retried -- the operator said stop.
    """
    first_checkin_seen = False

    # Checked before creating anything, on EVERY attempt. Without this the
    # retry after a stuck first pod created a second pod for a job that had
    # been cancelled while the first was stuck. A None read (console blip)
    # does not cancel: only a confirmed request does.
    state = get_job_state(job_id)
    if state is not None and state["cancel_requested"]:
        return _cancel_job(job_id)

    _log(f"job {job_id}: creating self-driving pod (attempt {attempt}, {image})...")
    try:
        pod_id, gpu_type = _create_pod_with_capacity_retry(job_id, env, image, deadline)
    except _CapacityWaitCancelled:
        return _cancel_job(job_id)
    _log(f"job {job_id}: pod {pod_id} created ({gpu_type}), waiting for it to finish "
         f"(it reports its own progress to the console from here)")

    pod_created_at = time.monotonic()
    while time.monotonic() < deadline:
        time.sleep(POD_POLL_SEC)

        if not first_checkin_seen:
            state = get_job_state(job_id)
            current_updated_at = state["updated_at"] if state is not None else None
            # None means this particular check failed (network hiccup,
            # console blip) -- inconclusive, not evidence of a stuck pod,
            # so it's left to the next poll rather than counted toward
            # the timeout below. Only a CONFIRMED read showing no change
            # counts.
            if current_updated_at is not None and current_updated_at != baseline_updated_at:
                # The pod is up and talking to the console. From here it
                # sees a cancel itself, on its own status PATCHes, and
                # stops gracefully -- reporting its own final result --
                # so this loop deliberately leaves it to. Acting here too
                # would pre-empt that with a hard kill.
                first_checkin_seen = True
            elif state is not None and state["cancel_requested"]:
                # The one window nobody else can see the cancel: the pod
                # has said nothing, so it never will read the flag.
                return _cancel_job(job_id, pod_id)
            elif current_updated_at is not None and \
                    time.monotonic() - pod_created_at > FIRST_CHECKIN_TIMEOUT_SEC:
                # No progress signal at all, well past every successful
                # cold start measured for this image (ADR-101: ~160s
                # worst case) -- the known "stuck at container start"
                # pattern, not a job that's just running slowly. Fails
                # fast rather than waiting out JOB_DEADLINE_SEC; does not
                # auto-retry, matching the deadline path below -- a human
                # decides whether to try again, same as every other
                # reel-job failure.
                _log(f"job {job_id}: pod {pod_id} reported no progress within "
                     f"{FIRST_CHECKIN_TIMEOUT_SEC}s of being created -- likely "
                     f"stuck at container start (ADR-101), terminating")
                runpod_pod.terminate_pod(pod_id)
                # Deliberately not reported to the console yet: the caller
                # may still get this job done on another image, and a job
                # that ends up succeeding should never have flashed an
                # error at the venue on its way there.
                return "no_checkin"

        if not runpod_pod.pod_exists(pod_id):
            # A pod that disappeared having genuinely finished already put
            # the job into a terminal state (done/error/cancelled) via its
            # own PATCH -- this call then hits the console's own
            # status != 'running' guard and does nothing (409, silently
            # ignored here). But "the pod is gone" and "the pod told the
            # console how it ended" are NOT the same fact: a crash, an
            # OOM kill, or the pod being torn down by anything other than
            # its own `finally` (confirmed for real, 2026-09-10 -- a pod
            # killed out from under this exact loop left its job stuck at
            # status='running' forever, because nothing here checked)
            # skips pod_driver.py's own reporting entirely. This call is
            # what turns that into an actual error instead of a job that
            # silently never finishes.
            patch_job(job_id, error="pod disappeared without reporting a final status")
            _log(f"job {job_id}: pod {pod_id} finished")
            return "finished"

    # Nothing but a hung/crashed pod gets here: pod_driver.py reports its
    # own terminal status (done/error/cancelled) and self-terminates
    # before this deadline in every path its own exception handling can
    # catch. This is the backstop for what it can't -- a host failure, an
    # OOM kill, anything that takes the process out before its own
    # `finally` runs -- so the job doesn't sit "running" forever and the
    # pod doesn't keep billing for nothing.
    _log(f"job {job_id}: pod {pod_id} exceeded {JOB_DEADLINE_SEC}s without finishing -- "
         f"terminating and marking errored")
    runpod_pod.terminate_pod(pod_id)
    patch_job(job_id, error=f"job exceeded {JOB_DEADLINE_SEC // 60} minutes without finishing")
    return "deadline"


def run_calibration_job(job):
    job_id = job["id"]
    params = job.get("params") or {}
    job_dir = os.path.join(WORK_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    snapshot_key = params.get("snapshotKey")
    points = params.get("points") or []
    if not snapshot_key or not points:
        raise ValueError("calibration job is missing its snapshot or points")

    patch_job(job_id, stage="calibrate", message="fitting the court homography...")
    snapshot_path = os.path.join(job_dir, "snapshot.png")
    r2_storage.download_file(job["bucket"], snapshot_key, snapshot_path)
    calib, rmse_ft, worst = build_calibration(points, snapshot_path)
    patch_job(job_id, done=True, stage="done",
              message=f"calibrated, reprojection error {rmse_ft:.3f} ft",
              result={"calib": calib, "rmse_ft": rmse_ft, "worst": worst})
    return job_dir


def _cleanup(job, job_dir):
    """Local scratch only. The venue's uploaded segments are not this
    process's to delete anymore (ADR-125).

    The console deletes them when the job is marked `done`, unless that
    venue has agreed to keep its footage for model training
    (pic-vision-cloud-console/lib/footageRetention.ts). A runner deleting
    them here would quietly override that choice -- and this runner is
    being retired, so the decision lives where it outlasts it.

    Every other outcome keeps them, as it has since 2026-09-19 (PIC-157):
    a failed job's footage is what a retry runs on, and the 14-day expiry
    on <venue>/ingest/ (ADR-112) reclaims what is never retried.
    """
    logs = os.path.join(WORK_DIR, "logs")
    os.makedirs(logs, exist_ok=True)
    log_src = os.path.join(job_dir, "log.txt")
    if os.path.exists(log_src):
        shutil.copyfile(log_src, os.path.join(logs, f"{job['id']}.log"))
    shutil.rmtree(job_dir, ignore_errors=True)


def run_one(job):
    kind = job.get("kind", "reel")
    _log(f"claimed {kind} job {job['id']} ({job.get('camera_label') or job.get('camera_id')})")
    job_dir = os.path.join(WORK_DIR, job["id"])
    try:
        if kind == "calibration":
            run_calibration_job(job)
        else:
            run_reel_job(job)
        _log(f"job {job['id']} finished")
    except Exception as e:  # noqa: BLE001 - report every failure back, then keep serving
        _log(f"job {job['id']} FAILED: {e}")
        try:
            patch_job(job["id"], error=str(e)[:2000])
        except Exception as report_err:  # noqa: BLE001
            _log(f"job {job['id']}: couldn't report failure: {report_err}")
    finally:
        _cleanup(job, job_dir)


def _report_unexpected_exception(future):
    """run_one() already catches and reports every failure of its own
    (run_one's try/except) -- this only fires if something escaped THAT,
    which should never happen but must not vanish silently into a Future
    nobody ever calls .result() on if it somehow does."""
    exc = future.exception()
    if exc is not None:
        _log(f"a job's thread raised past its own error handling (this is a bug): {exc}")


def main():
    if not RUNNER_TOKEN:
        sys.exit("RUNNER_TOKEN is not set (add it to .env; same value as the console's)")
    os.makedirs(WORK_DIR, exist_ok=True)
    _log(f"polling {CONSOLE_URL} as {RUNNER_ID}, work dir {WORK_DIR}, "
         f"up to {MAX_CONCURRENT_JOBS} job(s) at once")
    idle_polls = 0
    in_flight = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS) as executor:
        while True:
            in_flight = {f for f in in_flight if not f.done()}
            if not has_capacity(len(in_flight)):
                # Not claimed, not idle-backoff-worthy: this is a busy
                # runner, not an empty queue, so it checks back at the
                # tight cadence, not the ramped-up idle one.
                time.sleep(POLL_SEC)
                continue
            try:
                job = claim_job()
            except Exception as e:  # noqa: BLE001 - console unreachable: wait, don't die
                _log(f"claim failed: {e}")
                # A failing console is also a reason to back off, not to keep
                # hammering it every few seconds -- which is exactly what this
                # loop did for five days straight during the quota outage.
                idle_polls += 1
                time.sleep(max(POLL_SEC * 4, idle_sleep_sec(idle_polls)))
                continue
            if job is None:
                idle_polls += 1
                time.sleep(idle_sleep_sec(idle_polls))
                continue
            idle_polls = 0  # work exists: go back to polling tightly
            _log(f"claimed job {job['id']}, {len(in_flight) + 1} running concurrently")
            future = executor.submit(run_one, job)
            future.add_done_callback(_report_unexpected_exception)
            in_flight.add(future)


if __name__ == "__main__":
    main()
