"""How much of the real ball bouncing does the system see, and how accurate is where it lands?
(bounce-labelling pilot, 2026-10-14, PIC-195/204-206)

Input: the operator's hand labels from label_bounce_web.py (eval/labels/bounces/labels.jsonl),
made blind to the detector. For every labelled bounce, with a +-3 frame window:
  seen     a raw k14 detection exists near the bounce frame (anywhere in the image)
  tracked  the tracker (track_ball, as in serve_bounce_probe.py) accepted a point there
  found    a bounce candidate (serve_bounce_probe.candidates, rules unchanged) lies within
           15 px of where the operator marked the floor contact
and the court error in feet of the nearest tracked point / candidate (image -> court
homography; exact for a ball on the floor). Reported per set (pgc, public) and for the
near and far half of the court. Clips not marked "complete" are skipped (recall needs every
bounce marked).

BAR, fixed BEFORE any labels exist. A zone-level landing map (short / deep, left / right,
kitchen or not) is viable on the PGC set if ALL hold:
  (1) tracked >= 50% of labelled bounces,
  (2) found >= 40% of labelled bounces,
  (3) median court error of the found candidates <= 1.5 ft on the near half.
If (1) fails, the limit is the detector or camera angle, not the bounce finder. Line calls
are out of scope (calibration error 0.2-0.4 ft, a ball 0.24 ft). Public footage is the
ceiling, not the target. Small sample (about 18 PGC clips, one venue): a pass is a lead.
Run: .venv/bin/python scripts/eval_bounce_recovery.py
"""
import json, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
from src.bounce_eval import near_half, percentile, recover
from src.calib import court_wedge
from src.track import track_ball
from src.tracknet import load_predictions
import serve_bounce_probe as sbp

FPS = 30.0
LABELS = "eval/labels/bounces/labels.jsonl"
SAMPLE = "eval/labels/bounces/sample.json"


def clip_points(clip):
    calib = json.load(open(clip["calib"]))
    tr = load_predictions(clip["csv"], FPS)
    raw = {i: (x, y) for i, (_, x, y, *_r) in enumerate(tr) if x is not None}
    wedge = court_wedge(calib, margin_px=400.0)
    frames = [[(x, y, c if c is not None else 1.0)] if (x is not None and wedge(x, y)) else []
              for _, x, y, _w, _h, c in tr]
    ys, xs = track_ball(frames, max_jump=150, reset_after=15, return_x=True)
    tracked = {i: (xs[i], ys[i]) for i in range(len(ys)) if ys[i] is not None and xs[i] is not None}
    cand_frames, pts = sbp.candidates(xs, ys, 0, len(ys) - 1)
    cands = {f: pts[f] for f in cand_frames}
    return np.array(calib["homography"], dtype=float), raw, tracked, cands


def main():
    sample = {c["id"]: c for c in json.load(open(SAMPLE))["clips"]}
    rows = [json.loads(l) for l in open(LABELS) if l.strip()]
    done = [r for r in rows if r.get("complete")]
    print(f"labelled clips: {len(rows)}, marked complete: {len(done)}")
    res = []   # (set, half, recover-dict)
    for r in done:
        clip = sample[r["clip"]]
        H, raw, tracked, cands = clip_points(clip)
        for b in r["bounces"]:
            rec = recover({"frame": b["frame"], "x": b["x"], "y": b["y"], "visible": b.get("visible", True)},
                          raw, tracked, cands, H)
            res.append((r["set"], "near" if near_half(H, b["x"], b["y"]) else "far", b.get("visible", True), rec))
    if not res:
        print("no complete clips yet"); return
    print(f"\n{'group':18s} {'n':>4s} {'seen':>6s} {'tracked':>8s} {'found':>6s} {'med err ft (found)':>19s} {'p90':>6s}")
    for s in ("pgc", "public"):
        for half in ("all", "near", "far"):
            g = [x for x in res if x[0] == s and (half == "all" or x[1] == half)]
            if not g:
                continue
            n = len(g)
            f = lambda k: sum(1 for x in g if x[3][k]) / n
            errs = [x[3]["cand_err_ft"] for x in g if x[3]["found"]]
            med, p90 = percentile(errs, 0.5), percentile(errs, 0.9)
            print(f"{s + ' ' + half:18s} {n:4d} {f('seen'):6.0%} {f('tracked'):8.0%} {f('found'):6.0%} "
                  f"{('%.2f' % med) if med is not None else '-':>19s} {('%.2f' % p90) if p90 is not None else '-':>6s}")
    unseen = sum(1 for x in res if not x[2])
    print(f"\nbounces marked 'ball not visible' (shift+click): {unseen} of {len(res)}")
    p = [x for x in res if x[0] == "pgc"]
    if p:
        t = sum(1 for x in p if x[3]["tracked"]) / len(p)
        fd = sum(1 for x in p if x[3]["found"]) / len(p)
        near_errs = [x[3]["cand_err_ft"] for x in p if x[3]["found"] and x[1] == "near"]
        med = percentile(near_errs, 0.5)
        ok = t >= 0.5 and fd >= 0.4 and med is not None and med <= 1.5
        print(f"\nBAR (pgc): tracked {t:.0%} (>=50%), found {fd:.0%} (>=40%), near-half median error "
              f"{('%.2f ft' % med) if med is not None else 'n/a'} (<=1.5 ft)  ->  {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    main()
