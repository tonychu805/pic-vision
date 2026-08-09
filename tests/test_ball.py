from src.ball import count_crossings, net_image_y, crossing_times, cluster_crossings


def test_crossing_times_returns_timestamps():
    # net 100, band 10 -> near y>110, far y<90
    track = [(0.0, 150), (0.1, 50), (0.2, 150)]   # near, far, near -> crossings at 0.1, 0.2
    assert crossing_times(track, net_y=100, band=10) == [0.1, 0.2]


def test_cluster_crossings_groups_dense_drops_sparse():
    # 4 crossings within 1.5s = one rally; a lone crossing at 30s is dropped
    times = [10.0, 10.5, 11.0, 11.5, 30.0]
    segs = cluster_crossings(times, gap_sec=2.0, min_crossings=2)
    assert len(segs) == 1
    assert segs[0]["start"] == 10.0 and segs[0]["end"] == 11.5 and segs[0]["crossings"] == 4


def test_cluster_crossings_two_separate_rallies():
    times = [5.0, 5.5, 6.0, 20.0, 20.5, 21.0]   # two dense bursts, gap > 2s
    assert len(cluster_crossings(times, gap_sec=2.0, min_crossings=2)) == 2


def test_cluster_crossings_empty():
    assert cluster_crossings([], gap_sec=2.0, min_crossings=2) == []


def test_net_image_y_identity_homography():
    identity = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]   # image==court -> net at court-y 22
    assert abs(net_image_y(identity) - 22.0) < 1e-4


def test_count_crossings_back_and_forth():
    # net at image-y 100, band 10 -> near = y>110, far = y<90
    ys = [150, 50, 150, 50]        # near, far, near, far -> 3 crossings
    assert count_crossings(ys, net_y=100, band=10) == 3


def test_count_crossings_skips_missing_and_ambiguous():
    ys = [150, None, 105, 50, None, 150]   # near, (skip), (ambiguous), far, (skip), near
    assert count_crossings(ys, net_y=100, band=10) == 2


def test_count_crossings_same_side_is_zero():
    assert count_crossings([150, 140, 160, 155], net_y=100, band=10) == 0


def test_count_crossings_empty():
    assert count_crossings([], net_y=100, band=10) == 0
