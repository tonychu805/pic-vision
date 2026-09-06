"""The input gate that decides whether a session is worth processing.

Tested against constructed profiles rather than synthesised video: the
decision is what matters here, and building real files at exact frame rates
is slow and imprecise (an early attempt produced 33% degradation when 50%
was intended, purely from ffmpeg's timestamp handling).
"""
from src.video_quality import BLOCK_BELOW_FPS, MAX_DEGRADED_FRACTION, evaluate


def profile(rates, bucket_sec=30.0):
    buckets = [{"start_sec": i * bucket_sec, "fps": r} for i, r in enumerate(rates)]
    ordered = sorted(rates)
    return {
        "overall_fps": sum(rates) / len(rates),
        "median_fps": ordered[len(ordered) // 2],
        "min_bucket_fps": ordered[0],
        "duration_sec": len(rates) * bucket_sec,
        "buckets": buckets,
        "dips": [],
    }


def test_a_clean_30fps_session_passes():
    r = evaluate(profile([30.0] * 10))
    assert r["passes"] is True
    assert r["below_floor_fraction"] == 0.0
    assert r["reason"] is None


def test_2997_ntsc_passes():
    # A real, extremely common rate that means "30" in practice.
    assert evaluate(profile([29.97] * 10))["passes"] is True


def test_a_flat_15fps_session_fails_and_blames_the_setting():
    r = evaluate(profile([15.0] * 10))
    assert r["passes"] is False
    assert "throughout" in r["reason"]
    assert "configured too low" in r["reason"]
    # Must NOT send someone chasing lights or Wi-Fi for a settings problem.
    assert "mid-session" not in r["reason"].replace("not a mid-session drop", "")


def test_a_session_that_sags_for_most_of_its_length_fails_and_blames_conditions():
    # Fine for 2 minutes, then collapses for 8.
    r = evaluate(profile([30.0] * 4 + [14.0] * 16))
    assert r["passes"] is False
    assert r["below_floor_fraction"] == 0.8
    assert "conditions changing" in r["reason"]
    assert "configured too low" not in r["reason"]


def test_the_median_cannot_hide_half_a_bad_session():
    # The bug this replaced: [30]*10 + [15]*10 has a median of 30, so a
    # median-based gate passed it -- half a session of missing rallies.
    r = evaluate(profile([30.0] * 10 + [15.0] * 10))
    assert r["frame_rate"]["median_fps"] >= BLOCK_BELOW_FPS  # median still looks fine
    assert r["below_floor_fraction"] == 0.5
    assert r["passes"] is True   # exactly at the limit, not over it


def test_degradation_within_the_limit_passes_but_is_recorded():
    # A usable reel still comes out of the good majority; the fraction is
    # kept so a thinner reel can be explained afterwards.
    r = evaluate(profile([30.0] * 8 + [12.0] * 2))
    assert r["passes"] is True
    assert r["below_floor_fraction"] == 0.2
    assert r["below_floor_fraction"] <= MAX_DEGRADED_FRACTION


def test_an_unprobeable_file_never_fails_a_job():
    # Refusing real footage over missing data is worse than the problem.
    r = evaluate(None)
    assert r["passes"] is True
    assert r["frame_rate"] is None
