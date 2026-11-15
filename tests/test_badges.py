"""src/badges.py: a badge goes only to a rally that clears its bar, each badge
to at most one rally per session, and no rally holds two."""
import json

from src import badges
from src.badges import BARS, assess, award, decide, measure


def _player(x_ft, y_ft, box, wrist, conf=0.9):
    kp = [[0.0, 0.0, 0.0]] * 17
    kp = [list(k) for k in kp]
    kp[9] = [wrist[0], wrist[1], conf]
    kp[10] = [wrist[0], wrist[1], conf]
    return {"box": list(box), "court": [x_ft, y_ft], "kp": kp}


def _rally_poses(start_f, end_f, swing_at=None, swing_px=0.0):
    """Two players at the baselines with ordinary wrist movement (+-3 px a
    frame, so the session has a typical swing), plus -- if `swing_at` -- one
    big wrist move of `swing_px` a frame on the near player for 2 frames."""
    P = {}
    for f in range(start_f, end_f + 1):
        jitter = 3.0 if f % 2 else -3.0
        big = swing_px * min(max(f - swing_at, 0), 2) if swing_at is not None else 0.0
        near = _player(10, 2, (500, 400, 560, 600), (530 + jitter + big, 450))
        far = _player(10, 42, (600, 100, 630, 160), (615 - jitter, 120))
        P[str(f)] = [near, far]
    return P


def test_award_one_badge_per_rally_and_one_rally_per_badge():
    cands = [
        {"badge": "Killer Shot", "rally": 0, "margin": 2.0},
        {"badge": "Hardest Swing", "rally": 0, "margin": 1.5},   # rally 0 already holds Killer Shot
        {"badge": "Hardest Swing", "rally": 1, "margin": 1.2},
        {"badge": "Killer Shot", "rally": 2, "margin": 1.1},     # Killer Shot already given
    ]
    got = award(cands)
    assert {b: c["rally"] for b, c in got.items()} == {"Killer Shot": 0, "Hardest Swing": 1}


def test_no_candidates_no_badges():
    assert award([]) == {}


def test_a_rally_below_every_bar_gets_no_badge():
    # Ordinary play only: wrists barely move, nobody at the kitchens.
    P = _rally_poses(0, 300, swing_at=150, swing_px=2.0)
    segs = [{"start": 1.0, "end": 9.0}]
    result = assess(P, segs, 1280, 720)
    assert result["awarded"] == {}


def test_every_candidate_clears_its_bar():
    # Whatever assess() proposes must be at or past its bar (margin >= 1);
    # award() only ever picks from those candidates.
    P = _rally_poses(0, 300, swing_at=270, swing_px=150.0)
    P.update({k: v for k, v in _rally_poses(300, 600, swing_at=450, swing_px=2.0).items()})
    segs = [{"start": 1.0, "end": 9.2}, {"start": 11.0, "end": 19.0}]
    result = assess(P, segs, 1280, 720)
    assert result["candidates"], "the big late swing must produce at least one candidate"
    assert all(c["margin"] >= 1.0 for c in result["candidates"])
    assert {c["rally"] for c in result["candidates"]} == {0}, "the ordinary rally clears no bar"
    for b, c in result["awarded"].items():
        assert c in result["candidates"]
        assert c["value"] >= (BARS[b] if b != "Quick Hands" else BARS["Quick Hands"])


def test_spectators_off_court_are_ignored():
    P = _rally_poses(0, 300)
    for f in P:
        P[f].append(_player(40, 15, (1100, 300, 1140, 380), (1120, 320)))   # beside the court, level with a kitchen
    assert all(len([p for p in v if badges._player(p)]) == 2 for v in P.values())


def test_same_rally_number_in_two_parts_are_different_rallies():
    cands = [
        {"badge": "Killer Shot", "part": 0, "rally": 3, "margin": 2.0},
        {"badge": "Kitchen War", "part": 1, "rally": 3, "margin": 1.5, "value": 0.75},
    ]
    assert {b: (c["part"], c["rally"]) for b, c in award(cands).items()} == {"Killer Shot": (0, 3), "Kitchen War": (1, 3)}


def test_measure_is_json_and_decides_like_assess():
    P = _rally_poses(0, 300, swing_at=270, swing_px=150.0)
    segs = [{"start": 1.0, "end": 9.2}]
    m = json.loads(json.dumps(measure(P, segs, 1280, 720)))      # what the pod sends survives JSON
    assert decide([m])["awarded"].keys() == assess(P, segs, 1280, 720)["awarded"].keys()


def test_the_bar_is_the_sessions_typical_swing_not_the_parts():
    # One swing at 4x a slow part's typical clears Killer Shot (3.5x) within
    # that part, but the session's other part swings twice as fast, so
    # against the whole session's typical swing it is ordinary.
    def part(speed, late):
        swings = [[speed, 0.4 * i, 3.0] for i in range(20)] + [[late, 18.5, 3.0]]   # ordinary play before the rally
        return {"swings": swings, "rallies": [{"start": 10.0, "end": 19.0, "share": 0.0, "serve": None}]}
    slow = part(1.0, 4.0 * badges.ZONE_P90[0] / badges.ALL_P90)
    assert "Killer Shot" in decide([slow])["awarded"]
    session = decide([slow, part(2.0, 2.0)])
    assert session["typical_swing"] == 2.0
    assert "Killer Shot" not in session["awarded"]


def test_exchanges_count_only_crossings_while_both_teams_are_at_the_kitchen():
    P = _rally_poses(0, 300)
    for f in range(30, 241):                                      # 1.0 .. 8.0 s: a kitchen standoff
        P[str(f)] = [_player(10, 15, (500, 400, 560, 600), (530, 450)), _player(10, 29, (600, 100, 630, 160), (615, 120))]
    rally = measure(P, [{"start": 1.0, "end": 9.0}], 1280, 720, crossings=[2.0, 3.0, 8.5, 9.5])["rallies"][0]
    assert rally["exchanges"] == 2                                # 8.5 is after the standoff, 9.5 after the rally
    assert rally["kitchen_s"] == round(211 / 30, 3)
    assert "exchanges" not in measure(P, [{"start": 1.0, "end": 9.0}], 1280, 720)["rallies"][0]


def _kitchen_rally(start, share, exchanges, kitchen_s):
    return {"start": start, "end": start + 20, "share": share, "serve": None, "exchanges": exchanges, "kitchen_s": kitchen_s}


def test_kitchen_war_goes_to_the_longest_fastest_battle_not_the_highest_share():
    swings = [[1.0, 0.4 * i, 3.0] for i in range(20)]
    calm = _kitchen_rally(10.0, 0.9, 15, 16.0)                    # mostly at the kitchen, slow
    war = _kitchen_rally(40.0, 0.65, 31, 20.0)                    # less of the rally, twice the exchanges
    assert decide([{"swings": swings, "rallies": [calm, war]}])["awarded"]["Kitchen War"]["start"] == 40.0


def test_kitchen_war_falls_back_to_share_for_parts_measured_without_crossings():
    swings = [[1.0, 0.4 * i, 3.0] for i in range(20)]
    a, b = ({"start": s, "end": s + 20, "share": sh, "serve": None} for s, sh in ((10.0, 0.9), (40.0, 0.65)))
    assert decide([{"swings": swings, "rallies": [a, b]}])["awarded"]["Kitchen War"]["start"] == 10.0


def test_kitchen_war_takes_its_next_best_rally_when_its_best_holds_another_badge():
    cands = [
        {"badge": "Hardest Swing", "rally": 1, "margin": 3.0, "value": 15.0},
        {"badge": "Kitchen War", "rally": 0, "margin": 1.8, "value": 14.0},
        {"badge": "Kitchen War", "rally": 1, "margin": 1.3, "value": 48.0},
        {"badge": "Kitchen War", "rally": 2, "margin": 1.1, "value": 30.0},
    ]
    assert {b: c["rally"] for b, c in award(cands).items()} == {"Hardest Swing": 1, "Kitchen War": 2}
