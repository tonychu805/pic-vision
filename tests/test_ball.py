from src.ball import (count_crossings, net_image_y, crossing_times,
                      cluster_crossings, ball_box_ok, net_line_y)


def test_net_line_y_prefers_marked_net():
    calib = {"net_image_points": [[100, 300], [500, 320]],
             "homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}
    assert net_line_y(calib) == 310.0            # average of the two marked y's


def test_net_line_y_falls_back_to_homography():
    calib = {"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}
    assert abs(net_line_y(calib) - 22.0) < 1e-4  # derived (identity -> court y=22)


def test_ball_box_ok_accepts_small_square():
    assert ball_box_ok((100, 100, 120, 122), max_dim_px=50)


def test_ball_box_ok_rejects_oversized():
    assert not ball_box_ok((100, 100, 180, 180), max_dim_px=50)   # head-sized blob


def test_ball_box_ok_rejects_elongated():
    # within the size cap but too tall to be a ball (a body/limb)
    assert not ball_box_ok((100, 100, 130, 170), max_dim_px=100, max_aspect=2.0)


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


def test_net_line_y_warns_when_no_net_marked(caplog):
    """The derived fallback returns the net's base, not its tape — always too
    low. It must say so rather than silently producing biased crossings."""
    import json, os, logging
    from src.ball import net_line_y
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calib",
                        "IMG_7652_calib.json")
    if not os.path.exists(path):
        return
    calib = json.load(open(path))
    assert "net_image_points" not in calib or not calib["net_image_points"]
    with caplog.at_level(logging.WARNING):
        net_line_y(calib)
    assert any("net_image_points" in r.message for r in caplog.records)
