"""Test C evaluation: candidate pool at a LOWER heatmap threshold, chosen by a combined
confidence + physics score (PIC-226 / PIC-228). Pre-registered; written before inference ran.

Variants (parameters fixed now, not tuned):
  C0  production: top-1 blob at threshold 0.5 (cache/topk), src.track.track_ball. Gate: must
      reproduce Test B's V0 on the same windows.
  C1  pool at threshold 0.25, up to 5 blobs (cache/topk_t25), existing track_ball unchanged.
      Isolates what a lower threshold alone does.
  C2  C1 pool + scripts/track_associate.py: score = 0.5 * confidence + 0.5 * proximity to the
      last/predicted position; candidates beyond max_jump 150 px of both are never usable.
  C3  C2 with a constant-velocity Kalman prediction and coasting at most 3 frames.

PASS RULE per variant (all), same as Test B: (1) zero of the hand-graded dev rallies lost;
(2) zero judged real field clips lost; (3) >= 4 of the 8 scenery-verified fakes removed
(O, 201, 202, 203, 204, 205, 207, 209); (4) pooled chance q1>q2 not > 0.03 below C0;
(5) detected rallies in the windows rise by <= 10%.
Windows only (8 s before, 3 s after each clip); frames outside are empty.
"""
import collections, csv, glob, json, math, os, statistics, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import validate_absolute_ranking as base
import summarise_top_sample as S
from eval.harness import iou
from src.ball import net_line_y, crossing_times, cluster_crossings
from src.calib import court_wedge
from src.select import frame_speeds, net_width_px, score_segments
from src.track import track_ball
from track_associate import track_associate

FPS = 30.0
SCEN = {"O", "201", "202", "203", "204", "205", "207", "209"}
VAR = {
    "C0": None,   # production: top-1 at threshold 0.5 (cache/topk), src.track.track_ball
    "C1": None,   # pool at threshold 0.25, top-5 (cache/topk_t25), existing track_ball
    "C2": lambda fr: track_associate(fr, max_jump=150, reset_after=15, w_c=0.5, w_d=0.5),
    "C3": lambda fr: track_associate(fr, max_jump=150, reset_after=15, w_c=0.5, w_d=0.5, kalman=True, coast=3),
}

def load_topk(path):
    d = collections.defaultdict(list)
    for r in csv.DictReader(open(path)):
        d[int(r["Frame"])].append((int(r["Rank"]), float(r["X"]), float(r["Y"]), float(r["Conf"])))
    return d

def run(sid_or_name, csv_prod, calib, topk_path, n_frames):
    base_path = topk_path.replace("topk_t25", "topk")
    wedge = court_wedge(calib)
    f_top1 = [[] for _ in range(n_frames)]; f_all = [[] for _ in range(n_frames)]
    for f, c in load_topk(base_path).items():
        if f >= n_frames: continue
        c.sort()
        f_top1[f] = [(c[0][1], c[0][2], c[0][3])] if wedge(c[0][1], c[0][2]) else []
    for f, c in load_topk(topk_path).items():
        if f >= n_frames: continue
        c.sort()
        f_all[f] = [(x, y, p) for _, x, y, p in c if wedge(x, y)]
    times = [i / FPS for i in range(n_frames)]
    res = {}
    for v in VAR:
        if v == "C0": ys = track_ball(f_top1, max_jump=150, reset_after=15)
        elif v == "C1": ys = track_ball(f_all, max_jump=150, reset_after=15)
        else: ys = VAR[v](f_all)
        cr = crossing_times(list(zip(times, ys)), net_y=net_line_y(calib), band=0.0)
        segs = cluster_crossings(cr, gap_sec=base.GAP_SEC, min_crossings=base.MIN_CROSSINGS)
        raw = sorted([(i / FPS, c[0][0], c[0][1]) for i, c in enumerate(f_top1) if c], key=lambda p: p[0])
        res[v] = {"segs": segs, "cr": cr, "speeds": frame_speeds(raw), "ys": ys}
    return res

def main():
    results = {}                      # unit -> {variant: ...}
    # ---- dev videos
    VIDEO_N = {}
    for name, csvp, calibp, labp, wend in base.SESSIONS:
        tp = f"cache/topk_t25/{name}.csv"
        if not os.path.exists(tp): print("missing", tp); continue
        n = sum(1 for _ in open(csvp)) - 1
        results[("dev", name)] = (run(name, csvp, json.load(open(calibp)), tp, n), json.load(open(calibp)), labp, wend)
    # ---- field sessions
    for p in sorted(glob.glob("cache/pgc_fieldtest/*.csv")):
        sid = os.path.basename(p)[:-4]; tp = f"cache/topk_t25/{sid[:8]}.csv"
        if not os.path.exists(tp): continue
        calib = json.load(open(f"cache/pgc_fieldtest/{sid}.calib.json")); n = sum(1 for _ in open(p)) - 1
        results[("field", sid)] = (run(sid, p, calib, tp, n), calib, None, None)
    print(f"units evaluated: {len(results)} ({sum(1 for k in results if k[0]=='dev')} dev, {sum(1 for k in results if k[0]=='field')} field)\n")

    # ---- operator verdicts as windows
    bk = {r["clip"]: r for r in csv.DictReader(open("cache/blind_check_key.csv"))}
    hk = {r["clip"]: r for r in csv.DictReader(open("cache/hotspot_check_key.csv"))}
    def sid_of(pre): return [x.split("/")[-1][:-4] for x in glob.glob("cache/pgc_fieldtest/*.csv") if x.split("/")[-1].startswith(pre)][0]
    scen = {}
    for c in SCEN:
        r = bk["O"] if c == "O" else hk[c]
        pre = r["video"].split(":")[-1] if c == "O" else r["session"]
        scen[c] = (sid_of(pre), float(r["start"]), float(r["end"]))
    def present(unit_res, v, a, b):
        return any(iou({"start": a, "end": b}, s) >= 0.5 for s in unit_res[v]["segs"])

    out = {}
    for v in VAR:
        lost_dev = n_dev = 0; pool = ([], []); pool0 = ([], [])
        for (kind, key), (res, calib, labp, wend) in results.items():
            if kind != "dev": continue
            labs = [r for r in (json.loads(l) for l in open(labp) if l.strip()) if r.get("quality") in (1, 2) and (wend is None or r["end"] <= wend)]
            npx = net_width_px(calib)
            sc = lambda vv: {(r["start"], r["end"]): r["score"] for r in score_segments(res[vv]["segs"], res[vv]["cr"], res[vv]["speeds"], npx)}
            s0, sv = sc("C0"), sc(v)
            segs0 = res["C0"]["segs"]; segsv = res[v]["segs"]
            for lab in labs:
                b0, bv = base.best_match(lab, segs0), base.best_match(lab, segsv)
                if b0 is not None:
                    n_dev += 1; pool0[lab["quality"] - 1].append(s0[(b0["start"], b0["end"])])
                    lost_dev += bv is None
                if bv is not None: pool[lab["quality"] - 1].append(sv[(bv["start"], bv["end"])])
        # judged field clips
        real_lost = []; real_n = 0; not_removed = []; not_n = 0
        for (sid, a, b), (verdict, why) in S.v.items():
            u = results.get(("field", sid))
            if not u: continue
            res = u[0]
            if not present(res, "C0", a, b): continue
            gone = not present(res, v, a, b)
            if verdict == "real": real_n += 1; real_lost += [(sid[:8], round(a))] if gone else []
            elif verdict in ("not", "short"): not_n += 1; not_removed += [(sid[:8], round(a))] if gone else []
        scen_removed = []
        for c, (sid, a, b) in scen.items():
            u = results.get(("field", sid))
            if u and present(u[0], "C0", a, b) and not present(u[0], v, a, b): scen_removed.append(c)
        seg0 = sum(len(r[0]["C0"]["segs"]) for r in results.values()); segv = sum(len(r[0][v]["segs"]) for r in results.values())
        c0, cv = base.chance_q1_beats_q2(*pool0), base.chance_q1_beats_q2(*pool)
        p1, p2, p3 = lost_dev == 0, not real_lost, len(scen_removed) >= 4
        p4, p5 = cv >= c0 - 0.03, segv <= seg0 * 1.10
        out[v] = (p1, p2, p3, p4, p5)
        print(f"{v:4s} | graded dev lost {lost_dev}/{n_dev} | real field clips lost {len(real_lost)}/{real_n} {real_lost[:4]} | "
              f"scenery fakes removed {len(scen_removed)}/8 {sorted(scen_removed)} | not-real removed {len(not_removed)}/{not_n} | "
              f"chance {c0:.3f}->{cv:.3f} | segments {seg0}->{segv}")
        print(f"       rule: (1){'OK' if p1 else 'FAIL'} (2){'OK' if p2 else 'FAIL'} (3){'OK' if p3 else 'FAIL'} (4){'OK' if p4 else 'FAIL'} (5){'OK' if p5 else 'FAIL'}"
              f"  => {'PASS' if all(out[v]) else 'FAIL'}")
    # reproducibility of C0 vs cached production, and candidate availability
    print("\nV0 vs cached production (graded dev rallies matched):", end=" ")
    m_prod = m_v0 = 0
    for (kind, key), (res, calib, labp, wend) in results.items():
        if kind != "dev": continue
        name = key; csvp = [s[1] for s in base.SESSIONS if s[0] == name][0]
        ps, _, _ = base.detect(csvp, calib)
        labs = [r for r in (json.loads(l) for l in open(labp) if l.strip()) if r.get("quality") in (1, 2) and (wend is None or r["end"] <= wend)]
        for lab in labs:
            m_prod += base.best_match(lab, [s for s in ps if wend is None or s["end"] <= wend]) is not None
            m_v0 += base.best_match(lab, res["C0"]["segs"]) is not None
    print(f"production {m_prod}, C0 on windows {m_v0}")
    tot = multi = 0
    for tp in glob.glob("cache/topk_t25/*.csv"):
        if tp.endswith("_sanity.csv"): continue
        d = load_topk(tp); tot += len(d); multi += sum(1 for c in d.values() if len(c) > 1)
    print(f"frames with any blob: {tot}; with 2+ blobs: {multi} ({multi/max(1,tot):.1%})")

if __name__ == "__main__":
    main()
