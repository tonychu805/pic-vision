import numpy as np

from src.drift import phase_offset, find_bumps, drift_span


def _textured(w=160, h=120):
    """Deterministic non-repeating texture — phase correlation needs real
    structure to lock onto, so a flat or periodic image would be ambiguous."""
    rng = np.random.default_rng(0)
    return rng.random((h, w), dtype=np.float32)


def test_phase_offset_is_zero_for_identical_frames():
    img = _textured()
    dx, dy, resp = phase_offset(img, img)
    assert abs(dx) < 0.5 and abs(dy) < 0.5
    assert resp > 0.5


def test_phase_offset_recovers_a_known_shift():
    ref = _textured()
    shifted = np.roll(ref, shift=(7, 4), axis=(0, 1))   # +4 px in x, +7 px in y
    dx, dy, _ = phase_offset(ref, shifted)
    assert abs(dx - 4) < 0.5
    assert abs(dy - 7) < 0.5


def test_find_bumps_flags_a_step():
    # flat, then a hard jump that HOLDS -- the ADR-049 camera-bump signature
    samples = [(t, 0.0, -8.0, 0.4) for t in range(0, 500, 100)]
    samples += [(t, 0.0, -37.0, 0.4) for t in range(500, 900, 100)]
    bumps = find_bumps(samples, min_step_px=5.0)
    assert len(bumps) == 1
    t_before, t_after, sdx, sdy = bumps[0]
    assert (t_before, t_after) == (400, 500)
    assert abs(sdy - (-29.0)) < 0.01


def test_find_bumps_ignores_slow_creep():
    # 1 px per sample for 30 samples = 30 px of total travel, but no single
    # step is large -- gradual drift, NOT a bump. The distinction matters:
    # a bump invalidates calibration from that instant on (ADR-049), whereas
    # creep degrades it smoothly and shows up as rising boundary error.
    samples = [(t, float(i), 0.0, 0.4) for i, t in enumerate(range(0, 3000, 100))]
    assert find_bumps(samples, min_step_px=5.0) == []
    assert drift_span(samples) == (29.0, 0.0)


def test_find_bumps_empty_on_a_locked_camera():
    samples = [(t, 0.05, -0.04, 0.55) for t in range(0, 900, 100)]
    assert find_bumps(samples, min_step_px=5.0) == []
    assert drift_span(samples)[0] < 0.2


def test_find_bumps_handles_too_few_samples():
    assert find_bumps([], min_step_px=5.0) == []
    assert find_bumps([(0, 0.0, 0.0, 0.5)], min_step_px=5.0) == []
    assert drift_span([]) == (0.0, 0.0)
