from src.pipeline import rally_segments_from_candidates


def test_smooth_rally_is_one_segment():
    # ball alternates sides smoothly (each step under max_jump) -> one rally
    cands = [
        (0.0, [(100, 150, 0.9)]),   # near
        (0.1, [(100, 50, 0.9)]),    # far  -> crossing
        (0.2, [(100, 150, 0.9)]),   # near -> crossing
        (0.3, [(100, 50, 0.9)]),    # far  -> crossing
    ]
    segs = rally_segments_from_candidates(
        cands, net_y=100, max_jump=120, gap_sec=1.0, band=0, min_crossings=2)
    assert len(segs) == 1
    assert segs[0]["crossings"] == 3
    assert segs[0]["start"] == 0.1 and segs[0]["end"] == 0.3


def test_out_of_play_balls_produce_no_phantom_rally():
    # Two stationary balls on opposite courts. "Best per frame" would hop between
    # them (near, far, near) = 2 phantom crossings. Following ONE ball and
    # rejecting the teleport yields zero crossings -> no rally. This is the
    # 659-666s dead-time mechanism at unit scale.
    cands = [
        (0.0, [(100, 150, 0.9)]),   # ball A, near side
        (0.1, [(900, 50, 0.9)]),    # ball B, far side (teleport -> rejected)
        (0.2, [(100, 150, 0.9)]),   # ball A again
    ]
    segs = rally_segments_from_candidates(
        cands, net_y=100, max_jump=120, gap_sec=1.0, band=0, min_crossings=2)
    assert segs == []
