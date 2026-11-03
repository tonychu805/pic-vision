"""Footage that new evaluation / labelling / tuning samples must leave out
(ADR-155, consolidated and extended by ADR-158, 2026-10-23).

Any script that builds a test sample, labelling chunk, serve-candidate set or
tuning pool from PGC footage filters its sessions through usable(). Past
experiments keep the footage they were registered with.

Three independent reasons a session is excluded, each measurable:
  - EXCLUDED_CAMERAS / EXCLUDED_TAPO: the Tapo C200 at PGC court 1 drops ~1/3 of
    its frames (frozen/duplicated to hold 30fps CFR), so the ball/serve is
    unwatchable. ADR-155 listed only de3d1953; a frame-drop audit (mpdecimate on
    a 30s mid-slice) found ALL three "PGC - court 1" recordings in the
    Sept-2026 field test have the same ~32-33% frozen-frame signature -- they
    are the same camera, different recordings. Every other PGC camera measures
    0%. (ADR-158)
  - EXCLUDED_DRILL: a coaching / ball-feeding drill session has no real serves
    (balls scattered, a coach feeding from a cart). c6a9136a was confirmed by
    eye and by Jev (11/13 of its clips scored practice/not_play, mean real
    0.12 vs >0.5 for games sessions). (ADR-158)

usable() is a pure string match against known-bad session-id prefixes -- no
video I/O -- so it is cheap to call per candidate. To vet NEW footage, run the
frame-drop audit (>15% frozen => Tapo-class, exclude) and a games-vs-drill
check (e.g. Jev, or a quick watch) before it enters any sample.
"""

# ADR-155: the original single Tapo recording (PGC court 1 scale-review set).
EXCLUDED_CAMERAS = {
    "de3d1953": "Tapo C200 at PGC court 1: drops frames, no shutter control, and 22 of the 43 fresh clips "
                "judged from it were not rallies (ADR-155)",
}
# ADR-158: the same Tapo camera's other court-1 recordings in the Sept-2026
# field test -- ~32-33% frozen frames each (frame-drop audit). ADR-155 missed these.
EXCLUDED_TAPO = {
    "499ed4b8": "Tapo C200 PGC court 1 (frame-drop audit: 32% frozen frames) -- ADR-158",
    "52f4de24": "Tapo C200 PGC court 1 (frame-drop audit: 33% frozen frames) -- ADR-158",
    "72852da9": "Tapo C200 PGC court 1 (frame-drop audit: 33% frozen frames) -- ADR-158",
}
# ADR-158: coaching / ball-feeding drill session -- no real serves.
EXCLUDED_DRILL = {
    "c6a9136a": "PGC Court 2 coaching/feeding drill: no real serves (Jev: 11/13 practice/not_play, mean real 0.12) -- ADR-158",
}

EXCLUDED = {**EXCLUDED_CAMERAS, **EXCLUDED_TAPO, **EXCLUDED_DRILL}


def usable(name):
    """False when a session name, path or clip id comes from excluded footage
    (frame-dropping Tapo court-1 camera, or a coaching/drill session)."""
    return not any(prefix in str(name) for prefix in EXCLUDED)
