from src.select import frame_speeds, spike_threshold, peak_rate, peak_window, rank_segments


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


def test_peak_window_falls_back_to_full_range_for_short_segment():
    w_start, w_end, rate = peak_window([1.0, 1.5], start=1.0, end=2.0, window=3.0)
    assert (w_start, w_end, rate) == (1.0, 2.0, 2 / 1.0)


def test_peak_window_locates_the_burst_a_flat_average_would_dilute():
    # same fixture as test_peak_rate_finds_a_burst_a_flat_average_would_dilute --
    # the burst is in the first 2s, so the located window should start near 0.
    events = [0.0, 0.4, 0.8, 1.2, 1.6, 2.0]
    w_start, w_end, rate = peak_window(events, start=0.0, end=20.0, window=3.0, step=0.25)
    assert rate == 2.0
    assert w_end - w_start == 3.0
    assert 0.0 <= w_start <= 0.25  # window slides in 0.25s steps from start=0.0


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


def test_rank_segments_with_no_candidates_is_an_empty_ranking():
    # A stretch with no rallies (a break, a warm-up) -- common once a session
    # is sent in 10-minute parts. Used to crash the whole job (min() of an
    # empty list), 2026-09-23 auto-split rehearsal.
    assert rank_segments([], [1.0, 2.0], [(1.0, 5.0), (2.0, 6.0)], 5.5) == []


def test_spike_threshold_with_too_few_detections_counts_nothing_as_a_spike():
    assert spike_threshold([]) == float("inf")
    assert spike_threshold([(1.0, 40.0)]) == float("inf")


# --- the fixed-scale 0-100 rally score (ADR-133) ---

from src.select import net_width_px, rally_score, score_segments  # noqa: E402


def test_rally_score_matches_the_formula_and_stays_within_0_100():
    assert rally_score(0.0, 0.0, 0) == 0.0
    # 12 s -> 35*(1-1/e) = 22.1; pace at the cap -> 35; 12 hard -> 15.
    assert rally_score(12.0, 2.0, 12) == 72.1
    assert rally_score(600.0, 50.0, 10_000) <= 100.0
    assert rally_score(600.0, 50.0, 10_000) > 99.0


def test_rally_score_rises_with_each_signal():
    base = rally_score(8.0, 1.0, 6)
    assert rally_score(16.0, 1.0, 6) > base
    assert rally_score(8.0, 1.5, 6) > base
    assert rally_score(8.0, 1.0, 12) > base


def test_net_width_px_from_calibration():
    assert net_width_px({"net_image_points": [[100, 300], [400, 300]]}) == 300.0
    assert net_width_px({}) is None
    assert net_width_px({"net_image_points": [[5, 5], [5, 5]]}) is None


def test_score_segments_is_fixed_scale_not_relative_to_the_set():
    # The same rally scores the same alone or next to a much better one --
    # the property rank_segments lacks and the share page relies on.
    seg = {"start": 0.0, "end": 10.0}
    crossings = [1.0, 2.0, 3.0, 4.0, 5.0]
    speeds = [(t / 10, 600.0) for t in range(0, 600)]  # 600 px/s over a 300 px net = 2 cw/s
    alone = score_segments([seg], crossings, speeds, 300.0)[0]["score"]
    big = {"start": 20.0, "end": 60.0}
    many = [20.0 + i * 0.3 for i in range(100)]
    together = score_segments([seg, big], crossings + many, speeds, 300.0)
    assert together[0]["start"] == 20.0  # better one first
    assert [r for r in together if r["start"] == 0.0][0]["score"] == alone


def test_score_segments_counts_hard_shots_in_court_widths_per_second():
    seg = {"start": 0.0, "end": 10.0}
    slow = [(t / 10, 300.0) for t in range(0, 100)]  # 1 cw/s: below the 1.80 cut-off
    fast = [(t / 10, 900.0) for t in range(0, 100)]  # 3 cw/s
    assert score_segments([seg], [], slow, 300.0)[0]["n_hard"] == 0
    assert score_segments([seg], [], fast, 300.0)[0]["n_hard"] == 100
    assert score_segments([seg], [], fast, None)[0]["n_hard"] == 0  # no net: length+pace only
