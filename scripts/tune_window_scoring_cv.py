"""Tune whole-track window scoring, round 2: cross-validated over field sessions (Test D3, PIC-226).
Pre-registered; written before the run.

Round 1 (D2, `scripts/tune_window_scoring.py`) picked a config on the 4 dev videos plus 2 small field
sessions and it did not transfer: dev losses fell from 33/83 to 3/83 but 12 of 58 real field clips were
still lost on the held-out sessions. The split was the flaw: the tune set held only 2 real field clips.

Round 2 (fixed now): the 14 field sessions are dealt into 5 folds by session (round-robin in sorted
order). For each fold, the config is chosen on the 4 dev videos + the other 4 folds, by the same rule
as round 1 (fewest real rallies lost, dev + field; ties -> most scenery fakes removed; ties -> closest to
D1), over the same 72-config grid, and scored once on the held-out fold. Totals are summed over folds.
BAR (summed held-out folds): real field clips lost <= 3 of the real clips present, graded dev lost
<= 5 of 83 (scored with the config chosen on all folds), and >= 60% of the scenery fakes and >= 50% of
the not-real clips removed. Anything else = FAIL.
Run: .venv/bin/python scripts/tune_window_scoring_cv.py
"""
import sys, glob, json, os, csv, collections, itertools
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import validate_absolute_ranking as base
import summarise_top_sample as S
import track_score_windows as T
from eval.harness import iou
from src.calib import court_wedge
from src.track import track_ball
from src.ball import net_line_y, crossing_times, cluster_crossings

FPS = 30.0
SCEN = {"O", "201", "202", "203", "204", "205", "207", "209"}
GRID = list(itertools.product((6.0, 8.0, 12.0, 16.0), (3, 4, 5), (40.0, 60.0, 80.0), (0.3, 0.5)))
D1 = (6.0, 5, 80.0, 0.5)


def load_topk(path):
    d = collections.defaultdict(list)
    for r in csv.DictReader(open(path)):
        d[int(r["Frame"])].append((int(r["Rank"]), float(r["X"]), float(r["Y"]), float(r["Conf"])))
    return d


def tracks(path, calib, n):
    w = court_wedge(calib); f = [[] for _ in range(n)]
    for fr, c in load_topk(path).items():
        if fr >= n: continue
        c.sort(); f[fr] = [(c[0][1], c[0][2], c[0][3])] if w(c[0][1], c[0][2]) else []
    return track_ball(f, max_jump=150, reset_after=15, return_x=True)


def set_cfg(cfg):
    T.RMS_PX, T.MIN_PIECE, T.MIN_LEN, share = cfg
    T.SHARE = share


def segs_for(ys, calib, n):
    cr = crossing_times(list(zip([i / FPS for i in range(n)], ys)), net_y=net_line_y(calib), band=0.0)
    return cluster_crossings(cr, gap_sec=base.GAP_SEC, min_crossings=base.MIN_CROSSINGS)


def main():
    bk = {r["clip"]: r for r in csv.DictReader(open("cache/blind_check_key.csv"))}
    hk = {r["clip"]: r for r in csv.DictReader(open("cache/hotspot_check_key.csv"))}
    def sid_of(pre): return [os.path.basename(x)[:-4] for x in glob.glob("cache/pgc_fieldtest/*.csv") if os.path.basename(x).startswith(pre)][0]
    scen = {}
    for c in SCEN:
        r = bk["O"] if c == "O" else hk[c]
        pre = r["video"].split(":")[-1] if c == "O" else r["session"]
        scen[c] = (sid_of(pre), float(r["start"]), float(r["end"]))
    tune_sessions = {scen["O"][0]} | {sid_of("7ace7db9")}
    units = []   # (kind, name, split, ys, xs, calib, n, extra)
    for name, csvp, calibp, labp, wend in base.SESSIONS:
        calib = json.load(open(calibp)); n = sum(1 for _ in open(csvp)) - 1
        ys, xs = tracks(f"cache/topk/{name}.csv", calib, n)
        labs = [r for r in (json.loads(l) for l in open(labp) if l.strip()) if r.get("quality") in (1, 2) and (wend is None or r["end"] <= wend)]
        units.append(("dev", name, "tune", ys, xs, calib, n, labs))
    for p in sorted(glob.glob("cache/pgc_fieldtest/*.csv")):
        sid = os.path.basename(p)[:-4]; tp = f"cache/topk/{sid[:8]}.csv"
        if not os.path.exists(tp): continue
        calib = json.load(open(f"cache/pgc_fieldtest/{sid}.calib.json")); n = sum(1 for _ in open(p)) - 1
        ys, xs = tracks(tp, calib, n)
        units.append(("field", sid, "tune" if sid in tune_sessions else "held", ys, xs, calib, n, None))
    c0 = {}
    for u in units:
        c0[u[1]] = segs_for(u[3], u[5], u[6])

    def score(cfg, split):
        if cfg: set_cfg(cfg)
        lost_dev = n_dev = real_lost = real_n = fk = fk_n = nr = nr_n = seg = seg0 = 0
        for kind, name, sp, ys, xs, calib, n, labs in units:
            if not split(kind, name): continue
            sv = c0[name] if cfg is None else segs_for(T.drop_non_flight(ys, xs), calib, n)
            seg += len(sv); seg0 += len(c0[name])
            if kind == "dev":
                for lab in labs:
                    b0, bv = base.best_match(lab, c0[name]), base.best_match(lab, sv)
                    if b0 is not None:
                        n_dev += 1; lost_dev += bv is None
            else:
                for (sid, a, b), (verdict, why) in S.v.items():
                    if sid != name: continue
                    pres = lambda ss: any(iou({"start": a, "end": b}, s) >= 0.5 for s in ss)
                    if not pres(c0[name]): continue
                    gone = not pres(sv)
                    if verdict == "real": real_n += 1; real_lost += gone
                    elif verdict in ("not", "short"): nr_n += 1; nr += gone
                for c, (sid, a, b) in scen.items():
                    if sid != name: continue
                    pres = lambda ss: any(iou({"start": a, "end": b}, s) >= 0.5 for s in ss)
                    if pres(c0[name]): fk_n += 1; fk += not pres(sv)
        return dict(lost_dev=lost_dev, n_dev=n_dev, real_lost=real_lost, real_n=real_n, fk=fk, fk_n=fk_n, nr=nr, nr_n=nr_n, seg=seg, seg0=seg0)

    def show(tag, r):
        print(f"{tag:28s} dev lost {r['lost_dev']}/{r['n_dev']}  real field lost {r['real_lost']}/{r['real_n']}  "
              f"fakes removed {r['fk']}/{r['fk_n']}  not-real removed {r['nr']}/{r['nr_n']}  segments {r['seg0']}->{r['seg']}")
    field = sorted({u[1] for u in units if u[0] == "field"})
    fold_of = {s: idx % 5 for idx, s in enumerate(field)}
    def score_on(cfg, pred):
        return collections.Counter(score(cfg, pred))

    agg = collections.Counter(); chosen_all = []
    for fold in range(5):
        is_held = lambda kind, name: kind == "field" and fold_of[name] == fold
        is_tune = lambda kind, name: not is_held(kind, name)
        best = None
        for cfg in GRID:
            r = score_on(cfg, is_tune)
            key = (r["lost_dev"] + r["real_lost"], -r["fk"], sum(abs(a - b) / max(b, 1) for a, b in zip(cfg, D1)))
            if best is None or key < best[0]: best = (key, cfg)
        cfg = best[1]; chosen_all.append(cfg)
        r = score_on(cfg, is_held); base0 = score_on(None, is_held)
        print(f"fold {fold}: chose {cfg}  held-out real lost {r['real_lost']}/{r['real_n']}  fakes {r['fk']}/{r['fk_n']}  "
              f"not-real {r['nr']}/{r['nr_n']}  (C0 present: real {base0['real_n']})")
        for k2, v in r.items(): agg[k2] += v
    print(f"\nSUMMED held-out: real field clips lost {agg['real_lost']}/{agg['real_n']}  fakes removed {agg['fk']}/{agg['fk_n']}  "
          f"not-real removed {agg['nr']}/{agg['nr_n']}  segments {agg['seg0']}->{agg['seg']}")
    final = collections.Counter(chosen_all).most_common(1)[0][0]
    dev = score_on(final, lambda kind, name: kind == "dev")
    print(f"most-chosen config {final}: graded dev lost {dev['lost_dev']}/{dev['n_dev']}")
    ok = (agg["real_lost"] <= 3 and dev["lost_dev"] <= 5 and agg["fk"] >= 0.6 * agg["fk_n"] and agg["nr"] >= 0.5 * agg["nr_n"])
    print(f"BAR: real lost <= 3 ({agg['real_lost']}), dev lost <= 5 ({dev['lost_dev']}), fakes >= 60% ({agg['fk']}/{agg['fk_n']}), "
          f"not-real >= 50% ({agg['nr']}/{agg['nr_n']}) -> {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    main()
