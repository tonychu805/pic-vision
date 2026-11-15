"""Score the static bright-blob suppression test (PIC-226).

Sessions: the two 10-minute PGC sessions behind the operator's scenery check
(7ace7db9, 34fab44c; cache/pgc_fieldtest). Judged clips (operator, playback):
  scenery set  = the 9 clips of the 2026-10-12 hotspot check (verdict 'not' or
                 'short'; >= 30% of tracked points in fixed bright spots; 8 of 8 answered
                 contained light, glare or dots);
  real set     = the judged 'real' clips in the same two sessions.
Arms: control = k14 on the unmodified frames (same code path), suppress = k14 after
scripts/infer_k14_suppress.py preprocessing. A judged clip is 'found' when a detected
segment overlaps it at IoU >= 0.5 (same pipeline: court_wedge, track_ball, gap 3.0, min 6).

BAR, fixed before running: suppression HELPS only if it removes at least half of the
scenery clips the control finds AND loses none of the real clips the control finds.
n is tiny (9 and about 6): a pass is a hint. Also reported: the share of tracked points
inside fixed bright spots, per arm, and the number of detected segments.
"""
import contextlib, csv, io, json, os, sys, collections
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from eval.harness import iou
from src.ball import crossing_times, cluster_crossings, net_line_y
from src.calib import court_wedge
from src.track import track_ball
from src.tracknet import load_predictions

with contextlib.redirect_stdout(io.StringIO()):
    import summarise_top_sample as S

SESS = ["7ace7db9", "34fab44c"]
DIR = "cache/pgc_fieldtest"


def full_id(prefix):
    return next(f[:-4] for f in os.listdir(DIR) if f.startswith(prefix) and f.endswith(".mp4"))


def segments_and_track(csvp, calib):
    tr = load_predictions(csvp, 30.0); w = court_wedge(calib)
    times = [t for t, *_ in tr]
    fr = [[(x, y, c if c is not None else 1.0)] if (x is not None and w(x, y)) else [] for _, x, y, _w, _h, c in tr]
    ys, xs = track_ball(fr, max_jump=150, reset_after=15, return_x=True)
    cr = crossing_times(list(zip(times, ys)), net_y=net_line_y(calib), band=0.0)
    segs = cluster_crossings(cr, gap_sec=3.0, min_crossings=6)
    return segs, xs, ys, tr


def main():
    hot = {(r["session"], round(float(r["start"]), 2), round(float(r["end"]), 2)): r for r in csv.DictReader(open("cache/hotspot_check_key.csv"))}
    SQ = 12
    res = collections.defaultdict(lambda: collections.defaultdict(list))
    seg_count = collections.defaultdict(int)
    share = collections.defaultdict(list)
    for pre in SESS:
        sid = full_id(pre); calib = json.load(open(f"{DIR}/{sid}.calib.json"))
        arms = {"control": f"cache/arms/suppress_{pre}_control.csv", "suppress": f"cache/arms/suppress_{pre}_suppress.csv"}
        # judged clips of this session
        clips = []
        for (s, a, b), (v, why) in S.v.items():
            if s != sid: continue
            key = (pre, round(a, 2), round(b, 2))
            if key in hot: clips.append(("scenery", a, b))
            elif v == "real": clips.append(("real", a, b))
        for arm, p in arms.items():
            if not os.path.exists(p):
                print(f"missing {p}"); continue
            segs, xs, ys, tr = segments_and_track(p, calib)
            seg_count[arm] += len(segs)
            import statistics
            from collections import Counter
            cnt = Counter((round(x / SQ), round(y / SQ)) for _, x, y, *_ in tr if x is not None)
            med = statistics.median(cnt.values()) if cnt else 1
            hotsq = {s for s, n in cnt.items() if n >= 20 * med}
            for kind, a, b in clips:
                best = max((iou({"start": a, "end": b}, s) for s in segs), default=0.0)
                res[arm][kind].append(best >= 0.5)
                pts = [(round(xs[i] / SQ), round(ys[i] / SQ)) for i, (t, *_r) in enumerate(tr) if ys[i] is not None and a <= t <= b]
                if len(pts) >= 8 and kind == "scenery":
                    share[arm].append(sum(1 for q in pts if q in hotsq) / len(pts))
    print(f"{'arm':9s} {'segments':>9s} {'scenery clips found':>20s} {'real clips found':>17s} {'median fixed-spot share (scenery clips)':>40s}")
    for arm in ("control", "suppress"):
        sc, rl = res[arm]["scenery"], res[arm]["real"]
        ms = sorted(share[arm])[len(share[arm]) // 2] if share[arm] else float("nan")
        print(f"{arm:9s} {seg_count[arm]:9d} {sum(sc):9d} / {len(sc):2d}        {sum(rl):9d} / {len(rl):2d}      {ms:30.0%}")
    c_sc, s_sc = sum(res["control"]["scenery"]), sum(res["suppress"]["scenery"])
    c_rl = res["control"]["real"]; s_rl = res["suppress"]["real"]
    lost = sum(1 for c, s in zip(c_rl, s_rl) if c and not s)
    ok = (c_sc > 0 and (c_sc - s_sc) >= 0.5 * c_sc) and lost == 0
    print(f"\nscenery clips removed: {c_sc - s_sc} of {c_sc} found by control; real clips lost: {lost}")
    print(f"BAR: {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    main()
