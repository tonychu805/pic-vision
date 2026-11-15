"""Where does the serve first touch the ground? The simple version (PIC-226).

Operator, 2026-10-13: "we are simply trying to find where the ball lands at the
serve." The 3D arc fit (serve_landing_probe.py) failed its bar. This is the
direct route: find the first ground contact after the serve in the image, and
place it on the court with the calibration homography (image -> court feet),
which is exact for a ball on the floor. No arc fit, no camera pose.

Same 25 eligible judged fresh clips and verdicts as serve_landing_probe.py
(18 good serves, 7 faults: 301 net, 302 adjacent, 306 net, 308 kitchen, 316 out,
324 net, 328 net; excluded 311, 314, 319, 320, 322).

Rules, fixed BEFORE running (nothing tuned on results):
 1. Window: frames from (detected rally start - 2.5 s) to (start + 2.0 s).
 2. Points: track_ball (max_jump 150, reset_after 15) over detections gated by
    court_wedge with margin_px = 400 (wide, so serves landing out of bounds are
    not thrown away by the usual 160 px gate).
 3. Bounce candidate: a tracked frame whose image-y is the largest (lowest on
    screen) among tracked points within +-6 frames, with >= 2 tracked points on
    each side in that span, and at least 8 px lower than the minimum on each
    side (the ball comes down and goes back up). Candidates within 5 frames of
    each other collapse to the lowest.
 4. Server side from the first tracked point in the window projected through
    the homography: court y < 14 -> server on the near side (receiving half
    y > 22); y > 30 -> far side; otherwise no estimate.
 5. The serve landing = the earliest candidate whose projected court position is
    more than 6 ft from the server's baseline (this skips the contact and any
    bounce at the server's feet). None -> no estimate.
 6. Call from the projected landing (x, y): NET if it is on the server's half
    of the net; OUT if it is outside x 0..20 or beyond the far baseline;
    KITCHEN if it is within 7 ft of the net on the receiving half; ADJACENT if
    it is in the receiving service court on the same side of the centre line
    as the server's launch x (only when the first tracked point is within 8 ft
    of the server's baseline); otherwise IN. A landing within 2.0 ft of any
    boundary it is judged against -> no estimate.

BAR, fixed before running (same as the arc probe):
 (1) an estimate for >= 60% of the 25 serves;
 (2) among those: >= 50% of the true faults called a fault AND <= 25% of the
     true good serves called a fault.
 Fault-type accuracy reported, not gated. 25 clips, one venue: a pass is a hint.
Run: .venv/bin/python scripts/serve_bounce_probe.py
"""
import csv, json, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
import cv2
from src.calib import court_wedge
from src.track import track_ball
from src.tracknet import load_predictions

FPS = 30.0
V = dict(x.split("=") for x in "301=not 302=not 303=real 304=short 305=short 306=not 307=real 308=not 309=real 310=real 311=not 312=short 313=real 314=not 315=real 316=not 317=real 318=real 319=not 320=not 321=real 322=not 323=real 324=not 325=real 326=real 327=real 328=not 329=real 330=real".split())
FAULTS = {"301": "net", "302": "adjacent", "306": "net", "308": "kitchen", "316": "out", "324": "net", "328": "net"}
EXCLUDE = {"311", "314", "319", "320", "322"}
PRE, POST, SPAN, PROM, SKIP_FT, MARGIN = 2.5, 2.0, 6, 8.0, 6.0, 2.0
NET_Y, COURT_X, COURT_Y, KITCHEN = 22.0, 20.0, 44.0, 7.0


def candidates(xs, ys, a, b):
    """Bounce candidates (frame) inside [a, b] from tracked image points."""
    pts = {i: (xs[i], ys[i]) for i in range(a, b + 1) if ys[i] is not None and xs[i] is not None}
    out = []
    for f, (x, y) in pts.items():
        prev = [pts[g][1] for g in range(f - SPAN, f) if g in pts]
        nxt = [pts[g][1] for g in range(f + 1, f + SPAN + 1) if g in pts]
        if len(prev) < 2 or len(nxt) < 2:
            continue
        if y >= max(prev + nxt) and y - min(prev) >= PROM and y - min(nxt) >= PROM:
            out.append(f)
    out.sort()
    merged = []
    for f in out:
        if merged and f - merged[-1][-1] <= 5:
            merged[-1].append(f)
        else:
            merged.append([f])
    return [max(g, key=lambda i: pts[i][1]) for g in merged], pts


def classify(first_xy, land_xy):
    x0, y0 = first_xy
    if y0 < 14.0:
        near = True
    elif y0 > 30.0:
        near = False
    else:
        return "NONE", f"server side unknown (first point y={y0:.0f})"
    xl, yl = land_xy
    depth = (yl - NET_Y) if near else (NET_Y - yl)
    far_base = COURT_Y if near else 0.0
    if depth < 0:
        return "NET", f"lands on the server's half (y={yl:.0f})"
    edge = min(abs(xl), abs(xl - COURT_X), abs(yl - far_base))
    if edge < MARGIN:
        return "NONE", f"near a boundary (x={xl:.0f}, y={yl:.0f})"
    if xl < 0 or xl > COURT_X or (yl > COURT_Y if near else yl < 0.0):
        return "OUT", f"lands x={xl:.0f}, y={yl:.0f}"
    if abs(depth - KITCHEN) < MARGIN:
        return "NONE", f"near the kitchen line (depth {depth:.1f} ft)"
    if depth < KITCHEN:
        return "KITCHEN", f"lands {depth:.0f} ft past the net"
    base_dist = y0 if near else COURT_Y - y0
    if base_dist <= 8.0:
        if abs(xl - 10.0) < MARGIN:
            return "NONE", f"near the centre line (x={xl:.0f})"
        if (x0 < 10.0) == (xl < 10.0):
            return "ADJACENT", f"launch x={x0:.0f}, lands x={xl:.0f}"
    return "IN", f"lands x={xl:.0f}, y={yl:.0f}"


def main():
    rows = list(csv.DictReader(open("cache/fresh_sample_key.csv")))
    cache, out = {}, []
    for r in rows:
        clip = r["clip"]
        if clip in EXCLUDE:
            continue
        seg = r["segment"]
        if seg not in cache:
            meta = json.load(open(f"cache/fresh/{seg}.meta.json"))
            calib = json.load(open(meta["calib"]))
            H = np.array(calib["homography"], dtype=np.float32)
            tr = load_predictions(f"cache/fresh/{seg}.csv", FPS)
            wedge = court_wedge(calib, margin_px=400.0)
            frames = [[(x, y, c if c is not None else 1.0)] if (x is not None and wedge(x, y)) else []
                      for _, x, y, _w, _h, c in tr]
            ys, xs = track_ball(frames, max_jump=150, reset_after=15, return_x=True)
            cache[seg] = (H, xs, ys)
        H, xs, ys = cache[seg]
        proj = lambda x, y: tuple(float(v) for v in cv2.perspectiveTransform(
            np.array([[[x, y]]], dtype=np.float32), H)[0, 0])
        truth = "fault" if clip in FAULTS else "in"
        s0 = float(r["start"])
        a, b = max(0, int((s0 - PRE) * FPS)), min(len(ys) - 1, int((s0 + POST) * FPS))
        first = next((i for i in range(a, b + 1) if ys[i] is not None and xs[i] is not None), None)
        if first is None:
            out.append((clip, truth, "NONE", "no tracked points in the window"))
            continue
        fx, fy = proj(xs[first], ys[first])
        cands, pts = candidates(xs, ys, a, b)
        near = fy < 14.0
        pick = None
        for f in cands:
            if f < first:
                continue
            cx, cy = proj(*pts[f])
            dist_from_server_base = cy if near else COURT_Y - cy
            if dist_from_server_base > SKIP_FT:
                pick = (f, cx, cy)
                break
        if pick is None:
            out.append((clip, truth, "NONE", f"no bounce candidate ({len(cands)} in window)"))
            continue
        lab, detail = classify((fx, fy), (pick[1], pick[2]))
        out.append((clip, truth, lab, detail))

    print(f"{'clip':>4s} {'truth':>6s} {'kind':>9s} {'call':>9s}  detail")
    for clip, truth, lab, detail in out:
        kind = FAULTS.get(clip, V[clip] if V[clip] != "not" else "?")
        print(f"{clip:>4s} {truth:>6s} {kind:>9s} {lab:>9s}  {detail}")
    est = [o for o in out if o[2] != "NONE"]
    n = len(out)
    is_fault = lambda o: o[2] in ("NET", "OUT", "KITCHEN", "ADJACENT")
    tf = [o for o in est if o[1] == "fault"]; tg = [o for o in est if o[1] == "in"]
    cov = len(est) / n
    fr = sum(map(is_fault, tf)) / len(tf) if tf else float("nan")
    ff = sum(map(is_fault, tg)) / len(tg) if tg else float("nan")
    type_ok = sum(1 for o in tf if o[2].lower() == FAULTS[o[0]])
    print(f"\neligible {n} (faults {sum(1 for o in out if o[1] == 'fault')}, good serves {sum(1 for o in out if o[1] == 'in')})")
    print(f"(1) estimate produced for {len(est)}/{n} = {cov:.0%}   (bar >= 60%)")
    print(f"(2) true faults called a fault {sum(map(is_fault, tf))}/{len(tf)} = {fr:.0%} (bar >= 50%);"
          f"  good serves called a fault {sum(map(is_fault, tg))}/{len(tg)} = {ff:.0%} (bar <= 25%)")
    print(f"    fault type right (not gated): {type_ok}/{len(tf)}")
    ok = cov >= 0.60 and tf and tg and fr >= 0.50 and ff <= 0.25
    print(f"\nBAR: {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    main()
