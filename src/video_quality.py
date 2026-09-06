"""Does this video meet the pipeline's input requirements?

Checked before a job spends anything, because a session that can't yield
decent rallies costs exactly as much to process as one that can: the same
R2 transfer, the same GPU pod, the same minutes.

The frame-rate floor is measured, not assumed (EXPERIMENTS.md 2026-09-06):
the same footage scored precision 0.75 / recall 0.46 at 30fps and 0.60 /
0.23 at 15fps -- half the rallies found, with no threshold recovering them.
30 is also the rate every shipped constant was tuned at (config.yaml's
`capture.fps`, `track_ball`'s max_jump, `min_crossings`).

Reported as a per-bucket profile rather than one average, because the two
ways a session ends up slow need opposite responses and a single number
hides which one happened:

  flat and low        the camera is *configured* wrong -- the whole session
                      is degraded, and the fix is one setting
  starts fine, dips   conditions changed mid-session (indoor light falling
                      is the common one: cameras lengthen exposure and drop
                      frame rate to compensate) -- only part of the session
                      is affected, and the fix is lights or network

Averaging those together produces the same "22 fps" for both.

Reads packet timestamps only -- never decodes a frame -- so it costs a
fraction of a second even on a two-hour file.
"""
import json
import logging
import subprocess

log = logging.getLogger(__name__)

# The rate everything downstream was tuned at.
MIN_FPS = 30.0

# ...compared with slack. 29.97 (NTSC) is a real rate meaning "30" in
# practice, and a measurement off real packets carries noise; failing a
# correctly-configured camera on a rounding artefact would be worse than
# the problem. Mirrors desktop/electron/cameras/frameRate.js.
BLOCK_BELOW_FPS = 29.0

# A bucket that falls this far below the session's own median is a real dip
# rather than jitter -- used only to describe *where* it sagged, never to
# pass or fail, which is BLOCK_BELOW_FPS's job alone.
DIP_RATIO = 0.85

# How much of a session may sit below the floor before the job isn't worth
# running. Some degradation still yields a usable reel from the rest; a
# majority does not, and costs the same R2 transfer and GPU minutes either
# way. Not a measured constant -- no session with partial degradation has
# been scored yet -- so it's a deliberate judgement, marked as one.
MAX_DEGRADED_FRACTION = 0.5

BUCKET_SEC = 30.0


def _packet_times(video_path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts_time", "-of", "csv=p=0", video_path],
        capture_output=True, text=True, check=True).stdout
    return sorted(float(t) for t in out.split() if t and t != "N/A")


def frame_rate_profile(video_path, bucket_sec=BUCKET_SEC):
    """Overall and per-bucket frame rate, measured from packet timestamps.

    Returns None when the file can't be probed or is too short to judge --
    an unknown rate must never fail a job, same rule the desktop guard
    follows: refusing real footage over missing data is worse than the
    problem it prevents.
    """
    try:
        times = _packet_times(video_path)
    except Exception as e:  # noqa: BLE001 - a probe failure must not fail a job
        log.warning("could not probe %s (%s)", video_path, e)
        return None
    if len(times) < 10:
        return None

    span = times[-1] - times[0]
    if span <= 0:
        return None

    buckets = {}
    for t in times:
        buckets.setdefault(int((t - times[0]) // bucket_sec), []).append(t)
    # The final bucket is usually a partial window, so its count divided by a
    # full bucket_sec would read as a spurious collapse to near-zero. Dropped
    # rather than reported as a dip.
    complete = sorted(k for k in buckets if k < max(buckets)) or sorted(buckets)
    per_bucket = [{"start_sec": k * bucket_sec, "fps": round(len(buckets[k]) / bucket_sec, 2)}
                  for k in complete]

    rates = sorted(b["fps"] for b in per_bucket)
    median = rates[len(rates) // 2]
    # Median, not mean: a live stream ramps up, and one slow first bucket
    # would otherwise drag the whole session's figure down.
    return {
        "overall_fps": round((len(times) - 1) / span, 2),
        "median_fps": median,
        "min_bucket_fps": rates[0],
        "duration_sec": round(span, 1),
        "buckets": per_bucket,
        "dips": [b for b in per_bucket if b["fps"] < median * DIP_RATIO],
    }


def stream_info(video_path):
    """Codec and resolution, for the record. Never a pass/fail input --
    720p was measured to detect as well as 1080p (EXPERIMENTS.md
    2026-08-28), so resolution is recorded, not gated."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,width,height", "-of", "json", video_path],
            capture_output=True, text=True, check=True).stdout
        s = (json.loads(out).get("streams") or [{}])[0]
        return {"codec": s.get("codec_name"), "width": s.get("width"), "height": s.get("height")}
    except Exception as e:  # noqa: BLE001
        log.warning("could not read stream info for %s (%s)", video_path, e)
        return {}


def check_video(video_path):
    """Everything a job should know about its input before spending on it.

    Returns {"passes", "reason", "below_floor_fraction", "frame_rate",
    "stream"}. `passes` is False only for a rate we actually measured that
    falls below the floor for most of the session -- an unprobeable file
    passes, and fails later on its own terms if it's genuinely broken
    (pod_infer.py's own decode-integrity check).
    """
    return evaluate(frame_rate_profile(video_path), stream_info(video_path), video_path)


def evaluate(profile, stream=None, video_path="video"):
    """The pass/fail decision, separated from probing so it can be tested
    against constructed profiles rather than synthesised video files."""
    result = {"passes": True, "reason": None, "below_floor_fraction": 0.0,
              "frame_rate": profile, "stream": stream or {}}
    if not profile:
        return result

    # Judged on how much of the session is unusable, NOT on the median.
    # A session that ran at 30 for half its length and 15 for the other half
    # has a median of 30 and would sail through -- verified, that exact case
    # passed an earlier median-based version of this check. Half a session
    # of missing rallies is precisely what this exists to catch.
    bad = [b for b in profile["buckets"] if b["fps"] < BLOCK_BELOW_FPS]
    result["below_floor_fraction"] = round(len(bad) / len(profile["buckets"]), 2)
    if not bad:
        return result

    # Passing with degradation still carries the profile, so a thinner reel
    # can be explained afterwards by pointing at the windows that were slow.
    if result["below_floor_fraction"] <= MAX_DEGRADED_FRACTION:
        log.warning("%s: %.0f%% of the session is below %.0f fps but continuing",
                    video_path, result["below_floor_fraction"] * 100, BLOCK_BELOW_FPS)
        return result

    result["passes"] = False
    worst = min(bad, key=lambda b: b["fps"])
    # Flat vs. sagging: the same shortfall, two different faults, two
    # different fixes -- and only one of them is a camera setting.
    if result["below_floor_fraction"] >= 0.9:
        result["reason"] = (
            f"recorded at {profile['median_fps']:.1f} fps throughout, below the "
            f"{MIN_FPS:.0f} fps the detector needs -- at this rate roughly half the "
            f"rallies go undetected. The camera is configured too low; this is not "
            f"a mid-session drop.")
    else:
        result["reason"] = (
            f"frame rate was below {MIN_FPS:.0f} fps for "
            f"{result['below_floor_fraction'] * 100:.0f}% of this session, dropping to "
            f"{worst['fps']:.1f} fps around {int(worst['start_sec'] // 60)} min in. "
            f"The camera did not start out slow, so this is conditions changing "
            f"mid-session -- falling light or a struggling network, not a setting.")
    return result
