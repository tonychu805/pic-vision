import json

from src import framing

W, H = 1920, 1080
CW = framing.crop_width(W, H)   # 608


def test_crop_width_is_full_height_9_16_and_even():
    assert CW == 608
    assert framing.crop_width(1280, 720) == 404
    assert framing.crop_width(400, 1080) == 400        # never wider than the frame


def test_ball_only_follows_the_ball_and_stays_in_frame():
    xs = [1800.0] * 30 + [None] * 30 + [100.0] * 30
    c = framing.smooth(framing.targets(xs, [None] * 90, W, CW, use_players=False), 30, W, CW)
    assert c.min() >= CW / 2 and c.max() <= W - CW / 2
    assert c[0] == W - CW / 2                           # pinned to the right edge near the ball
    assert c[-1] < c[0]                                 # and moved left with it


def test_window_shifts_to_show_a_player_without_losing_the_ball():
    ball = 900.0
    player = [1100, 400, 1180, 800]                     # right of the ball, reachable
    c = framing._most_players(ball, [player], W, CW)
    assert c - CW / 2 <= player[0] and player[2] <= c + CW / 2
    assert c - CW / 2 + 0.1 * CW <= ball <= c + CW / 2 - 0.1 * CW


def test_player_out_of_reach_never_costs_the_ball():
    ball = 900.0
    far = [1700, 400, 1780, 800]
    c = framing._most_players(ball, [far], W, CW)
    assert c - CW / 2 <= ball <= c + CW / 2


def test_more_players_win_over_one():
    ball = 960.0
    left_pair = [[560, 400, 620, 700], [640, 400, 700, 700]]
    right_one = [[1250, 400, 1310, 700]]
    c = framing._most_players(ball, left_pair + right_one, W, CW)
    assert c < ball                                     # leans toward the pair


def test_no_players_means_ball_centred():
    xs = [960.0] * 10
    assert list(framing.targets(xs, [[]] * 10, W, CW)) == xs


def test_focus_holds_on_the_badge_hitter():
    n = 90
    near = {"box": [200, 600, 320, 1000], "court": [3.0, 2.0]}
    far = {"box": [1500, 100, 1550, 220], "court": [17.0, 40.0]}
    people = [[near, far]] * n
    t = framing.targets([1500.0] * n, people, W, CW, use_players=False, focus=[(1.5, 2.0)], fps=30)
    assert t[45] == 260.0                               # the near player's centre at the shot
    assert t[0] == 1500.0                               # ball elsewhere


def test_path_is_resolution_independent_and_serialisable():
    xs = [float(x) for x in range(300, 1500, 4)]        # 300 frames panning right
    path = framing.framing_path(xs, [None] * len(xs), W, H, 30, use_players=False)
    assert path["fps"] == framing.PATH_FPS and len(path["x"]) == 50
    json.dumps(path)
    t = 5.0
    a = framing.window_left(path, t, 1920, 1080) / 1920
    b = framing.window_left(path, t, 3840, 2160) / 3840
    assert abs(a - b) < 0.001


def test_centre_at_interpolates_and_holds_past_the_end():
    p = {"fps": 10.0, "x": [0.2, 0.4]}
    assert abs(framing.centre_at(p, 0.05) - 0.3) < 1e-9
    assert framing.centre_at(p, 9.0) == 0.4
    assert framing.centre_at({"fps": 10.0, "x": []}, 1.0) == 0.5


def test_clip_window_slices_the_clip_and_pads_past_the_end():
    xs = [float(i) for i in range(100)]
    players = {"31": [{"box": [0, 0, 1, 1]}]}
    got, people = framing.clip_window(xs, players, 1.0, 2.0, fps=30)
    assert got[0] == 30.0 and len(got) == 30 and people[1] == players["31"] and people[0] is None
    got, _ = framing.clip_window(xs, {}, 3.0, 4.0, fps=30)
    assert got[:10] == [float(i) for i in range(90, 100)] and got[10:] == [None] * 20


def test_window_frames_the_server_until_the_serve_crosses():
    n = 60
    server = {"box": [100, 500, 220, 1000], "court": [5.0, -2.0]}     # near baseline, far left
    receiver = {"box": [1650, 100, 1700, 220], "court": [15.0, 44.0]}
    people = [[server, receiver]] * n
    xs = [None] * 30 + [1675.0] * 30                                 # ball first seen at the receiver
    serve = {"until": 30, "court": [5.0, -2.0]}
    t = framing.targets(xs, people, W, CW, use_players=False, serve=serve)
    assert t[0] == 160.0 and t[29] == 160.0                          # on the server
    assert t[30] == 1675.0                                           # then the ball
    t = framing.targets(xs, people, W, CW, use_players=False)
    assert t[0] == 1675.0                                            # without: waits at the receiver


def test_clip_framing_without_a_serve_falls_back_to_ball_and_players():
    xs = [960.0] * 90
    clip = {"start": 0.0, "end": 3.0, "rally_start": 1.5}
    a = framing.clip_framing(xs, {}, clip, W, H)
    b = framing.clip_framing(xs, {}, {"start": 0.0, "end": 3.0}, W, H)
    assert a == b
