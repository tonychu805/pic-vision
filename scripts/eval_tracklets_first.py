"""Test E: tracklets-first still-site removal (scripts/tracklets_first.py) on bounces AND rallies (2026-10-16,
PIC-226). Pre-registered: this file, the parameters in tracklets_first.py and the bar were committed before
any scoring. No tuning: one fixed config.

Variant = drop_still() applied to the per-frame detections before track_ball; everything downstream unchanged.

PART 1, bounces (tile arm, eval_bounce_recovery matching +-3 frames / 15 px), production vs tracklets-first:
  chunk 2 (c199a97c 0926 s002, 36 labels; production 4, fixed static mask 10):  found >= 10
  chunk 1 (eda301d9 0925 0821 s000, 33 labels; production 14):                   found >= 13  (no real regression)
PART 2, rallies (production detector, the D-series units: 4 graded dev videos + 14 PGC field sessions,
  cache/topk top-1 = production, matching as tune_rally_scoring_cv.py), production vs tracklets-first:
  real field clips lost <= 3 of 60   AND   graded dev rallies lost <= 5 of 83
  reported, not gated: scenery fakes removed (of 8), not-real clips removed (of 35), rallies before -> after
PASS = both parts. Rally loss is counted as in D4: a labelled/judged rally is lost when no segment
matches it at IoU >= 0.5 after the change while one did before.
Run: .venv/bin/python scripts/eval_tracklets_first.py
"""
import collections, csv, glob, json, os, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
from eval.harness import iou
from src.bounce_eval import recover
from src.calib import court_wedge
from src.track import track_ball
from src.tracknet import load_predictions
import eval_bounce_recovery as E
import validate_absolute_ranking as base
import summarise_top_sample as S
import tune_window_scoring as W0
from tracklets_first import drop_still

CHUNKS = [
    ("chunk 1", "eval/labels/bounces/cvat_eda301d9_0925T0821_s000.json",
     "cache/pgc_fieldtest/365c798c-6554-42b1-b0e6-b2825e73d264.calib.json", "cache/bounce_pilot/chunk_eda301d9_0821.tile.csv", 13),
    ("chunk 2", "eval/labels/bounces/cvat_c199a97c_0926T0538_s002.json",
     "cache/pgc_fieldtest/34fab44c-a9a4-4719-bea3-d5a611d54576.calib.json", "cache/bounce_pilot/chunk2_c199a97c_0538_s002.tile.csv", 10),
]


def bounce_points(csv_, calib, variant):
    tr = load_predictions(csv_, 30.0)
    raw = {i: (x, y) for i, (_, x, y, *_r) in enumerate(tr) if x is not None}
    w = court_wedge(calib, margin_px=400.0)
    frames = [[(x, y, c if c is not None else 1.0)] if (x is not None and w(x, y)) else [] for _, x, y, _w, _h, c in tr]
    if variant: frames = drop_still(frames)
    ys, xs = track_ball(frames, max_jump=150, reset_after=15, return_x=True)
    tracked = {i: (xs[i], ys[i]) for i in range(len(ys)) if ys[i] is not None and xs[i] is not None}
    cf, pts = E.sbp.candidates(xs, ys, 0, len(ys) - 1)
    return np.array(calib["homography"], float), raw, tracked, {f: pts[f] for f in cf}


def part1():
    ok = True
    for name, labp, calp, csv_, need in CHUNKS:
        labs = json.load(open(labp))["bounces"]; calib = json.load(open(calp)); res = {}
        for variant in (False, True):
            H, raw, tracked, cands = bounce_points(csv_, calib, variant)
            res[variant] = sum(recover({"frame": b["frame"], "x": b["x"], "y": b["y"], "visible": True}, raw, tracked, cands, H)["found"]
                               for b in labs)
            res[(variant, "c")] = len(cands)
        print(f"{name}: found production {res[False]}/{len(labs)} -> tracklets-first {res[True]}/{len(labs)}  (need >= {need})"
              f"  candidates {res[(False, 'c')]} -> {res[(True, 'c')]}")
        ok &= res[True] >= need
    return ok


def tracks(topk_path, calib, n, variant):
    w = court_wedge(calib); f = [[] for _ in range(n)]
    for fr, c in W0.load_topk(topk_path).items():
        if fr >= n: continue
        c.sort(); f[fr] = [(c[0][1], c[0][2], c[0][3])] if w(c[0][1], c[0][2]) else []
    if variant: f = drop_still(f)
    return track_ball(f, max_jump=150, reset_after=15, return_x=True)


def part2():
    bk = {r["clip"]: r for r in csv.DictReader(open("cache/blind_check_key.csv"))}
    hk = {r["clip"]: r for r in csv.DictReader(open("cache/hotspot_check_key.csv"))}
    def sid_of(pre): return [os.path.basename(x)[:-4] for x in glob.glob("cache/pgc_fieldtest/*.csv") if os.path.basename(x).startswith(pre)][0]
    scen = {}
    for c in W0.SCEN:
        r = bk["O"] if c == "O" else hk[c]
        scen[c] = (sid_of(r["video"].split(":")[-1] if c == "O" else r["session"]), float(r["start"]), float(r["end"]))
    units = []
    for name, csvp, calibp, labp, wend in base.SESSIONS:
        calib = json.load(open(calibp)); n = sum(1 for _ in open(csvp)) - 1
        labs = [r for r in (json.loads(l) for l in open(labp) if l.strip()) if r.get("quality") in (1, 2) and (wend is None or r["end"] <= wend)]
        units.append(("dev", name, f"cache/topk/{name}.csv", calib, n, labs))
    for p in sorted(glob.glob("cache/pgc_fieldtest/*.csv")):
        sid = os.path.basename(p)[:-4]; tp = f"cache/topk/{sid[:8]}.csv"
        if not os.path.exists(tp): continue
        calib = json.load(open(f"cache/pgc_fieldtest/{sid}.calib.json")); n = sum(1 for _ in open(p)) - 1
        units.append(("field", sid, tp, calib, n, None))
    r = collections.Counter()
    pres = lambda ss, a, b: any(iou({"start": a, "end": b}, s) >= 0.5 for s in ss)
    for kind, name, tp, calib, n, labs in units:
        s0 = W0.segs_for(tracks(tp, calib, n, False)[0], calib, n)
        sv = W0.segs_for(tracks(tp, calib, n, True)[0], calib, n)
        r["seg0"] += len(s0); r["seg"] += len(sv)
        if kind == "dev":
            for lab in labs:
                if base.best_match(lab, s0) is not None:
                    r["n_dev"] += 1; r["lost_dev"] += base.best_match(lab, sv) is None
        else:
            for (sid, a, b), (verdict, why) in S.v.items():
                if sid != name or not pres(s0, a, b): continue
                gone = not pres(sv, a, b)
                if verdict == "real": r["real_n"] += 1; r["real_lost"] += gone
                elif verdict in ("not", "short"): r["nr_n"] += 1; r["nr"] += gone
            for c, (sid, a, b) in scen.items():
                if sid == name and pres(s0, a, b): r["fk_n"] += 1; r["fk"] += not pres(sv, a, b)
    print(f"rallies: real field clips lost {r['real_lost']}/{r['real_n']} (need <= 3)  graded dev lost {r['lost_dev']}/{r['n_dev']} (need <= 5)")
    print(f"         scenery fakes removed {r['fk']}/{r['fk_n']}  not-real removed {r['nr']}/{r['nr_n']}  rallies {r['seg0']} -> {r['seg']}")
    return r["real_lost"] <= 3 and r["lost_dev"] <= 5


def main():
    a = part1(); b = part2()
    print(f"\nPART 1 bounces {'PASS' if a else 'FAIL'}   PART 2 rallies {'PASS' if b else 'FAIL'}   ->  {'PASS' if a and b else 'FAIL'}")


if __name__ == "__main__":
    main()
