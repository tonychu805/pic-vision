"""Highlight-type detection from the signals we measure reliably (2026-10-19, PIC-226).
Goal (operator): produce every highlight type that is BOTH feasible (built on signals we have) and highly consistent
(its signature separates highlight-worthy rallies on BOTH graded videos, not one). Pre-registered: the type definitions
and the consistency bar below were committed before the held-out video (pb_draft_cup) was scored on kitchen/fast-dink.

WHY only these types. Contact-dependent types (great serve/ace, put-away/smash) need the ball at the paddle, which the
tracker cannot see (ADR-156) -- excluded as not feasible now; they are the Jev-reads-the-scene route, not this one.

TYPES (per rally, from reliable signals). v2 definitions (2026-10-19), refined after scrutinising each (see
EXPERIMENTS 2026-10-19 long_rally robustness + kitchen_war net-cross follow-ups); the consistency bar is unchanged:
  long_rally  = ACTIVE-PLAY span in seconds = (last net crossing - first net crossing), 0 if < 2 crossings. Padding-,
                merge- and toss-proof: dead time or a toss has no sustained crossings, so it cannot inflate the span.
                (v1 used raw segment duration; active span is equally predictive, AUC 0.81 vs 0.82, and robust.)
  kitchen_war = fraction of rally frames in a cross-net dinking posture that is ALSO an active exchange: a player at
                the near kitchen line (court y 12-18 ft) AND one at the far line (26-32 ft), AND a paddle swing within
                +-15 frames (0.5 s). The swing gate (not a net-cross gate: the tracker loses soft dinks; swings beat
                crossings, EXPERIMENTS follow-up 2) stops players merely standing at the kitchen from counting.
  fast_dink   = true near<->far ALTERNATIONS per second during the kitchen posture, 0 if posture < 1.5 s. Alternations
                (a swing on one side then the other) are the real back-and-forth and are robust to the swing detector's
                false positives (operator clip review: raw counts "close", alternation count stable). (v1 used raw
                swings/sec, which over-counts non-hit arm motion.)
DATA: the two hand-graded videos, brickwall_30fps (49 rallies) and pb_draft_cup_30fps (34), grade 1 = highlight, 2 = ordinary.
  Pose cached per rally (eval_highlight_signals.POSES per target).
CONSISTENCY BAR (what "ship this type" means): a type is KEPT only if its score separates grade-1 from grade-2 with
  AUC >= 0.65 on BOTH videos (same direction). Otherwise it is a single-video artifact and is dropped. long_rally is
  the anchor (already known consistent). The grades are soft (never consistency-checked, LABELING.md), so a KEPT type
  is a lead whose face validity must still be confirmed by watching the clips it flags -- it is not a shipped feature.
OUTPUT: `--eval` prints the consistency table (AUC per type per video, KEEP/DROP). `--tag <target>` writes a per-rally
  type manifest (scores + flags + primary type) to cache/highlight_types/<target>.json for reel assembly / eyeballing.
Run: .venv/bin/python scripts/highlight_types.py --eval
     .venv/bin/python scripts/highlight_types.py --tag brickwall
"""
import json, os, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
import eval_highlight_signals as H
import eval_arm_swing_hits as A
import eval_bounce_recovery as E
from src.bounce_eval import project

TARGETS = ["brickwall", "pbdc"]
TYPES = ["long_rally", "kitchen_war", "fast_dink"]
BAR = 0.65
KITCHEN_MIN_S = 1.5
SWING_GATE = 15   # frames: a kitchen-posture frame counts only if a swing is within +-this


def in_kitchen_posture(players):
    ys = [p["court"][1] for p in players]
    return any(12 <= y <= 18 for y in ys) and any(26 <= y <= 32 for y in ys)


def feats(target):
    H.set_target(target)
    P = {int(k): v for k, v in json.load(open(H.POSES)).items()}
    Hm = np.array(json.load(open(H.CALIB))["homography"], float)
    _, _, tracked, _ = E.clip_points({"calib": H.CALIB, "csv": H.CSV})
    cy = {f: project(Hm, x, y)[1] for f, (x, y) in tracked.items()}
    rows = []
    for r in H.rallies():
        fs = list(H.rally_frames(r))
        # ball net-crossings in the rally -> active-play span
        fsc = [f for f in fs if f in cy]
        cross = [f for f0, f in zip(fsc, fsc[1:]) if f - f0 <= 6 and (cy[f0] - 22) * (cy[f] - 22) < 0]
        active_span = (cross[-1] - cross[0]) / H.FPS if len(cross) >= 2 else 0.0
        # swings with side
        TR = A.tracks([P.get(f, []) for f in fs], 0, len(fs) - 1)
        sw = sorted((fs[0] + lf, "near" if TR[i][lf]["court"][1] < 22 else "far")
                    for lf, i in A.swing_picks(TR) if lf in TR[i])
        swf = {f for f, _ in sw}
        # active kitchen posture: posture AND a swing within +-SWING_GATE
        kit = [f for f in fs if in_kitchen_posture(P.get(f, []))]
        act_kit = [f for f in kit if any((f + d) in swf for d in range(-SWING_GATE, SWING_GATE + 1))]
        kdur = len(kit) / H.FPS
        # fast_dink: near<->far alternations/sec among swings during the kitchen posture
        kset = set(kit); ksw = [(f, s) for f, s in sw if f in kset]
        alt = sum(1 for a, b in zip(ksw, ksw[1:]) if a[1] != b[1])
        rows.append(dict(rid=r["rally_id"], q=r["quality"], dur=r["end"] - r["start"],
                         long_rally=active_span,
                         kitchen_war=len(act_kit) / max(1, len(fs)),
                         fast_dink=(alt / max(0.5, kdur)) if kdur >= KITCHEN_MIN_S else 0.0,
                         kdur=kdur))
    return rows


def auc(pos, neg):
    return sum((p > q) + 0.5 * (p == q) for p in pos for q in neg) / max(1, len(pos) * len(neg))


def eval_consistency():
    data = {t: feats(t) for t in TARGETS}
    print(f"consistency: AUC(grade-1 > grade-2) per type, must be >= {BAR} on BOTH to KEEP\n")
    print(f"{'type':12s}" + "".join(f"{t:>14s}" for t in TARGETS) + "   verdict")
    for ty in TYPES:
        aucs = {}
        for t in TARGETS:
            g1 = [r[ty] for r in data[t] if r["q"] == 1]; g2 = [r[ty] for r in data[t] if r["q"] == 2]
            aucs[t] = auc(g1, g2)
        keep = all(a >= BAR for a in aucs.values())
        print(f"{ty:12s}" + "".join(f"{aucs[t]:>14.2f}" for t in TARGETS) + f"   {'KEEP' if keep else 'drop'}")
    print("\n(grades are soft/never consistency-checked; a KEEP is a lead to confirm by watching the flagged clips.)")


def tag(target):
    rows = feats(target)
    # per-type flag: score in the top third for that video (relative, so it works per court)
    cuts = {ty: np.percentile([r[ty] for r in rows], 66) for ty in TYPES}
    norm = {ty: (lambda v, m=max(1e-9, max(r[ty] for r in rows)): v / m) for ty in TYPES}
    out = []
    for r in rows:
        flags = [ty for ty in TYPES if r[ty] >= cuts[ty] and r[ty] > 0]
        primary = max(TYPES, key=lambda ty: norm[ty](r[ty])) if flags else None
        out.append(dict(rally_id=r["rid"], quality=r["q"], duration=round(r["dur"], 1),
                        scores={ty: round(r[ty], 3) for ty in TYPES}, types=flags, primary=primary))
    os.makedirs("cache/highlight_types", exist_ok=True)
    json.dump(out, open(f"cache/highlight_types/{target}.json", "w"), indent=1)
    from collections import Counter
    c = Counter(x["primary"] for x in out if x["primary"])
    print(f"{target}: tagged {len(out)} rallies; primary type counts {dict(c)}; untyped {sum(x['primary'] is None for x in out)}")
    print("cache/highlight_types/%s.json written" % target)


if __name__ == "__main__":
    if sys.argv[1] == "--eval": eval_consistency()
    else: tag(sys.argv[2])
