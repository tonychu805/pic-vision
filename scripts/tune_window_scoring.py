"""Tune whole-track window scoring (Test D2, PIC-226) WITH a held-out split. Pre-registered.

Test D1 (2026-10-15) removed all 8 scenery fakes but lost 25/60 real field clips and 33/83 graded
rallies. Diagnosis of the real rallies it dropped: points fail the flight test mostly for a poor
quadratic fit (37%), fewer than 5 points in the piece (38%), short path (24%); the speed test never
binds. So the grid varies only those three and the ball-like share.

GRID (fixed now):  RMS_PX in {6, 8, 12, 16}; MIN_PIECE in {3, 4, 5}; MIN_LEN in {40, 60, 80};
                   ball-like share in {0.3, 0.5}.        72 configs. Everything else as D1.
SPLIT (fixed now): TUNE = the 4 graded dev videos + the field sessions of the scenery fakes
                   7ace7db9 and the blind-check clip O; HELD-OUT = every other field session
                   (includes 34fab44c: scenery fakes 205, 207, 209).
SELECTION (on TUNE only): fewest real rallies lost (graded dev + real field clips); ties -> most
                   scenery fakes removed; ties -> closest to D1. The chosen config is then scored once
                   on HELD-OUT, next to production (C0) and D1.
BAR for the chosen config on HELD-OUT: zero real field clips lost and >= 2 of the held-out scenery
                   fakes removed; reported, not gated: not-real removed, segments.
Run: .venv/bin/python scripts/tune_window_scoring.py
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
            if sp != split: continue
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
    print("tune units:", sum(1 for u in units if u[2] == "tune"), " held-out units:", sum(1 for u in units if u[2] == "held"))
    show("TUNE  C0 production", score(None, "tune")); show("TUNE  D1 (6,5,80,0.5)", score(D1, "tune"))
    res = []
    for cfg in GRID:
        r = score(cfg, "tune")
        res.append((r["lost_dev"] + r["real_lost"], -r["fk"], sum(abs(a - b) / max(b, 1) for a, b in zip(cfg, D1)), cfg, r))
    res.sort(key=lambda t: t[:3])
    print("\nbest 5 configs on TUNE (rms, min_piece, min_len, share):")
    for lost, nfk, _, cfg, r in res[:5]:
        show(str(cfg), r)
    chosen = res[0][3]
    print("\nCHOSEN:", chosen, "\n")
    show("HELD   C0 production", score(None, "held")); show("HELD   D1 (6,5,80,0.5)", score(D1, "held"))
    hr = score(chosen, "held"); show("HELD   chosen", hr)
    ok = hr["real_lost"] == 0 and hr["fk"] >= 2
    print(f"\nBAR on held-out: real field clips lost {hr['real_lost']} (need 0), fakes removed {hr['fk']}/{hr['fk_n']} (need >= 2) -> {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    main()
