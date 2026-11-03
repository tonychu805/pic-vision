"""Two ideas from an external discussion on separating warm-up from match play (PIC-226), GPU-free.

 A. Post-rally behaviour: a real point is followed by a pause (players walk back,
    fetch the ball, reset); warm-up / drills re-hit immediately or in rapid
    succession. Feature: seconds from the previous detected rally's end to this
    rally's start (pre_gap), from this end to the next start (post_gap), and how
    many detected rallies start within +/-60 s (density). Expected: practice
    has SHORTER gaps / HIGHER density than real rallies.
 B. Speed variance: warm-up has low ball-speed variance, competitive rallies high.
    Feature: std/mean of speeds along the TRACKED ball inside the rally.
    Expected: practice LOWER.

Direction fixed above, before running. Bar (each feature): AUC practice-vs-real
>= 0.75 in the expected direction on the operator's judged field clips AND at the
practice median it flags <= 15% of the 90 hand-graded dev rallies. In-sample, small n.
IMG_7743 not read.
"""
import json, glob, os, statistics, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import validate_absolute_ranking as base
import summarise_top_sample as S
from src.calib import court_wedge
from src.select import frame_speeds, net_width_px
from src.track import track_ball
from src.tracknet import load_predictions

def auc(pos, neg):
    return sum(1.0 if a > b else .5 if a == b else 0 for a in pos for b in neg) / (len(pos) * len(neg))

def unit_features(csvp, calib):
    """per detected rally: pre_gap, post_gap, density, speed_cv"""
    segs, cr, _ = base.detect(csvp, calib)
    segs = sorted(segs, key=lambda s: s["start"])
    tr = load_predictions(csvp, base.FPS); w = court_wedge(calib); npx = net_width_px(calib)
    times = [t for t, *_ in tr]
    fr = [[(x, y, c if c is not None else 1.0)] if w(x, y) else [] for _, x, y, _w, _h, c in tr]
    ys, xs = track_ball(fr, max_jump=150, reset_after=15, return_x=True)
    trk = [(t, x, y) for t, x, y in zip(times, xs, ys) if x is not None]
    sp = [(t, v / npx) for t, v in frame_speeds(trk)]
    out = []
    for i, s in enumerate(segs):
        pre = s["start"] - segs[i - 1]["end"] if i > 0 else None
        post = segs[i + 1]["start"] - s["end"] if i + 1 < len(segs) else None
        dens = sum(1 for o in segs if o is not s and abs(o["start"] - s["start"]) <= 60)
        v = [x for t, x in sp if s["start"] <= t <= s["end"]]
        cv = statistics.pstdev(v) / statistics.mean(v) if len(v) >= 5 and statistics.mean(v) > 0 else None
        out.append({"start": s["start"], "end": s["end"], "pre": pre, "post": post, "dens": dens, "cv": cv})
    return out

DIR = "cache/pgc_fieldtest"; cache = {}
rows = []
for (sid, a, b), (verdict, why) in S.v.items():
    if verdict not in ("real", "short", "not"): continue
    if sid not in cache:
        calib = json.load(open(f"{DIR}/{sid}.calib.json")); cache[sid] = unit_features(f"{DIR}/{sid}.csv", calib)
    best = max(cache[sid], key=lambda r: base.iou({"start": a, "end": b}, r), default=None)
    if best is None or base.iou({"start": a, "end": b}, best) < 0.5: continue
    practice = verdict == "not" and why and any(k in why for k in ("machine", "warm", "feeding", "practice"))
    rows.append((("practice" if practice else verdict), best))
dev = []
for name, csvp, calibp, labp, wend in base.SESSIONS:
    calib = json.load(open(calibp)); feats = unit_features(csvp, calib)
    labs = [r for r in (json.loads(l) for l in open(labp) if l.strip()) if r.get("quality") in (1, 2) and (wend is None or r["end"] <= wend)]
    for lab in labs:
        m = max(feats, key=lambda r: base.iou(lab, r), default=None)
        if m and base.iou(lab, m) >= 0.5: dev.append(m)
P = [r for k, r in rows if k == "practice"]; R = [r for k, r in rows if k == "real"]; SH = [r for k, r in rows if k == "short"]
print(f"judged field clips: real {len(R)}, practice {len(P)}, very short {len(SH)}; graded dev rallies {len(dev)}\n")
def med(v, f): 
    x = [r[f] for r in v if r[f] is not None]; return statistics.median(x) if x else float("nan")
print(f"{'':16s} {'gap before (s)':>15s} {'gap after (s)':>14s} {'rallies within 60 s':>20s} {'speed variability':>18s}")
for lab, g in (("real", R), ("practice", P), ("very short", SH), ("graded dev", dev)):
    print(f"{lab:16s} {med(g,'pre'):15.1f} {med(g,'post'):14.1f} {med(g,'dens'):20.0f} {med(g,'cv'):18.2f}")
print(f"\n{'feature':22s} {'expected':>16s} {'AUC':>6s}   at practice median: flags real field / graded dev   verdict")
for f, nice, sign in (("pre", "gap before", -1), ("post", "gap after", -1), ("dens", "rallies within 60 s", +1), ("cv", "speed variability", -1)):
    p = [r[f] for r in P if r[f] is not None]; r = [x[f] for x in R if x[f] is not None]; d = [x[f] for x in dev if x[f] is not None]
    a = auc(p, r) if sign > 0 else auc(r, p)      # oriented so > 0.5 = expected direction
    cut = statistics.median(p)
    flag = (lambda v: v >= cut) if sign > 0 else (lambda v: v <= cut)
    fr = sum(flag(v) for v in r) / len(r); fd = sum(flag(v) for v in d) / len(d)
    ok = a >= 0.75 and fd <= 0.15
    print(f"{nice:22s} {'practice ' + ('higher' if sign>0 else 'lower'):>16s} {a:6.2f}   {fr:20.0%} / {fd:4.0%}                  {'PASS' if ok else 'fail'}")
