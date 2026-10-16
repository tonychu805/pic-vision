"""Footage that new evaluation samples must leave out (ADR-155, 2026-10-17).

Any new script that builds a test sample, labelling chunk or tuning pool from PGC footage filters its
sessions through usable(). Past experiments keep the footage they were registered with.
"""
EXCLUDED_CAMERAS = {
    "de3d1953": "Tapo C200 at PGC court 1: drops frames, no shutter control, and 22 of the 43 fresh clips "
                "judged from it were not rallies (ADR-155)",
}


def usable(name):
    """False when a session name, path or clip id comes from an excluded camera."""
    return not any(cam in str(name) for cam in EXCLUDED_CAMERAS)
