"""Fresh-session test of the frozen pause rule (PIC-226).

Rule, frozen before these sessions were processed (EXPERIMENTS.md 2026-10-12
"session context"): within one recording segment, flag a detected rally as
practice-like if the gap BEFORE it and the gap AFTER it are both <= T = 6.0 s.
A rally with no neighbour on either side cannot be flagged.

The sessions here were never read when the rule was fitted: PGC footage of
2026-09-25/26, processed locally with production inference (run_fresh_inference.py).

Writes cache/fresh_rallies.json (every detected rally with its gaps and flag) and
prints counts. Cutting the review sample is a separate step (cut_fresh_sample.py).
"""
import glob, json, os, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import validate_absolute_ranking as base

T = 6.0
rows, per = [], []
for csvp in sorted(glob.glob("cache/fresh/*.csv")):
    name = os.path.basename(csvp)[:-4]
    meta = json.load(open(f"cache/fresh/{name}.meta.json"))
    calib = json.load(open(meta["calib"]))
    segs, _cr, _sp = base.detect(csvp, calib)
    segs = sorted(segs, key=lambda s: s["start"])
    n_flag = 0
    for i, s in enumerate(segs):
        pre = s["start"] - segs[i - 1]["end"] if i > 0 else None
        post = segs[i + 1]["start"] - s["end"] if i + 1 < len(segs) else None
        flag = pre is not None and post is not None and pre <= T and post <= T
        n_flag += flag
        rows.append({"seg": name, "video": meta["path"], "court": meta["court"], "start": s["start"], "end": s["end"],
                     "pre": pre, "post": post, "flag": flag})
    last = max((s["end"] for s in segs), default=0)
    per.append((name, len(segs), n_flag, last))

json.dump(rows, open("cache/fresh_rallies.json", "w"), indent=1)
print(f"{'segment':52s} {'rallies':>8s} {'flagged':>8s}")
for name, n, f, last in per:
    print(f"{name:52s} {n:8d} {f:8d}")
tot, fl = len(rows), sum(r["flag"] for r in rows)
edge = sum(1 for r in rows if r["pre"] is None or r["post"] is None)
print(f"\nTOTAL detected rallies {tot}; flagged {fl} ({fl/max(tot,1):.0%}); cannot be judged by the rule (no neighbour on a side) {edge}")
