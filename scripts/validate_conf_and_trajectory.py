"""Two alternatives to the failed scenery mask (PIC-226), offline only.

 1. HIGH CONFIDENCE ONLY: drop every detection whose TrackNet confidence is
    below a cut-off (0.60, 0.65) before tracking.
 2. TRAJECTORY CHECK ("no teleport back"): drop a detection that returns to
    within 6 px of a point seen 2-3 detections earlier (within 1 s) right after
    jumping >= 60 px away -- a ball cannot go A -> B -> A on the same pixels.
    A fixed bright spot flickering against another one does exactly this.

Same PASS RULE as scripts/validate_scenery_mask.py, written before running:
  (a) zero hand-graded rallies lost; (b) clip O no longer detected;
  (c) field clips K, L, N, P, Q, R all still detected; (d) pooled chance
  quality:1 > quality:2 under the shipped score not >0.03 below unfiltered.
IMG_7743 not read.
"""
import csv, glob, json, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import validate_absolute_ranking as base
from eval.harness import iou
from src.ball import net_line_y, crossing_times, cluster_crossings
from src.calib import court_wedge
from src.select import frame_speeds, net_width_px, score_segments
from src.track import track_ball
from src.tracknet import load_predictions

REAL = ("K", "L", "N", "P", "Q", "R")

def detect(csv_path, calib, conf_min=None, no_teleport_back=False):
    in_court = court_wedge(calib)
    track = load_predictions(csv_path, base.FPS)
    keep = [False] * len(track)
    recent = []                      # last visible (idx, x, y), regardless of acceptance
    for i, (t, x, y, w, h, c) in enumerate(track):
        if x is None or not in_court(x, y):
            continue
        ok = True
        if conf_min is not None and (c is None or c < conf_min):
            ok = False
        if ok and no_teleport_back and len(recent) >= 3:
            (_, x1, y1), (j2, x2, y2), (j3, x3, y3) = recent[-1], recent[-2], recent[-3]
            far_prev = ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5 >= 60
            for (jj, xx, yy) in (recent[-2], recent[-3]):
                if far_prev and i - jj <= 30 and ((x - xx) ** 2 + (y - yy) ** 2) ** 0.5 <= 6:
                    ok = False
        keep[i] = ok
        recent.append((i, x, y))
    times = [t for t, *_ in track]
    frames = [[(x, y, c if c is not None else 1.0)] if keep[i] else [] for i, (_, x, y, w, h, c) in enumerate(track)]
    ys = track_ball(frames, max_jump=150, reset_after=15)
    crossed = crossing_times(list(zip(times, ys)), net_y=net_line_y(calib), band=0.0)
    segs = cluster_crossings(crossed, gap_sec=base.GAP_SEC, min_crossings=base.MIN_CROSSINGS)
    raw = sorted([(t, x, y) for i, (t, x, y, *_r) in enumerate(track) if keep[i]], key=lambda p: p[0])
    return segs, crossed, frame_speeds(raw)

VARIANTS = {"conf>=0.60": dict(conf_min=0.60), "conf>=0.65": dict(conf_min=0.65), "no-teleport-back": dict(no_teleport_back=True)}

def main():
    key = {r["clip"]: r for r in csv.DictReader(open("cache/blind_check_key.csv"))}
    field = {}
    for clip in REAL + ("O", "M"):
        k = key[clip]
        sid = [p.split("/")[-1][:-4] for p in glob.glob("cache/pgc_fieldtest/*.csv")
               if p.split("/")[-1].startswith(k["video"].split(":")[-1])][0]
        field[clip] = (sid, {"start": float(k["start"]), "end": float(k["end"])})
    for vname, kw in VARIANTS.items():
        lost = gained = nb = na = 0
        pooled = {"b": ([], []), "m": ([], [])}
        for name, csvp, calibp, labp, wend in base.SESSIONS:
            calib = json.load(open(calibp))
            bs, bc, bsp = detect(csvp, calib)
            ms, mc, msp = detect(csvp, calib, **kw)
            if wend is not None:
                bs = [s for s in bs if s["end"] <= wend]; ms = [s for s in ms if s["end"] <= wend]
            npx = net_width_px(calib)
            labs = [r for r in (json.loads(l) for l in open(labp) if l.strip())
                    if r.get("quality") in (1, 2) and (wend is None or r["end"] <= wend)]
            bsc = {(r["start"], r["end"]): r["score"] for r in score_segments(bs, bc, bsp, npx)}
            msc = {(r["start"], r["end"]): r["score"] for r in score_segments(ms, mc, msp, npx)}
            for lab in labs:
                b, m = base.best_match(lab, bs), base.best_match(lab, ms)
                if b is not None:
                    nb += 1; pooled["b"][lab["quality"] - 1].append(bsc[(b["start"], b["end"])])
                if m is not None:
                    na += 1; pooled["m"][lab["quality"] - 1].append(msc[(m["start"], m["end"])])
                lost += (b is not None and m is None); gained += (b is None and m is not None)
        cb, cm = base.chance_q1_beats_q2(*pooled["b"]), base.chance_q1_beats_q2(*pooled["m"])
        status = {}
        for clip, (sid, win) in field.items():
            segs, *_ = detect(f"cache/pgc_fieldtest/{sid}.csv", json.load(open(f"cache/pgc_fieldtest/{sid}.calib.json")), **kw)
            status[clip] = any(iou(win, s) >= 0.5 for s in segs)
        a, b_, c_, d = lost == 0, not status["O"], all(status[x] for x in REAL), cm >= cb - 0.03
        print(f"{vname:17s} graded {nb}->{na} (lost {lost}, gained {gained}) | O {'GONE' if b_ else 'still there'} | "
              f"real field clips kept {sum(status[x] for x in REAL)}/6 | chance {cb:.3f}->{cm:.3f} | "
              f"(a){'OK' if a else 'FAIL'} (b){'OK' if b_ else 'FAIL'} (c){'OK' if c_ else 'FAIL'} (d){'OK' if d else 'FAIL'} "
              f"=> {'PASS' if a and b_ and c_ and d else 'FAIL'}")

if __name__ == "__main__":
    main()
