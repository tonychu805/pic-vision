"""Rally ranking for reel selection (TECH_SPEC §7.2).

Three signals, each derived from the detector's own proposed segment (never
a hand label -- at inference time there is no label to window against):

  duration              -- rewards a genuinely long rally, not just a loud one.
  peak_crossing_rate     -- the highest crossings/sec in any short sliding
                             window inside the segment, not the segment's
                             average rate. A flat average dilutes a real
                             burst with any slower stretch elsewhere in a
                             long rally (2026-08-23 held-out test on
                             brickwall-SEMI: the average-rate version
                             correlated *negatively* with duration, -0.53,
                             i.e. it structurally punished long rallies --
                             the opposite of what "favor long, exciting
                             rallies" wants). The peak version fixes that
                             (correlation +0.82 on the same test).
  n_spikes                -- count of frame-to-frame ball speeds in the top
                              decile observed anywhere in the source video,
                              inside the segment. Raw count, not a rate --
                              deliberately gives a longer rally more chances
                              to earn credit, consistent with favoring
                              duration rather than fighting it.

Raw crossing *count* (not rate, not peak, not duration-normalized at all) is
explicitly not used as a ranking signal -- DECISIONS.md ADR-054: it
structurally favors long kitchen-heavy dink exchanges over a real spread of
rally types, confirmed by the 2026-08-21 TrackNetV3 reel it produced.

Locked in 2026-08-23 after a live-tuning session on brickwall-SEMI landed on
this combination (operator: "this is genuinely great, lock in the formula
for now") -- not yet checked against the quality:1/quality:2 hand grades the
way duration/crossing-rate/top-5-velocity were validated earlier that day.
Revisit if that check turns up a problem.
"""
import math
import statistics


def frame_speeds(points):
    """points: [(t, x, y), ...] sorted by t (raw in-court ball detections,
    not the tracked/confirmed stream -- this only needs A and B positions
    close in time, not a continuous single-ball track).

    Returns [(t, px_per_sec), ...] -- one speed per consecutive pair, keyed
    on the later timestamp. Skips non-positive dt (duplicate timestamps)."""
    out = []
    for (t0, x0, y0), (t1, x1, y1) in zip(points, points[1:]):
        dt = t1 - t0
        if dt <= 0:
            continue
        dist = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        out.append((t1, dist / dt))
    return out


def spike_threshold(speeds, percentile=90):
    """The percentile (default: 90th) of frame-to-frame speeds, used as the
    cutoff for what counts as a velocity "spike" elsewhere in this module."""
    vals = [v for _, v in speeds]
    # Too few in-court detections to have a distribution (a covered camera,
    # lights off, an empty court): nothing counts as a spike.
    if len(vals) < 2:
        return float("inf")
    return statistics.quantiles(vals, n=100)[percentile - 1]


def peak_window(event_times, start, end, window=3.0, step=0.25):
    """Like peak_rate, but also returns *where* the busiest window is, not
    just how busy it was -- needed to cut a clip around just the burst
    rather than the whole segment it was found in.

    Returns (window_start, window_end, rate). Falls back to the whole
    [start, end) range if the segment is shorter than `window` (no room to
    slide)."""
    if end - start <= window:
        rate = len(event_times) / (end - start) if end > start else 0.0
        return start, end, rate
    best_start, best_rate = start, 0.0
    w = start
    while w + window <= end:
        count = sum(1 for t in event_times if w <= t <= w + window)
        rate = count / window
        if rate > best_rate:
            best_start, best_rate = w, rate
        w += step
    return best_start, best_start + window, best_rate


def peak_rate(event_times, start, end, window=3.0, step=0.25):
    """Highest count-per-second of `event_times` in any `window`-second
    sliding window fully inside [start, end]. Falls back to the flat
    average if the segment is shorter than `window` (no room to slide)."""
    _, _, rate = peak_window(event_times, start, end, window=window, step=step)
    return rate


def _minmax(vals):
    lo, hi = min(vals), max(vals)
    return [(v - lo) / (hi - lo) if hi > lo else 0.5 for v in vals]


def rank_segments(segments, crossing_times, speeds, threshold,
                   weights=(1 / 3, 1 / 3, 1 / 3), window=3.0, step=0.25):
    """Score and sort `segments` (each a dict with 'start'/'end', as returned
    by cluster_crossings) by the three signals above.

    weights: (w_duration, w_peak_crossing_rate, w_n_spikes), applied to each
    signal's min-max normalized value *across this segment set* -- ranking
    is relative to the candidates given, not an absolute scale.

    Returns a new list of segments (each with 'duration', 'peak_crossing_rate',
    'n_spikes', and 'score' added), sorted by score descending. Does not
    mutate the input."""
    if not segments:
        return []  # no candidates to rank -- a stretch with no rallies
    w_d, w_p, w_s = weights
    rows = []
    for s in segments:
        start, end = s["start"], s["end"]
        dur = end - start
        seg_crossings = [t for t in crossing_times if start <= t <= end]
        pcr = peak_rate(seg_crossings, start, end, window=window, step=step)
        nsp = sum(1 for t, v in speeds if start <= t <= end and v >= threshold)
        rows.append({**s, "duration": dur, "peak_crossing_rate": pcr, "n_spikes": nsp})

    d_n = _minmax([r["duration"] for r in rows])
    p_n = _minmax([r["peak_crossing_rate"] for r in rows])
    s_n = _minmax([r["n_spikes"] for r in rows])
    for r, a, b, c in zip(rows, d_n, p_n, s_n):
        r["score"] = w_d * a + w_p * b + w_s * c

    rows.sort(key=lambda r: -r["score"])
    return rows


# --- A fixed-scale 0-100 rally score (ADR-133, 2026-09-28) -------------------
#
# rank_segments above scales each signal min-max within the set it is given,
# so a session sent in 10-minute parts (ADR-127/128) is scored part by part:
# every part's best rally scores ~1 however dull it was, and scores from
# different parts can't be compared. This score is on a fixed scale, given
# once per rally, so any set of rallies (a whole session) can be sorted by it.
#
# Same three signals, fixed units, each levelling off so no single outlier
# dominates:
#   length  35 * (1 - exp(-seconds / 12))
#   pace    35 * min(1, peak crossings per second / 2.0)
#   hard    30 * n / (n + 12), n = ball-speed readings above 1.80 court
#           widths per second (pixel speed / the calibrated net's pixel width)
# Validated against the quality:1/quality:2 hand grades (EXPERIMENTS.md
# 2026-09-28: 18 of 33 highlight-worthy rallies into top 10s vs 15 for
# rank_segments) and its constants re-measured on PGC footage (same day:
# pace cap 2.67 -> 2.0; the hard-shot half-point 12 held). Comparable within
# one camera; NOT yet across cameras, since the hard-shot count still varies
# ~2x with camera angle.
SCORE_LENGTH_SEC = 12.0
SCORE_PACE_CAP = 2.0
SCORE_HARD_HALF = 12.0
SCORE_HARD_CUTOFF = 1.80  # court widths per second
SCORE_WEIGHTS = (35.0, 35.0, 30.0)


def rally_score(duration, peak_crossing_rate, n_hard):
    """0-100 for one rally, from its three signals (see above)."""
    w_len, w_pace, w_hard = SCORE_WEIGHTS
    length = 1 - math.exp(-max(duration, 0.0) / SCORE_LENGTH_SEC)
    pace = min(1.0, max(peak_crossing_rate, 0.0) / SCORE_PACE_CAP)
    hard = n_hard / (n_hard + SCORE_HARD_HALF) if n_hard > 0 else 0.0
    return round(w_len * length + w_pace * pace + w_hard * hard, 1)


def net_width_px(calib):
    """The calibrated net's width in image pixels, or None if the calibration
    doesn't have the net's two end points."""
    pts = calib.get("net_image_points") or []
    if len(pts) != 2:
        return None
    (x0, y0), (x1, y1) = pts
    width = math.hypot(x1 - x0, y1 - y0)
    return width if width > 0 else None


def score_segments(segments, crossing_times, speeds, net_px, window=3.0, step=0.25):
    """Each segment with 'duration', 'peak_crossing_rate', 'n_hard' and a
    0-100 'score' added, sorted best first. speeds are (t, px/sec) from
    frame_speeds. Without a net width (net_px None) nothing counts as a hard
    shot, and the score comes from length and pace alone. Doesn't mutate the
    input."""
    rows = []
    for s in segments:
        start, end = s["start"], s["end"]
        seg_crossings = [t for t in crossing_times if start <= t <= end]
        pcr = peak_rate(seg_crossings, start, end, window=window, step=step)
        n_hard = 0 if not net_px else sum(
            1 for t, v in speeds if start <= t <= end and v / net_px >= SCORE_HARD_CUTOFF)
        dur = end - start
        rows.append({**s, "duration": dur, "peak_crossing_rate": pcr, "n_hard": n_hard,
                     "score": rally_score(dur, pcr, n_hard)})
    rows.sort(key=lambda r: -r["score"])
    return rows
