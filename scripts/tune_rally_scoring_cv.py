"""Rally-level flight scoring, cross-validated by session (Test D4, PIC-226). Pre-registered; written
before the run.

D1-D3 deleted individual points inside windows; that fragments real rallies (best cross-validated
result: 12 of 60 real field clips lost, 7 of 8 scenery fakes and 18 of 35 not-real clips removed).
D4 never deletes points. The production tracker and rally detector run unchanged; each detected rally
then gets a flight score and is DROPPED WHOLE when the score is low.

  score   windows of W frames (step W/3) across the rally; a window with >= 6 tracked points is scored by
          the share of its points lying in flight pieces (scripts/track_score_windows.py: pieces cut at
          gaps > GAP frames and turns > 90 degrees; flight = >= MINP points, quadratic-fit RMS <= RMS px,
          path >= 40 px, median speed >= 4 px/frame). Rally score = mean share over scored windows; a
          rally with no scored window is kept.
  drop    rally score < T.

GRID (fixed now): W {45, 90} x GAP {3, 6} x RMS {8, 16, 24} x MINP {3, 4} x T {0.15, 0.25, 0.35} = 72.
FOLDS: the 14 field sessions dealt round-robin (sorted) into 5 folds; per fold the config is chosen on
dev + the other folds (fewest real rallies lost, dev + field; ties -> most scenery fakes removed; ties ->
lower T), then scored once on the held fold. Totals are summed over folds.
BAR (same as D3): real field clips lost <= 3; graded dev lost <= 5 of 83 (config chosen on all data
would be circular, so the most-chosen config is used); scenery fakes removed >= 60%; not-real clips
removed >= 50%.
Run: .venv/bin/python scripts/tune_rally_scoring_cv.py
"""
import sys, glob, json, os, csv, collections, itertools
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
import validate_absolute_ranking as base
import summarise_top_sample as S
import track_score_windows as T
from eval.harness import iou
import tune_window_scoring as W0

FPS = 30.0
GRID = list(itertools.product((45, 90), (3, 6), (8.0, 16.0, 24.0), (3, 4), (0.15, 0.25, 0.35)))


def rally_score(ys, xs, seg, w, gap, rms, minp):
    T.GAP, T.RMS_PX, T.MIN_PIECE, T.MIN_LEN = gap, rms, minp, 40.0
    a, b = int(seg["start"] * FPS), int(seg["end"] * FPS)
    shares = []
    for s in range(a, max(a + 1, b - w + 2), max(1, w // 3)):
        pts = [(i, xs[i], ys[i]) for i in range(s, min(b + 1, s + w, len(ys))) if ys[i] is not None and xs[i] is not None]
        if len(pts) < 6:
            continue
        flying = sum(len(p) for p in T._pieces(pts) if T._is_flight(p))
        shares.append(flying / len(pts))
    return float(np.mean(shares)) if shares else None


def main():
    bk = {r["clip"]: r for r in csv.DictReader(open("cache/blind_check_key.csv"))}
    hk = {r["clip"]: r for r in csv.DictReader(open("cache/hotspot_check_key.csv"))}
    def sid_of(pre): return [os.path.basename(x)[:-4] for x in glob.glob("cache/pgc_fieldtest/*.csv") if os.path.basename(x).startswith(pre)][0]
    scen = {}
    for c in W0.SCEN:
        r = bk["O"] if c == "O" else hk[c]
        pre = r["video"].split(":")[-1] if c == "O" else r["session"]
        scen[c] = (sid_of(pre), float(r["start"]), float(r["end"]))
    units = []
    for name, csvp, calibp, labp, wend in base.SESSIONS:
        calib = json.load(open(calibp)); n = sum(1 for _ in open(csvp)) - 1
        ys, xs = W0.tracks(f"cache/topk/{name}.csv", calib, n)
        labs = [r for r in (json.loads(l) for l in open(labp) if l.strip()) if r.get("quality") in (1, 2) and (wend is None or r["end"] <= wend)]
        units.append(dict(kind="dev", name=name, ys=ys, xs=xs, calib=calib, n=n, labs=labs))
    for p in sorted(glob.glob("cache/pgc_fieldtest/*.csv")):
        sid = os.path.basename(p)[:-4]; tp = f"cache/topk/{sid[:8]}.csv"
        if not os.path.exists(tp): continue
        calib = json.load(open(f"cache/pgc_fieldtest/{sid}.calib.json")); n = sum(1 for _ in open(p)) - 1
        ys, xs = W0.tracks(tp, calib, n)
        units.append(dict(kind="field", name=sid, ys=ys, xs=xs, calib=calib, n=n, labs=None))
    for u in units:
        u["segs"] = W0.segs_for(u["ys"], u["calib"], u["n"])
        u["cache"] = {}
    def scores(u, key):
        if key not in u["cache"]:
            u["cache"][key] = [rally_score(u["ys"], u["xs"], s, *key) for s in u["segs"]]
        return u["cache"][key]
    def kept_segs(u, cfg):
        if cfg is None: return u["segs"]
        w, gap, rms, minp, t = cfg
        return [s for s, sc in zip(u["segs"], scores(u, (w, gap, rms, minp))) if sc is None or sc >= t]
    def score(cfg, pred):
        r = collections.Counter()
        for u in units:
            if not pred(u): continue
            sv = kept_segs(u, cfg)
            r["seg0"] += len(u["segs"]); r["seg"] += len(sv)
            if u["kind"] == "dev":
                for lab in u["labs"]:
                    b0, bv = base.best_match(lab, u["segs"]), base.best_match(lab, sv)
                    if b0 is not None: r["n_dev"] += 1; r["lost_dev"] += bv is None
            else:
                pres = lambda ss, a, b: any(iou({"start": a, "end": b}, s) >= 0.5 for s in ss)
                for (sid, a, b), (verdict, why) in S.v.items():
                    if sid != u["name"] or not pres(u["segs"], a, b): continue
                    gone = not pres(sv, a, b)
                    if verdict == "real": r["real_n"] += 1; r["real_lost"] += gone
                    elif verdict in ("not", "short"): r["nr_n"] += 1; r["nr"] += gone
                for c, (sid, a, b) in scen.items():
                    if sid == u["name"] and pres(u["segs"], a, b): r["fk_n"] += 1; r["fk"] += not pres(sv, a, b)
        return r
    field = sorted(u["name"] for u in units if u["kind"] == "field")
    fold_of = {s: i % 5 for i, s in enumerate(field)}
    agg = collections.Counter(); chosen = []
    for fold in range(5):
        held = lambda u: u["kind"] == "field" and fold_of[u["name"]] == fold
        tune = lambda u: not held(u)
        best = None
        for cfg in GRID:
            r = score(cfg, tune)
            key = (r["lost_dev"] + r["real_lost"], -r["fk"], cfg[4])
            if best is None or key < best[0]: best = (key, cfg)
        cfg = best[1]; chosen.append(cfg)
        r = score(cfg, held); agg.update(r)
        print(f"fold {fold}: chose (W,gap,rms,minp,T)={cfg}  held-out real lost {r['real_lost']}/{r['real_n']}  "
              f"fakes {r['fk']}/{r['fk_n']}  not-real {r['nr']}/{r['nr_n']}")
    print(f"\nSUMMED held-out: real field clips lost {agg['real_lost']}/{agg['real_n']}  fakes removed {agg['fk']}/{agg['fk_n']}  "
          f"not-real removed {agg['nr']}/{agg['nr_n']}  rallies {agg['seg0']}->{agg['seg']}")
    final = collections.Counter(chosen).most_common(1)[0][0]
    dev = score(final, lambda u: u["kind"] == "dev")
    print(f"most-chosen config {final} ({collections.Counter(chosen).most_common(1)[0][1]}/5 folds): graded dev lost {dev['lost_dev']}/{dev['n_dev']}")
    ok = agg["real_lost"] <= 3 and dev["lost_dev"] <= 5 and agg["fk"] >= 0.6 * agg["fk_n"] and agg["nr"] >= 0.5 * agg["nr_n"]
    print(f"BAR: real lost <= 3 ({agg['real_lost']}), dev lost <= 5 ({dev['lost_dev']}), fakes >= 60% ({agg['fk']}/{agg['fk_n']}), "
          f"not-real >= 50% ({agg['nr']}/{agg['nr_n']}) -> {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    main()
