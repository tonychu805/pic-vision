import sys

sys.path.insert(0, "scripts")
from footage_rules import usable


def test_tapo_sessions_are_excluded():
    assert not usable("cache/scale/de3d1953_2026-09-25T08-24-02_session-001.csv")
    assert not usable("pgc-fieldtest-sept2026/de3d1953-6fbd-4633-8c34-d941a5613127/2026-09-25T07-21-01/session-000.mkv")


def test_other_cameras_stay_usable():
    assert usable("cache/scale/eda301d9_2026-09-26T07-00-34_session-000.csv")
    assert usable("pgc-fieldtest-sept2026/c199a97c-c51f-4620-8523-b2837f48c1a7/2026-09-26T05-38-15/session-002.mkv")
