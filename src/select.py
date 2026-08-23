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
    return statistics.quantiles(vals, n=100)[percentile - 1]


def peak_rate(event_times, start, end, window=3.0, step=0.25):
    """Highest count-per-second of `event_times` in any `window`-second
    sliding window fully inside [start, end]. Falls back to the flat
    average if the segment is shorter than `window` (no room to slide)."""
    if end - start <= window:
        return len(event_times) / (end - start) if end > start else 0.0
    best = 0.0
    w = start
    while w + window <= end:
        count = sum(1 for t in event_times if w <= t <= w + window)
        best = max(best, count / window)
        w += step
    return best


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
