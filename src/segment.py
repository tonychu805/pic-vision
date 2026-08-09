"""Turn a per-frame activity signal into rally segments (TECH_SPEC §6, ADR-026).

Signal-agnostic on purpose: the v0 (player) detector feeds it a player-activity
score; the v1 (ball) detector will feed it a ball-in-play / crossing signal.
It's a gap-tolerant, minimum-duration state machine — the same shape as the
prior art's ball-timeline segmenter."""


def segment(series, threshold, gap_sec, min_dur_sec):
    """Segment a per-frame signal into rally intervals.

    series: list of (time_sec, score), sorted by time. A frame is 'in play'
    when score > threshold. Consecutive in-play frames form a segment; low runs
    shorter than gap_sec are bridged (brief occlusions), so they don't split a
    rally; segments shorter than min_dur_sec are dropped. Returns a list of
    {'start', 'end', 'duration'} — the end is the last in-play frame, not where
    the gap is confirmed."""
    segs = []
    in_play = False
    start = last = None
    for t, score in series:
        if score > threshold:
            if not in_play:
                start, in_play = t, True
            last = t
        elif in_play and (t - last) > gap_sec:
            segs.append((start, last))
            in_play = False
    if in_play:
        segs.append((start, last))
    return [{"start": s, "end": e, "duration": e - s}
            for s, e in segs if e - s >= min_dur_sec]
