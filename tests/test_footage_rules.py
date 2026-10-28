import sys

sys.path.insert(0, "scripts")
from footage_rules import usable


def test_original_tapo_session_excluded():
    # ADR-155: the first Tapo court-1 recording.
    assert not usable("cache/scale/de3d1953_2026-09-25T08-24-02_session-001.csv")
    assert not usable("pgc-fieldtest-sept2026/de3d1953-6fbd-4633-8c34-d941a5613127/2026-09-25T07-21-01/session-000.mkv")


def test_tapo_court1_frame_drop_sessions_excluded():
    # ADR-158: the same Tapo camera's other court-1 recordings (~1/3 frozen frames).
    for pre in ("499ed4b8", "52f4de24", "72852da9"):
        assert not usable(f"cache/pgc_fieldtest/{pre}-0000-0000-0000-000000000000.mp4"), pre
        assert not usable(f"cache/serve_review/near/001_near_{pre}_93s.mp4"), pre


def test_drill_session_excluded():
    # ADR-158: coaching/feeding drill session -- no real serves.
    assert not usable("cache/pgc_fieldtest/c6a9136a-1111-2222-3333-444444444444.mp4")
    assert not usable("cache/serve_review/near/024_near_c6a9136a_16s.mp4")


def test_games_sessions_stay_usable():
    # Clean games cameras (0% frame drop, real play) must pass.
    for pre in ("7358ef3f", "3e1caf84", "a96cbae3", "365c798c", "1974ac52"):
        assert usable(f"cache/pgc_fieldtest/{pre}-0000-0000-0000-000000000000.mp4"), pre
