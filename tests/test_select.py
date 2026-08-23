from src.select import frame_speeds, spike_threshold, peak_rate, rank_segments


def test_frame_speeds_basic():
    points = [(0.0, 0.0, 0.0), (1.0, 3.0, 4.0), (2.0, 3.0, 4.0)]  # 5px in 1s, then 0px
    assert frame_speeds(points) == [(1.0, 5.0), (2.0, 0.0)]


def test_frame_speeds_skips_nonpositive_dt():
    points = [(1.0, 0.0, 0.0), (1.0, 10.0, 0.0), (2.0, 20.0, 0.0)]  # duplicate timestamp
    speeds = frame_speeds(points)
    assert len(speeds) == 1
    assert speeds[0] == (2.0, 10.0)


def test_spike_threshold_is_a_percentile():
    speeds = [(float(i), float(i)) for i in range(1, 101)]  # values 1..100
    # statistics.quantiles' default (exclusive) interpolation, not a naive index
    assert spike_threshold(speeds, percentile=90) == 90.9


def test_peak_rate_falls_back_to_average_for_short_segment():
    # segment shorter than the window -- no room to slide, just the flat rate
    assert peak_rate([1.0, 1.5], start=1.0, end=2.0, window=3.0) == 2 / 1.0


def test_peak_rate_finds_a_burst_a_flat_average_would_dilute():
    # 6 events packed into the first 2s of a 20s segment; nothing after.
    # Flat average over 20s = 0.3/s; the peak 3s window should find the burst.
    events = [0.0, 0.4, 0.8, 1.2, 1.6, 2.0]
    flat_avg = len(events) / 20.0
    pk = peak_rate(events, start=0.0, end=20.0, window=3.0, step=0.25)
    assert pk > flat_avg
    assert pk == 2.0  # 6 events / 3.0s window


def test_rank_segments_favors_duration_when_other_signals_tie():
    # Two segments with identical crossing/speed activity but different length
    # -- duration is the only thing that can tell them apart.
    segments = [
        {"start": 0.0, "end": 5.0, "crossings": 6},
        {"start": 100.0, "end": 115.0, "crossings": 6},  # same crossing count, longer
    ]
    crossing_times = [0.5, 1.5, 2.5, 100.5, 105.5, 110.5]
    speeds = []  # no velocity spikes either way
    ranked = rank_segments(segments, crossing_times, speeds, threshold=1e9,
                            weights=(1.0, 0.0, 0.0))
    assert ranked[0]["start"] == 100.0  # the longer one wins when only duration counts


def test_rank_segments_sorted_descending_by_score():
    segments = [{"start": 0.0, "end": 10.0, "crossings": 2},
                {"start": 20.0, "end": 30.0, "crossings": 8}]
    crossing_times = [1.0, 5.0, 21.0, 22.0, 23.0, 24.0, 25.0, 26.0, 27.0, 28.0]
    speeds = []
    ranked = rank_segments(segments, crossing_times, speeds, threshold=1e9)
    scores = [r["score"] for r in ranked]
    assert scores == sorted(scores, reverse=True)


def test_rank_segments_does_not_mutate_input():
    segments = [{"start": 0.0, "end": 5.0, "crossings": 2}]
    original = dict(segments[0])
    rank_segments(segments, [1.0], [], threshold=1e9)
    assert segments[0] == original
