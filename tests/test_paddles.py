import json
import os

import src.paddles as paddles_mod
from src.paddles import filter_paddle_boxes, filter_paddle_boxes_by_on_court_player


def test_filter_paddle_boxes_drops_whole_body_boxes(monkeypatch):
    # court_wedge itself isn't under test here -- stub it to accept everything
    # so only the area filter is exercised.
    monkeypatch.setattr(paddles_mod, "court_wedge", lambda calib, **kw: (lambda x, y: True))
    small = (100, 100, 110, 130)   # 300px^2 -- paddle-scale
    big = (0, 0, 400, 400)          # 160000px^2 -- whole body
    kept = filter_paddle_boxes([small, big], calib={}, area_max=15000.0)
    assert kept == [small]


def test_filter_paddle_boxes_drops_off_court_boxes(monkeypatch):
    calls = []

    def fake_wedge(calib, **kw):
        def inside(x, y):
            calls.append((x, y))
            return x < 500   # arbitrary in-court region for the test
        return inside

    monkeypatch.setattr(paddles_mod, "court_wedge", fake_wedge)
    in_court_box = (100, 100, 120, 130)     # center x=110 -- inside
    off_court_box = (600, 100, 620, 130)    # center x=610 -- outside
    kept = filter_paddle_boxes([in_court_box, off_court_box], calib={})
    assert kept == [in_court_box]
    assert (110, 115) in calls
    assert (610, 115) in calls


def test_filter_paddle_boxes_passes_wedge_kwargs_through(monkeypatch):
    captured = {}

    def fake_wedge(calib, **kw):
        captured.update(kw)
        return lambda x, y: True

    monkeypatch.setattr(paddles_mod, "court_wedge", fake_wedge)
    filter_paddle_boxes([(0, 0, 10, 10)], calib={}, margin_px=42.0)
    assert captured == {"margin_px": 42.0}


def test_filter_paddle_boxes_on_real_calibration_keeps_real_paddle():
    # A real paddle held near the net (~y=550, inside the court) must survive
    # court_wedge's gate regardless of margin_px.
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "calib", "brickwall_30fps_calib.json")
    if not os.path.exists(path):
        return                      # calibration not present in this checkout
    calib = json.load(open(path))
    real_paddle_near_net = (500, 540, 560, 600)
    kept = filter_paddle_boxes([real_paddle_near_net], calib)
    assert kept == [real_paddle_near_net]


def test_filter_paddle_boxes_shipped_margin_does_not_exclude_balcony_hotspot():
    # Documents a real, measured limitation (EXPERIMENTS.md, 2026-08-20): with
    # court_wedge's shipped ball-tuned margin_px=160, the balcony
    # maintenance-pole false-positive spot is NOT excluded -- the pad is wide
    # enough to cover it at that image depth. A tighter margin_px is required
    # for paddle filtering; this is not yet re-derived (open follow-up).
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "calib", "brickwall_30fps_calib.json")
    if not os.path.exists(path):
        return
    calib = json.load(open(path))
    balcony_pole = (280, 80, 320, 190)
    assert filter_paddle_boxes([balcony_pole], calib) == [balcony_pole]
    # A materially tighter margin does exclude it.
    assert filter_paddle_boxes([balcony_pole], calib, margin_px=60.0) == []


# Identity homography: image pixels equal court feet 1:1, so a foot point's
# "court coordinates" are just its own (x, y) -- makes on/off-court easy to
# construct directly without a real calibration.
IDENTITY_CALIB = {"homography": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]}


def test_on_court_player_filter_keeps_paddle_near_on_court_player():
    player_on_court = (0, 0, 20, 20)     # foot point (10, 20) -- within the court
    paddle = (5, 5, 15, 15)               # center (10, 10), overlaps the player box
    kept = filter_paddle_boxes_by_on_court_player([paddle], [player_on_court], IDENTITY_CALIB)
    assert kept == [paddle]


def test_on_court_player_filter_drops_paddle_near_off_court_player():
    # Same pairing distance as the case above, but this player's foot point
    # is nowhere near the court -- the front-desk-bystander case: a real
    # person, holding something real, who just isn't playing.
    player_off_court = (0, 980, 20, 1000)   # foot point (10, 1000) -- way off-court
    paddle = (5, 985, 15, 995)
    kept = filter_paddle_boxes_by_on_court_player([paddle], [player_off_court], IDENTITY_CALIB)
    assert kept == []


def test_on_court_player_filter_drops_paddle_with_no_nearby_player():
    player_on_court = (0, 0, 20, 20)
    paddle_far_away = (900, 900, 910, 910)
    kept = filter_paddle_boxes_by_on_court_player(
        [paddle_far_away], [player_on_court], IDENTITY_CALIB, max_dist_px=50.0)
    assert kept == []


def test_on_court_player_filter_passes_on_court_kwargs_through():
    # A player just past the strict 44ft baseline is off-court by default,
    # but on-court once y_margin is widened to cover them.
    player_just_past_baseline = (0, 45, 20, 45)   # foot point (10, 45)
    paddle = (5, 40, 15, 44)
    assert filter_paddle_boxes_by_on_court_player(
        [paddle], [player_just_past_baseline], IDENTITY_CALIB) == [paddle]
    assert filter_paddle_boxes_by_on_court_player(
        [paddle], [player_just_past_baseline], IDENTITY_CALIB, y_margin=0.5) == []
