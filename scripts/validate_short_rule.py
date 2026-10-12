"""Can a duration / crossing-pace rule remove the "very short" false rallies? (PIC-226)

9 of 24 not-real clips in the top-5 sample were "very short" (serve + return
only) points that the detector reported because it counted >= 6 crossings. They
are short. Question: does a simple rule on a detected rally's DURATION (or
crossings per second) remove most of them without removing real rallies?

BAR, WRITTEN BEFORE RUNNING. A rule is acceptable only if ALL hold:
  (1) removes >= 60% of the operator-judged "very short" field clips;
  (2) loses <= 10% of the judged REAL field clips;
  (3) loses <= 5% of the hand-graded dev rallies (89), where a rally is judged by
      the detector's segment duration;
and it is IN-SAMPLE: a passing rule is a candidate to confirm on a fresh sample,
never a result. Grid fixed up front: duration cut-offs 4-9 s and crossing-rate
cut-offs 2.0-3.5 per s. IMG_7743 not read.
"""
import csv, glob, json, os, statistics, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import validate_absolute_ranking as base
from src.select import peak_rate
import summarise_top_sample as S            # reuses all operator verdicts (v)

DIR = "cache/pgc_fieldtest"
def feats(seg, crossed):
    xs = [t for t in crossed if seg["start"] <= t <= seg["end"]]
    d = seg["end"] - seg["start"]
    return {"dur": d, "n": len(xs), "rate": len(xs) / d if d else 0.0}
rows = []
cache = {}
for (sid, a, b), (verdict, why) in S.v.items():
    if verdict not in ("real", "short", "not"): continue
    if sid not in cache:
        calib = json.load(open(f"{DIR}/{sid}.calib.json")); segs, cr, _ = base.detect(f"{DIR}/{sid}.csv", calib); cache[sid] = (segs, cr)
    segs, cr = cache[sid]
    best = max(segs, key=lambda s: base.iou({"start": a, "end": b}, s), default=None)
    if best is None or base.iou({"start": a, "end": b}, best) < 0.5: continue
    f = feats(best, cr); f["verdict"] = verdict; rows.append(f)
R = [r for r in rows if r["verdict"] == "real"]; SH = [r for r in rows if r["verdict"] == "short"]; N = [r for r in rows if r["verdict"] == "not"]
print(f"judged field clips matched to a detected rally: real {len(R)}, very short {len(SH)}, not a rally {len(N)}\n")
def med(v, k): return statistics.median([r[k] for r in v]) if v else float("nan")
print(f"{'':12s} {'duration s':>11s} {'crossings':>10s} {'per second':>11s}")
for lab, g in (("real", R), ("very short", SH), ("not a rally", N)):
    print(f"{lab:12s} {med(g,'dur'):11.1f} {med(g,'n'):10.0f} {med(g,'rate'):11.2f}")
dev = []
for name, csvp, calibp, labp, wend in base.SESSIONS:
    calib = json.load(open(calibp)); segs, cr, _ = base.detect(csvp, calib)
    if wend: segs = [s for s in segs if s["end"] <= wend]
    labs = [r for r in (json.loads(l) for l in open(labp) if l.strip()) if r.get("quality") in (1, 2) and (wend is None or r["end"] <= wend)]
    for lab in labs:
        m = base.best_match(lab, segs)
        if m: dev.append(feats(m, cr))
print(f"\ngraded dev rallies matched: {len(dev)}; their median duration {med(dev,'dur'):.1f} s\n")
print(f"{'rule (reject if...)':28s} {'very short removed':>19s} {'real field lost':>16s} {'not-a-rally removed':>20s} {'graded dev lost':>16s}   bar")
def line(name, pred):
    a = sum(pred(r) for r in SH); b = sum(pred(r) for r in R); c = sum(pred(r) for r in N); d = sum(pred(r) for r in dev)
    ok = (a / len(SH) >= 0.60) and (b / len(R) <= 0.10) and (d / len(dev) <= 0.05)
    print(f"{name:28s} {a:3d}/{len(SH):<3d} ({a/len(SH):4.0%}) {b:6d}/{len(R):<3d} ({b/len(R):4.0%}) {c:8d}/{len(N):<3d} ({c/len(N):4.0%}) {d:6d}/{len(dev):<3d} ({d/len(dev):4.0%})   {'PASS' if ok else 'fail'}")
for D in (4, 5, 6, 7, 8, 9): line(f"duration < {D} s", lambda r, D=D: r["dur"] < D)
for T in (2.0, 2.5, 3.0, 3.5): line(f"crossings/s >= {T}", lambda r, T=T: r["rate"] >= T)
