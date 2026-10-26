"""src/badges.py: a badge goes only to a rally that clears its bar, each badge
to at most one rally, and no rally holds two."""
from src import badges
from src.badges import BARS, assess, award


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
