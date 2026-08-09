from src.ball import count_crossings, net_image_y


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
