"""Camera-drift detection: does the camera hold still for the whole recording?

Motivated by ADR-049. IMG_7743 was physically bumped ~47 minutes into a
67-minute session, shifting the net's image position and silently invalidating
`net_y` for everything after it. Nothing downstream noticed: detection kept
working, the crossing counter kept counting, and the only visible symptom was
recall quietly collapsing in the back half of the video. It cost a session to
find by hand, and no amount of threshold tuning recovers it -- the fix is to
recalibrate per segment. So the cheap thing is to CHECK, before labeling or
scoring any new footage, whether the camera moved at all.

The measurement is global image translation via phase correlation against the
first sampled frame. It deliberately does not try to be a homography or a
full stabiliser: a bump on a tripod shows up as a translation, that translation
is exactly what breaks `net_y`, and a scalar per axis is something a human can
read off a table and act on.

Two failure modes, deliberately reported separately, because the responses
differ (see find_bumps and drift_span):
  - a BUMP: a large step between consecutive samples that then holds. Splits
    the video into before/after, each needing its own calibration.
  - CREEP: many small changes accumulating. No clean split point exists;
    it shows up as boundary error rising through the file.

Validated 2026-08-18 against known answers before being trusted: brickwall
(0.1 px over 25 min -- a locked camera reads as locked) and IMG_7743, where
this independently recovered the hand-diagnosed ADR-049 bump inside the
sampling interval containing t=2859s.

Note the response value that phase_offset returns alongside the offsets. It
drops sharply once frames stop resembling the reference (IMG_7743 falls from
~0.40 to ~0.15 across its bump), so it is a confidence reading on the offsets,
not a second drift signal -- low response means "trust these numbers less",
which is why the CLI prints it instead of hiding it.
"""

import cv2
import numpy as np


def phase_offset(ref, img):
    """Global (dx, dy) shift of `img` relative to `ref`, plus a 0..1 response.

    Both inputs are 2-D float32 grayscale of identical shape. A Hanning window
    is applied to both to suppress the edge discontinuity that would otherwise
    dominate the correlation peak on a non-tiling image."""
    ref = np.asarray(ref, dtype=np.float32)
    img = np.asarray(img, dtype=np.float32)
    if ref.shape != img.shape:
        raise ValueError(f"shape mismatch: {ref.shape} vs {img.shape}")
    h, w = ref.shape
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(ref * win, img * win)
    return dx, dy, resp


def find_bumps(samples, min_step_px=5.0):
    """Detect discrete camera bumps in `samples` -- (t, dx, dy, response) rows
    ordered by time, as produced by measuring each sampled frame against the
    first one.

    Returns [(t_before, t_after, step_dx, step_dy), ...]: consecutive-sample
    pairs whose offset changed by more than min_step_px on either axis. The
    times bracket the bump; the true instant lies between them, so sample
    finely enough that the bracket is actionable.

    min_step_px is in pixels at whatever resolution the offsets were measured
    (the CLI's --width, 960 by default). The 5.0 default is provisional, not
    tuned: it sits well above the noise floor of a genuinely locked camera
    (brickwall reads 0.1 px) and well below a real bump (IMG_7743 steps 29 px,
    IMG_7655 25 px), but the footage that would calibrate it properly -- a
    known-size bump scored with and without split calibration -- does not
    exist yet. Anything in the single-digit range is a judgement call."""
    bumps = []
    for (t0, dx0, dy0, _), (t1, dx1, dy1, _) in zip(samples, samples[1:]):
        sdx, sdy = dx1 - dx0, dy1 - dy0
        if abs(sdx) > min_step_px or abs(sdy) > min_step_px:
            bumps.append((t0, t1, sdx, sdy))
    return bumps


def drift_span(samples):
    """Total travel (x_range, y_range) across all samples -- max minus min per
    axis, which counts a bump and slow creep alike. Read it together with
    find_bumps: a large span with no bumps is creep, a large span with a bump
    is mostly that bump."""
    if not samples:
        return (0.0, 0.0)
    xs = [s[1] for s in samples]
    ys = [s[2] for s in samples]
    return (max(xs) - min(xs), max(ys) - min(ys))
