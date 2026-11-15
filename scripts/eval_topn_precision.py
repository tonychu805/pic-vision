"""How precise is "ship only the best N clips" / "ship only clips above a score"? (2026-10-14)

Descriptive measurement, no pass/fail bar: its job is to tell us what bar is realistic
for the PGC field-test footage before we pick one (the operator asked for a guardrail
against false positives without a number that was not grounded in data).

Data: the 30 clips the operator judged at playback speed (cache/fresh_sample_key.csv with the
verdicts in scripts/eval_rally_formation.py: 15 real, 3 serve-and-return only, 12 not a
rally). Every detected rally in the 8 fresh PGC segments is scored with the shipped fixed
0-100 score (src/select.py score_segments), so a clip's score does not depend on which
other clips are in the set. Detection is the shipped rule (gap 3.0 s, min 6 crossings,
band 0, 30 fps as in eval_rally_formation.py).

Caveat, stated up front: the 30 judged clips are a sample ("near" and "rand" groups) of
the detected rallies, not all of them, and they come from one venue. Precision numbers
are rough; the second-venue test is the real measurement.

Reports, for each score cut-off: clips kept, how many of the judged real clips survive,
and precision of what is kept (strict: only "real" counts; lenient: serve-and-return
counts as a rally too). Also per-session top-N.
Run: .venv/bin/python scripts/eval_topn_precision.py
"""
import csv, json, sys
sys.path.insert(0, ".")
from eval.harness import iou
from src.ball import cluster_crossings, crossing_times, net_line_y
from src.calib import court_wedge
from src.select import frame_speeds, net_width_px, score_segments
from src.track import track_ball
from src.tracknet import load_predictions

V = dict(x.split("=") for x in "301=not 302=not 303=real 304=short 305=short 306=not 307=real 308=not 309=real 310=real 311=not 312=short 313=real 314=not 315=real 316=not 317=real 318=real 319=not 320=not 321=real 322=not 323=real 324=not 325=real 326=real 327=real 328=not 329=real 330=real".split())


def scored_segments(seg):
    meta = json.load(open(f"cache/fresh/{seg}.meta.json"))
    calib = json.load(open(meta["calib"]))
    tr = load_predictions(f"cache/fresh/{seg}.csv", 30.0)
    w = court_wedge(calib)
    frames = [[(x, y, c if c is not None else 1.0)] if (x is not None and w(x, y)) else []
              for _, x, y, _w, _h, c in tr]
    ys = track_ball(frames, max_jump=150, reset_after=15)
    cr = crossing_times(list(zip([i / 30.0 for i in range(len(ys))], ys)), net_y=net_line_y(calib), band=0)
    segs = cluster_crossings(cr, gap_sec=3.0, min_crossings=6)
    raw = sorted([(t, x, y) for t, x, y, _w, _h, _c in tr if x is not None and w(x, y)], key=lambda p: p[0])
    return score_segments(segs, cr, frame_speeds(raw), net_width_px(calib))


def main():
    fresh = list(csv.DictReader(open("cache/fresh_sample_key.csv")))
    by_seg = {}
    for f in fresh:
        by_seg.setdefault(f["segment"], []).append(f)
    allseg, judged = {}, []
    for seg, items in by_seg.items():
        allseg[seg] = scored_segments(seg)
        for f in items:
            lab = {"start": float(f["start"]), "end": float(f["end"])}
            best = max(allseg[seg], key=lambda s: iou(lab, s), default=None)
            if best is None or iou(lab, best) < 0.5:
                print("unmatched judged clip", f["clip"], seg); continue
            rank = allseg[seg].index(best) + 1
            judged.append(dict(clip=f["clip"], seg=seg, verdict=V[f["clip"]], score=best["score"],
                               rank=rank, n=len(allseg[seg])))
    print(f"detected rallies across the {len(allseg)} sessions: {sum(len(v) for v in allseg.values())}; judged matched: {len(judged)}")
    n_real = sum(j["verdict"] == "real" for j in judged)
    print(f"judged: real {n_real}, serve+return {sum(j['verdict']=='short' for j in judged)}, "
          f"not a rally {sum(j['verdict']=='not' for j in judged)}\n")
    print("per judged clip, best score first:")
    for j in sorted(judged, key=lambda j: -j["score"]):
        print(f"  clip {j['clip']} {j['verdict']:5s} score {j['score']:5.1f}  rank {j['rank']}/{j['n']} in its session")
    print(f"\n{'score >=':>9s} {'kept':>5s} {'real kept':>10s} {'real lost':>10s} {'precision strict':>17s} {'lenient':>8s}")
    for t in (0, 20, 30, 35, 40, 45, 50, 55, 60):
        kept = [j for j in judged if j["score"] >= t]
        rk = sum(j["verdict"] == "real" for j in kept)
        lk = sum(j["verdict"] in ("real", "short") for j in kept)
        p = f"{rk / len(kept):.0%}" if kept else "-"
        pl = f"{lk / len(kept):.0%}" if kept else "-"
        print(f"{t:9d} {len(kept):5d} {rk:7d}/{n_real:<2d} {n_real - rk:10d} {p:>17s} {pl:>8s}")
    print(f"\n{'top-N/session':>14s} {'kept':>5s} {'real kept':>10s} {'precision strict':>17s} {'lenient':>8s}")
    for n in (1, 2, 3, 5, 8):
        kept = [j for j in judged if j["rank"] <= n]
        rk = sum(j["verdict"] == "real" for j in kept)
        lk = sum(j["verdict"] in ("real", "short") for j in kept)
        p = f"{rk / len(kept):.0%}" if kept else "-"
        pl = f"{lk / len(kept):.0%}" if kept else "-"
        print(f"{n:14d} {len(kept):5d} {rk:7d}/{n_real:<2d} {p:>17s} {pl:>8s}")


main()
