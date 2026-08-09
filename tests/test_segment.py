from src.segment import segment


def test_segment_single_burst():
    series = [(round(t * 0.2, 1), 1.0 if 5 <= t <= 10 else 0.0) for t in range(0, 20)]
    segs = segment(series, threshold=0.5, gap_sec=0.5, min_dur_sec=0.0)
    assert len(segs) == 1
    assert abs(segs[0]["start"] - 1.0) < 1e-9 and abs(segs[0]["end"] - 2.0) < 1e-9


def test_segment_bridges_short_gap_splits_long():
    series = [(0.0, 1), (0.2, 1), (0.4, 0), (0.6, 1), (0.8, 1),   # 0.2 s gap = bridged
              (1.0, 0), (1.2, 0), (1.4, 0), (1.6, 0),              # long gap = split
              (1.8, 1), (2.0, 1)]
    segs = segment(series, threshold=0.5, gap_sec=0.5, min_dur_sec=0.0)
    assert len(segs) == 2
    assert abs(segs[0]["start"] - 0.0) < 1e-9 and abs(segs[0]["end"] - 0.8) < 1e-9
    assert abs(segs[1]["start"] - 1.8) < 1e-9 and abs(segs[1]["end"] - 2.0) < 1e-9


def test_segment_drops_short_segments():
    series = [(0.0, 1), (0.2, 1),                                  # 0.2 s burst -> dropped
              (1.0, 0), (1.2, 0),
              (2.0, 1), (2.2, 1), (2.4, 1), (2.6, 1)]               # 0.6 s burst -> kept
    segs = segment(series, threshold=0.5, gap_sec=0.5, min_dur_sec=0.5)
    assert len(segs) == 1
    assert abs(segs[0]["start"] - 2.0) < 1e-9


def test_segment_empty():
    assert segment([], threshold=0.5, gap_sec=0.5, min_dur_sec=0.5) == []
