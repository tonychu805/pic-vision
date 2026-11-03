"""Does a rally's hitting RHYTHM separate practice from real rallies? (PIC-226)

Practice (warm-up, ball-machine drills, feeding) scored higher than real
rallies under the shipped score (median 84 vs 65) because it is continuous and
fast. Idea: practice is also more METRONOMIC (steady gaps between net
crossings), a game point is not. Offline, crossing times only; no new model.

Features, all from the gaps between consecutive net crossings inside a rally:
  cv_gap       std / mean of the gaps            (low = steady)
  mad_ratio    median |gap - median| / median    (low = steady, robust)
  frac_steady  share of gaps within +/-25% of the median gap (high = steady)
  longest_run  longest run of consecutive "steady" gaps / number of gaps
  max_gap_ratio  largest gap / median gap        (a pause or a missed ball)

DECIDED BEFORE LOOKING AT ANY NUMBER. A rhythm feature is useful only if ALL:
  (1) AUC practice-vs-real on the operator's 40-clip field sample >= 0.75 in
      the expected direction (real clips = 24, practice = 10; clips already
      judged by the operator, key in cache/);
  (2) it stays >= 0.70 within a length-matched subset (8-25 s), because
      practice rallies are longer and length alone could carry the result;
  (3) at the PRACTICE MEDIAN (a cut that catches half the practice clips) it
      flags no more than 15% of the 89 hand-graded real game rallies in the
      four dev videos, so it does not punish legitimate long dink rallies.
Anything that fails (1) is reported as "no signal"; (3) is reported either way.
n is small (10 practice clips, one venue, two days): a pass is a lead, not a
result. IMG_7743 (locked eval set) is never read.
"""
import csv, glob, json, math, statistics, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import validate_absolute_ranking as base

PRACTICE = {"03", "21", "30", "36", "18", "24", "26", "37", "39", "29"}   # operator's reasons
REAL = None  # set from answers below
ANS_REAL = {"01","02","04","05","06","08","10","11","12","13","16","17","19","20","22","23","25","27","28","31","32","33","34","38"}
FEATS = ["cv_gap", "mad_ratio", "frac_steady", "longest_run", "max_gap_ratio"]
EXPECT = {"cv_gap": -1, "mad_ratio": -1, "frac_steady": +1, "longest_run": +1, "max_gap_ratio": -1}  # direction practice vs real

def rhythm(times):
    g = [b - a for a, b in zip(times, times[1:]) if b - a > 0]
    if len(g) < 3:
        return None
    med = statistics.median(g)
    mean = statistics.mean(g)
    steady = [abs(x - med) <= 0.25 * med for x in g]
    run = best = 0
    for s in steady:
        run = run + 1 if s else 0
        best = max(best, run)
    return {"cv_gap": statistics.pstdev(g) / mean if mean else None,
            "mad_ratio": statistics.median(abs(x - med) for x in g) / med if med else None,
            "frac_steady": sum(steady) / len(g), "longest_run": best / len(g),
            "max_gap_ratio": max(g) / med if med else None, "n_gaps": len(g)}

def auc(pos, neg):  # chance a random positive exceeds a random negative
    return sum(1.0 if a > b else .5 if a == b else 0 for a in pos for b in neg) / (len(pos) * len(neg))

def ci(a, n1, n2):
    q1, q2 = a / (2 - a), 2 * a * a / (1 + a)
    se = ((a * (1 - a) + (n1 - 1) * (q1 - a * a) + (n2 - 1) * (q2 - a * a)) / (n1 * n2)) ** 0.5
    return 1.96 * se

key = {r["clip"]: r for r in csv.DictReader(open("cache/precision_sample_key.csv"))}
cache = {}
clips = []
for c, r in key.items():
    if c not in PRACTICE and c not in ANS_REAL:
        continue
    sid = [p.split("/")[-1][:-4] for p in glob.glob("cache/pgc_fieldtest/*.csv") if p.split("/")[-1].startswith(r["session"])][0]
    if sid not in cache:
        calib = json.load(open(f"cache/pgc_fieldtest/{sid}.calib.json"))
        _, crossed, _ = base.detect(f"cache/pgc_fieldtest/{sid}.csv", calib)
        cache[sid] = crossed
    s, e = float(r["start"]), float(r["end"])
    f = rhythm([t for t in cache[sid] if s <= t <= e])
    if f:
        f.update({"clip": c, "kind": "practice" if c in PRACTICE else "real", "dur": e - s})
        clips.append(f)
prac = [c for c in clips if c["kind"] == "practice"]; real = [c for c in clips if c["kind"] == "real"]
print(f"field sample: {len(prac)} practice, {len(real)} real (clips with >= 4 crossings)\n")

# graded dev rallies (real game play)
dev = []
for name, csvp, calibp, labp, wend in base.SESSIONS:
    calib = json.load(open(calibp))
    segs, crossed, _ = base.detect(csvp, calib)
    if wend: segs = [s for s in segs if s["end"] <= wend]
    labs = [r for r in (json.loads(l) for l in open(labp) if l.strip()) if r.get("quality") in (1, 2) and (wend is None or r["end"] <= wend)]
    for lab in labs:
        seg = base.best_match(lab, segs)
        if seg:
            f = rhythm([t for t in crossed if seg["start"] <= t <= seg["end"]])
            if f: dev.append(f)
print(f"hand-graded dev rallies (real game play): {len(dev)}\n")

print(f"{'feature':14s} {'practice med':>12s} {'real med':>9s} {'dev med':>8s} | {'AUC':>5s} {'(95%)':>12s} {'AUC len-matched':>16s} | flagged at practice median: real field / graded dev")
verdict = {}
for ft in FEATS:
    p = [c[ft] for c in prac if c[ft] is not None]; r = [c[ft] for c in real if c[ft] is not None]
    d = [c[ft] for c in dev if c[ft] is not None]
    sign = EXPECT[ft]
    a = auc(p, r) if sign > 0 else auc(r, p)          # oriented so that >0.5 = expected direction
    h = ci(a, len(p), len(r))
    pm = [c[ft] for c in prac if 8 <= c["dur"] <= 25 and c[ft] is not None]; rm = [c[ft] for c in real if 8 <= c["dur"] <= 25 and c[ft] is not None]
    am = (auc(pm, rm) if sign > 0 else auc(rm, pm)) if len(pm) >= 3 and len(rm) >= 3 else float("nan")
    cut = statistics.median(p)
    flag = (lambda v: v >= cut) if sign > 0 else (lambda v: v <= cut)
    fr = sum(flag(v) for v in r) / len(r); fd = sum(flag(v) for v in d) / len(d)
    ok = a >= 0.75 and am >= 0.70 and fd <= 0.15
    verdict[ft] = ok
    print(f"{ft:14s} {statistics.median(p):12.2f} {statistics.median(r):9.2f} {statistics.median(d):8.2f} | {a:5.2f} {f'({max(0,a-h):.2f}-{min(1,a+h):.2f})':>12s} {am:16.2f} | {fr:5.0%} / {fd:5.0%}   {'PASS' if ok else 'fail'}  [(1){'ok' if a>=0.75 else 'x'} (2){'ok' if am>=0.70 else 'x'} (3){'ok' if fd<=0.15 else 'x'}]")
print("\nuseful features:", [f for f, ok in verdict.items() if ok] or "none")
