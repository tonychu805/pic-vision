"""Collectible badges from player pose (operator bars, 2026-10-26).

Each badge goes to at most one rally per session, no rally holds two, and a
badge nobody clears is simply not awarded. Bars, all relative to the
session's typical swing so they hold across cameras and levels:

  Kitchen War    >= half the rally with a player at each kitchen line, <= 1 fast swing
  Quick Hands    >= half the rally at the kitchens, >= 4 fast swings
  Hardest Swing  one swing >= 5x typical, not hit from the kitchen
  First Strike   the serve >= 3x typical swing AND >= 2x the session's typical serve
  Killer Shot    the rally's last swing >= 3.5x typical
  (Marathon is blocked: a long "rally" was two points merged.)

Swing = a player's wrist speed in their own box-heights per second: same
player across consecutive frames, swap-proof (nearest of that player's
previous two wrists), sustained over 2 frames, wrist confidence > 0.3, box
height stable, not cut off by the frame edge, player on court. A "fast"
swing is >= 2x typical. Speeds are divided by a court-zone correction
(ZONE_P90), frozen from the 12 sessions the bars were set on, because the
same swing reads faster or slower depending on where the player stands.

Ported from the scratchpad prototypes (swing_speed3 / serve_score /
badges_generic) that produced the blind brickwall run; any change here
needs that run repeated.
"""
import math
import statistics as st

FPS = 30.0
FAST = 2.0
BARS = {"Kitchen War": 0.5, "Quick Hands": 4, "Hardest Swing": 5.0, "First Strike": 3.0, "Killer Shot": 3.5}
FIRST_STRIKE_VS_SERVE = 2.0
BADGES = ("Kitchen War", "Quick Hands", "Hardest Swing", "First Strike", "Killer Shot")

# Per-zone p90 of (swing / session median) over 2,073 swings in 12 sessions
# (brickwall, brickwall-SEMI, 10 PGC), and the overall p90. Frozen.
ZONE_P90 = {0: 1.992, 1: 1.9312, 2: 1.8522, 3: 2.7183, 4: 2.1209, 5: 2.5749}
ALL_P90 = 2.0173


def zone(court_y):
    return 0 if court_y < 7 else 1 if court_y < 15 else 2 if court_y < 22 else 3 if court_y < 29 else 4 if court_y < 37 else 5


def _centre(box):
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _wrist_steps(P, frames, W, H, keep, keep_cur=None):
    """{(frame, x-bucket, wrist): (speed, t, wrist_xy, box, court_x, court_y)} for one-frame wrist moves.

    `keep` filters both frames' people; `keep_cur`, if given, additionally
    filters the current frame's (the serve's baseline rule applies to the
    swinging player, not to who they are matched against)."""
    step = {}
    for f in frames:
        prev, cur = P.get(str(f - 1)), P.get(str(f))
        if prev is None or cur is None:
            continue
        A = [p for p in prev if keep(p)]
        for b in (p for p in cur if keep(p) and (keep_cur is None or keep_cur(p))):
            bx0, by0, bx1, by1 = b["box"]
            hb = by1 - by0
            cb = _centre(b["box"])
            if hb <= 0 or not A:
                continue
            if bx0 <= 3 or by0 <= 3 or bx1 >= W - 3 or by1 >= H - 3:      # cut off by the frame edge
                continue
            a = min(A, key=lambda p: math.dist(_centre(p["box"]), cb))
            if math.dist(_centre(a["box"]), cb) > 0.5 * hb:
                continue
            if not (0.8 <= hb / max(a["box"][3] - a["box"][1], 1) <= 1.25):
                continue
            prevw = [a["kp"][k] for k in (9, 10) if len(a["kp"]) > k and a["kp"][k][2] > 0.3]
            for j in (9, 10):
                if prevw and len(b["kp"]) > j and b["kp"][j][2] > 0.3:
                    d = min(math.hypot(b["kp"][j][0] - w[0], b["kp"][j][1] - w[1]) for w in prevw) / hb
                    if d < 1.0:
                        step[(f, round(cb[0] / 40), j)] = (d * FPS, f / FPS, (b["kp"][j][0], b["kp"][j][1]), b["box"],
                                                           b["court"][0], b["court"][1])
    return step


def _sustained(step):
    """Keep moves that the same player + wrist sustains into the next frame; speed = the slower of the two."""
    out = []
    for (f, cx, j), v in step.items():
        nxt = next((step[k] for k in ((f + 1, cx + dx, j) for dx in (-1, 0, 1)) if k in step), None)
        if nxt:
            out.append((min(v[0], nxt[0]),) + v[1:])
    return out


def _player(p):
    """Feet on court -- the filter the pose caches the bars were set on applied
    (eval_arm_swing_hits.py: x -2..22, y -6..50 ft). Without it a spectator
    level with a kitchen line counts toward Kitchen War."""
    c = p.get("court")
    return bool(c) and -2 <= c[0] <= 22 and -6 <= c[1] <= 50


def _on_court(p):
    c = p.get("court")
    return bool(c) and -4 <= c[0] <= 24 and -6 <= c[1] <= 50


def _on_court_serve(p):
    c = p.get("court")
    return bool(c) and -6 <= c[0] <= 26 and -10 <= c[1] <= 54


def _at_baseline(p):
    return p["court"][1] < 7 or p["court"][1] > 37                  # the server stands at a baseline


def swing_peaks(P, W, H):
    """Swing peaks >= 1 s apart: (speed, t, wrist_xy, box, court_x, court_y), fastest first."""
    frames = sorted(map(int, P))
    out = sorted(_sustained(_wrist_steps(P, frames, W, H, _on_court)), key=lambda s: -s[0])
    peaks = []
    for s in out:
        if all(abs(s[1] - p[1]) > 1.0 for p in peaks):
            peaks.append(s)
    return peaks


def serve_peak(P, frames, W, H):
    """Fastest sustained swing by a player at a baseline within `frames`, or None."""
    out = _sustained(_wrist_steps(P, frames, W, H, _on_court_serve, _at_baseline))
    return max(out, key=lambda s: s[0]) if out else None


def _kitchen_standoff(people):
    yy = [p["court"][1] for p in people if p.get("court")]
    return any(12 <= y <= 18 for y in yy) and any(26 <= y <= 32 for y in yy)


def measure(P, segments, W, H):
    """One part's raw measurements -- what a pod sends; it decides nothing.

    Every bar is relative to the SESSION's typical swing and serve, which no
    single part knows (a slow part makes the next part's swings look fast),
    so the console gathers every part's measurements and calls decide().

    P: {str(frame): [person]} from src/pose.py; segments: rallies in seconds.
    Returns {"swings": [[speed, t, court_y], ...] (every swing peak in the
    part, fastest first), "rallies": [{"start", "end", "share", "serve":
    [speed, t, court_y] or None}]}. share = fraction of the rally with a
    player at each kitchen line; serve is None when the serve window wasn't
    posed well enough to judge.
    """
    P = {f: [p for p in people if _player(p)] for f, people in P.items()}
    swings = [[round(p[0], 5), round(p[1], 3), round(p[5], 3)] for p in swing_peaks(P, W, H)]
    rallies = []
    for r in segments:
        fs = [f for f in range(int(r["start"] * FPS), int(r["end"] * FPS) + 1) if str(f) in P]
        share = sum(_kitchen_standoff(P[str(f)]) for f in fs) / len(fs) if fs else 0.0
        window = range(int((r["start"] - 1.5) * FPS), int(r["start"] * FPS) + 1)
        serve = None
        if sum(1 for f in window if str(f) in P) >= 0.8 * len(window):
            b = serve_peak(P, window, W, H)
            if b:
                serve = [round(b[0], 5), round(b[1], 3), round(b[5], 3)]
        rallies.append({"start": r["start"], "end": r["end"], "share": round(share, 5), "serve": serve})
    return {"swings": swings, "rallies": rallies}


def decide(parts):
    """Badges for a whole session from every part's measure().

    parts: list of measure() results, one per part, in any order. Returns
    {"typical_swing", "n_swings", "candidates", "awarded"}. A candidate is
    {badge, part, rally, start, end, value, margin, t}: `part` is the index
    into `parts`, `rally` the index into that part's rallies; margin = how
    far past its bar (1.0 = exactly on it), which is also how badges are
    chosen when two want the same rally. Only candidates (every one at or
    past its bar) can be awarded, so no rally clearing a bar means no badge.
    """
    speeds = [s[0] for m in parts for s in m["swings"]]
    result = {"typical_swing": None, "n_swings": len(speeds), "candidates": [], "awarded": {}}
    if not speeds:
        return result
    med = st.median(speeds)
    result["typical_swing"] = med
    if med <= 0:          # nobody actually swung: nothing to measure against
        return result

    def adj(s):           # [speed, t, court_y] -> times typical, position-corrected
        return s[0] / med / ZONE_P90[zone(s[2])] * ALL_P90

    cands, serves = [], []

    def add(badge, k, i, value, margin, t=None):
        r = parts[k]["rallies"][i]
        cands.append({"badge": badge, "part": k, "rally": i, "start": r["start"], "end": r["end"],
                      "value": float(value), "margin": float(margin), "t": t})

    for k, m in enumerate(parts):
        for i, r in enumerate(m["rallies"]):
            share = r["share"]
            rs = sorted((s for s in m["swings"] if r["start"] - 1.5 <= s[1] <= r["end"] + 0.5), key=lambda s: s[1])
            fast = [s for s in rs if adj(s) >= FAST]
            if share >= BARS["Kitchen War"] and len(fast) <= 1:
                add("Kitchen War", k, i, share, share / BARS["Kitchen War"])
            if share >= BARS["Kitchen War"] and len(fast) >= BARS["Quick Hands"]:
                add("Quick Hands", k, i, len(fast), len(fast) / BARS["Quick Hands"])
            for s in rs:
                if adj(s) >= BARS["Hardest Swing"] and not (15 <= s[2] <= 29) and r["start"] <= s[1] <= r["end"] + 0.5:
                    add("Hardest Swing", k, i, adj(s), adj(s) / BARS["Hardest Swing"], s[1])
            late = [s for s in rs if adj(s) >= 1.0 and r["end"] - 2 <= s[1] <= r["end"] + 0.1]
            if late and adj(late[-1]) >= BARS["Killer Shot"]:
                add("Killer Shot", k, i, adj(late[-1]), adj(late[-1]) / BARS["Killer Shot"], late[-1][1])
            if r["serve"]:
                serves.append((adj(r["serve"]), k, i, r["serve"]))

    if serves:
        typical_serve = st.median(s[0] for s in serves)
        for v, k, i, b in serves:
            if v >= BARS["First Strike"] and v / typical_serve >= FIRST_STRIKE_VS_SERVE:
                add("First Strike", k, i, v, min(v / BARS["First Strike"], v / typical_serve / FIRST_STRIKE_VS_SERVE), b[1])

    result["candidates"] = cands
    result["awarded"] = award(cands)
    return result


def assess(P, segments, W, H):
    """Badges for one video on its own: decide() over a single part."""
    return decide([measure(P, segments, W, H)])


def award(cands):
    """Each badge to at most one rally, each rally at most one badge, biggest margin first."""
    got, used = {}, set()
    for c in sorted(cands, key=lambda c: -c["margin"]):
        key = (c.get("part", 0), c["rally"])
        if c["badge"] in got or key in used:
            continue
        got[c["badge"]] = c
        used.add(key)
    return got
