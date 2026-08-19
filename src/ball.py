"""Ball net-crossing signal: backend-agnostic crossing counter and net-line helpers.

Works in image space: in a behind-baseline view the ball's vertical pixel
position (image-y) tells us which side of the net it's on. A crossing is the
ball's image-y crossing the net line, with a hysteresis band so jitter near the
net doesn't inflate the count. Missing/ambiguous frames are skipped.

These functions accept any ball track (YOLO, TrackNet, or synthetic) — they are
not detector-specific. The TrackNet inference path (src/tracknet.py) is the
active detector; the retired YOLO path lives in archive/."""

import logging
import statistics

import cv2
import numpy as np

log = logging.getLogger(__name__)


def net_image_y(homography, x_ft=10.0, net_y_ft=22.0):
    """Image-y (pixels) of the net line, from the image->court homography
    (calibrate.py output). Projects a court point on the net back into image
    space — the reference line the ball crosses."""
    h_inv = np.linalg.inv(np.array(homography, dtype=np.float64))
    pt = cv2.perspectiveTransform(
        np.array([[[x_ft, net_y_ft]]], dtype=np.float32), h_inv)
    return float(pt[0, 0, 1])


def ball_box_ok(box, max_dim_px, max_aspect=2.0):
    """True if a detection box is ball-shaped: not larger than max_dim_px on its
    long side (drops heads/bodies) and roughly square (drops elongated limbs).
    box = (x1, y1, x2, y2). max_dim_px must be calibrated to the ball's pixel
    size on the actual footage — see detect_ball's max_ball_px."""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    long, short = max(w, h), max(min(w, h), 1)
    return long <= max_dim_px and long / short <= max_aspect


def net_line_y(calib):
    """Net line image-y from a calibration dict. Prefers a hand-marked net
    (calib['net_image_points'], from calibrate.py) — the reliable source when
    the camera is fixed — and falls back to projecting it through the homography
    when no net was marked. Marking removes the derived-line error we hit on
    zoomed footage (EXPERIMENTS.md 2026-08-10)."""
    pts = calib.get("net_image_points")
    if pts:
        return sum(p[1] for p in pts) / len(pts)
    # The fallback is not merely less accurate, it is biased: the homography
    # maps the *ground plane*, so projecting court point (10, 22) returns where
    # the net's base meets the floor, not its tape — always too low (larger
    # image-y), by the net's height in pixels at that depth. On IMG_7652, whose
    # calibration has no marked net, that is ~130 px, and it silently corrupts
    # every crossing count computed from it (EXPERIMENTS.md 2026-08-16).
    log.warning(
        "calibration has no net_image_points — falling back to the "
        "homography-derived line, which gives the net's BASE, not its tape, "
        "and is systematically too low. Re-run calibrate.py (or "
        "calibrate_web.py) and click the two net-tape points before trusting "
        "any crossing count from this calibration.")
    return net_image_y(calib["homography"])


def crossing_times(track, net_y, band=0.0):
    """Timestamps where the ball crosses the net. track = [(time, y or None)].
    Same side logic as count_crossings, but returns the times so bursts can be
    located and clustered into rallies."""
    times = []
    last_side = None
    for t, y in track:
        if y is None:
            continue
        if y > net_y + band:
            side = "near"
        elif y < net_y - band:
            side = "far"
        else:
            continue
        if last_side is not None and side != last_side:
            times.append(t)
        last_side = side
    return times


def cluster_crossings(times, gap_sec, min_crossings=2):
    """Group dense bursts of crossing times into rally segments. Consecutive
    crossings within gap_sec belong to the same rally; a burst is kept only if
    it has >= min_crossings (an exchange, not a stray). Returns
    [{start, end, crossings}] — the auto-annotated rallies."""
    if not times:
        return []
    clusters = [[times[0]]]
    for t in times[1:]:
        if t - clusters[-1][-1] <= gap_sec:
            clusters[-1].append(t)
        else:
            clusters.append([t])
    return [{"start": c[0], "end": c[-1], "crossings": len(c)}
            for c in clusters if len(c) >= min_crossings]


def adaptive_gap_sec(times, min_crossings=2, *, base_gap=3.0, k=0.10,
                      gap_min=2.0, gap_max=5.0, ref_duration=10.0):
    """Derive a per-video gap_sec from the video's own observed rally length,
    instead of one global constant tuned on a single video (PIC-33).

    `gap_sec=3.0` (ADR-048) was tuned on IMG_7743, whose rallies average
    ~10.8s. A longer-rally video (competitive doubles, ~22s) contains lulls
    -- lobs, slow dink exchanges -- longer than 3.0s, so a fixed gap splits
    real rallies into fragments that get charged twice: once as a miss, once
    as a false positive. A shorter-rally video (singles, casual) needs the
    opposite: too loose a gap merges separate points. Neither a single fixed
    constant nor scaling gap_sec linearly with rally length works (both were
    tried and rejected -- see EXPERIMENTS.md, PIC-33): a `gap_sec=4.0` global
    bump wins on long-rally footage and loses badly on short-rally footage.

    This runs two passes instead. The first, at `base_gap`, is a coarse
    estimate of this video's own typical rally span (its cluster median
    duration) -- not a final answer, since long rallies are still fragmented
    at `base_gap`, but suggestive of whether this video runs long or short
    relative to `ref_duration` (~IMG_7743's own average, what `base_gap` was
    itself tuned against). The second pass nudges `base_gap` toward that
    estimate, scaled down by `k` so a single long rally doesn't overcorrect
    the whole video, and clamped to [gap_min, gap_max] so a pathological
    estimate can't blow the gap out to where dead time gets merged into rallies.

    Returns (gap_sec, segments) -- segments already clustered with the
    derived gap_sec, same schema as cluster_crossings.
    """
    pass1 = cluster_crossings(times, gap_sec=base_gap, min_crossings=min_crossings)
    if not pass1:
        return base_gap, pass1
    med_dur = statistics.median(c["end"] - c["start"] for c in pass1)
    gap_sec = min(gap_max, max(gap_min, base_gap + k * (med_dur - ref_duration)))
    return gap_sec, cluster_crossings(times, gap_sec=gap_sec, min_crossings=min_crossings)


def count_crossings(ball_ys, net_y, band=0.0):
    """Count net-crossings from a ball's per-frame image-y positions.

    ball_ys: list of image-y (pixels) or None where the ball wasn't detected.
    A frame's side is 'near' if y > net_y + band, 'far' if y < net_y - band, and
    ambiguous (skipped) within the band. A crossing is counted each time the
    definite side flips."""
    crossings = 0
    last_side = None
    for y in ball_ys:
        if y is None:
            continue
        if y > net_y + band:
            side = "near"
        elif y < net_y - band:
            side = "far"
        else:
            continue  # inside the band: too close to the net to call a side
        if last_side is not None and side != last_side:
            crossings += 1
        last_side = side
    return crossings
