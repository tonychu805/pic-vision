import sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from track_associate import track_associate


def _line(n, x0=100.0, y0=300.0, vx=10.0, vy=0.0):
    return [(x0 + vx * i, y0 + vy * i) for i in range(n)]


def test_mid_confidence_on_path_beats_stray_dot():
    path = _line(8)
    frames = [[(x, y, 0.9)] for x, y in path[:5]]
    # frame 5: the true ball (0.45) on the path vs a 0.9 dot 120 px off the path
    frames.append([(path[5][0], path[5][1], 0.45), (path[5][0], path[5][1] + 120, 0.90)])
    ys = track_associate(frames, max_jump=150)
    assert ys[5] == path[5][1]


def test_confident_teleport_is_rejected():
    path = _line(5)
    frames = [[(x, y, 0.6)] for x, y in path]
    frames.append([(path[-1][0] + 600, path[-1][1], 0.95)])   # 600 px away
    ys = track_associate(frames, max_jump=150)
    assert ys[-1] is None


def test_gap_is_bridged_then_reset():
    path = _line(30)
    frames = [[(x, y, 0.8)] for x, y in path[:5]]
    frames += [[] for _ in range(3)]
    frames.append([(path[8][0], path[8][1], 0.8)])
    ys = track_associate(frames, max_jump=150, kalman=True, coast=3)
    assert ys[8] == path[8][1]                      # picked up after a 3-frame gap
    frames2 = [[(x, y, 0.8)] for x, y in path[:5]] + [[] for _ in range(15)]
    ys2 = track_associate(frames2, max_jump=150, reset_after=15, kalman=True, coast=3)
    assert all(v is None for v in ys2[5:])


def test_reversal_still_accepted():
    # ball going right then reversing (a hit): the last-position gate must still accept it
    pts = [(100 + 12 * i, 300.0) for i in range(6)] + [(100 + 12 * 5 - 12 * j, 300.0) for j in range(1, 4)]
    frames = [[(x, y, 0.7)] for x, y in pts]
    ys = track_associate(frames, max_jump=150, kalman=True, coast=3)
    assert all(v is not None for v in ys)
