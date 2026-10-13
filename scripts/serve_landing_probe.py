"""Can the 3D flight fit say where a serve came down? Probe on the judged fresh clips (PIC-226).

Question (operator, 2026-10-13): failed serves are out of bounds, net, or the
adjacent box (and the kitchen). Before building a serve detector, can the
existing flight-fitting tool (scripts/ball_court_map_3d.py: camera pose from the
calibration, ballistic arc per flight segment) recover a serve's landing well
enough to tell a fault from a good serve? Tried so far on ONE brickwall rally.

Input: the 30 judged fresh clips (cache/fresh_sample_key.csv, operator verdicts
and reasons, playback). Eligible = 25: real 15 + serve-and-return-only 3 (serve
was in; 304 = return touched the net) are "in"; the 7 faults with a stated
cause (301 net, 302 adjacent, 306 net, 308 kitchen, 316 out, 324 net, 328 net)
are "fault". Excluded: 311 (no serve), 314 (ball tossed in), 319 (practice),
320 and 322 (serve only, cut off: cannot tell whether the serve was in).

Rules, fixed BEFORE running (nothing below is tuned on results):
 1. Window: frames from (detected rally start - 2.5 s) to (start + 2.0 s),
    detections gated by court_wedge. Flight segments from segment_flights()
    with its defaults; only segments passing seg_ok() count.
 2. The serve flight = the earliest valid segment in the window whose fitted
    path covers >= 10 ft of court-y. None found -> no estimate.
 3. Landing = the fitted arc extrapolated forward from its last detection until
    z <= 0, at most 1.0 s ahead; none within 1.0 s -> no estimate.
 4. Server side from the fitted start y0: y0 < 14 ft -> server on the near
    side (receiving half y > 22); y0 > 30 -> far side (receiving half y < 22);
    otherwise no estimate. Launch x counts only if the segment starts within
    8 ft of a baseline; otherwise the adjacent box cannot be told and only the
    other faults are called.
 5. Call: NET if the arc crosses y = 22 below 2.8 ft, or ends at the net below
    4.5 ft without crossing (seg_report's rules), or lands on the server's own
    half. OUT if it lands outside x 0..20 or beyond the far baseline. KITCHEN if
    it lands within 7 ft of the net on the receiving half. ADJACENT if it lands
    in the receiving service court on the same side of the centre line as the
    launch (only when launch x is known). Otherwise IN.
    A landing within 2.0 ft of a boundary it was judged against -> no estimate
    (the calibration error is about 0.4 ft and the arc fit is worse).
 6. Calibration sanity: the net-tape image points must reconstruct at z within
    1.0 ft of 3.0 ft when intersected with the net plane; otherwise the clip is
    reported and excluded.

BAR, fixed before running (all eligible clips pooled):
 (1) an estimate (IN or a fault) for >= 60% of the 25 serves;
 (2) among those: >= 50% of the true faults are called a fault, AND <= 25% of
     the true good serves are called a fault.
 25 clips (7 faults, 18 good serves), one venue, one weekend: a pass is a hint
 for a bigger labelled set (mine the pipeline's false alarms), not a result.
 Fault-type accuracy is reported, not gated.
Run: .venv/bin/python scripts/serve_landing_probe.py
"""
import csv, json, os, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
import scripts.ball_court_map_3d as b3
from scripts.ball_trail_overlay import FPS, gated_points
from src.calib import court_wedge
from src.tracknet import load_predictions

V = dict(x.split("=") for x in "301=not 302=not 303=real 304=short 305=short 306=not 307=real 308=not 309=real 310=real 311=not 312=short 313=real 314=not 315=real 316=not 317=real 318=real 319=not 320=not 321=real 322=not 323=real 324=not 325=real 326=real 327=real 328=not 329=real 330=real".split())
FAULTS = {"301": "net", "302": "adjacent", "306": "net", "308": "kitchen", "316": "out", "324": "net", "328": "net"}
EXCLUDE = {"311", "314", "319", "320", "322"}
PRE, POST, MIN_TRAVEL, MAX_EXTRAP, MARGIN = 2.5, 2.0, 10.0, 1.0, 2.0
NET_Y, COURT_X, COURT_Y, KITCHEN = 22.0, 20.0, 44.0, 7.0


def camera_for(calib, w, h):
    cam = b3.camera_from_homography(calib["homography"], w / 2.0, h / 2.0)
    if cam is None:
        return None, "pose not recoverable"
    f, R, C = cam
    zs = []
    for u, v in calib["net_image_points"]:
        d = b3.ray_dir(u, v, f, R, w / 2.0, h / 2.0)
        if abs(d[1]) < 1e-9:
            return None, "net ray parallel to net plane"
        t = (NET_Y - C[1]) / d[1]
        zs.append(float(C[2] + t * d[2]))
    ok = all(abs(z - 3.0) <= 1.0 for z in zs)
    return (f, R, C, zs) if ok else (None, f"net posts reconstruct at z={zs[0]:.1f},{zs[1]:.1f} ft")


def landing(seg):
    """Extrapolate the arc until it reaches the floor; (x, y, seconds_ahead) or None."""
    last = seg["frames"][-1]
    for k in range(0, int(MAX_EXTRAP * FPS) + 1):
        p = b3.position(seg["P0"], seg["V0"], (last - seg["t0"]) / FPS + k / FPS)
        if p[2] <= 0.0:
            return float(p[0]), float(p[1]), k / FPS
    return None


def call(seg, rep):
    """-> (label, detail). label in IN / NET / OUT / KITCHEN / ADJACENT / NONE."""
    y0 = rep["start_xy"][1]
    x0 = rep["start_xy"][0]
    if y0 < 14.0:
        near_server = True
    elif y0 > 30.0:
        near_server = False
    else:
        return "NONE", f"server side unknown (start y={y0:.0f})"
    ld = landing(seg)
    if rep["net_hit"]:
        return "NET", f"crosses net at z={rep['net_z']:.1f}"
    if rep["net_end"]:
        return "NET", "arc ends at the net"
    if ld is None:
        return "NONE", "no landing within 1 s"
    xl, yl, _ahead = ld
    far_base = COURT_Y if near_server else 0.0                    # baseline of the receiving end
    depth = (yl - NET_Y) if near_server else (NET_Y - yl)         # >0 on the receiving half
    if depth < 0:
        return "NET", f"lands on the server's half (y={yl:.0f})"
    beyond = xl < 0.0 or xl > COURT_X or (yl > COURT_Y if near_server else yl < 0.0)
    edge = min(abs(xl), abs(xl - COURT_X), abs(yl - far_base))
    if edge < MARGIN:
        return "NONE", f"near a boundary (x={xl:.0f}, y={yl:.0f})"
    if beyond:
        return "OUT", f"lands x={xl:.0f}, y={yl:.0f}"
    if abs(depth - KITCHEN) < MARGIN:
        return "NONE", f"near the kitchen line (depth {depth:.1f} ft)"
    if depth < KITCHEN:
        return "KITCHEN", f"lands {depth:.0f} ft past the net"
    baseline_dist = y0 if near_server else COURT_Y - y0
    if baseline_dist <= 8.0:                                       # launch x is the server's x
        if abs(xl - 10.0) < MARGIN:
            return "NONE", f"near the centre line (x={xl:.0f})"
        if (x0 < 10.0) == (xl < 10.0):
            return "ADJACENT", f"launch x={x0:.0f}, lands x={xl:.0f}"
    return "IN", f"lands x={xl:.0f}, y={yl:.0f}"


def main():
    rows = list(csv.DictReader(open("cache/fresh_sample_key.csv")))
    cams, out = {}, []
    for r in rows:
        clip = r["clip"]
        if clip in EXCLUDE:
            continue
        seg_name = r["segment"]
        if seg_name not in cams:
            meta = json.load(open(f"cache/fresh/{seg_name}.meta.json"))
            calib = json.load(open(meta["calib"]))
            res = camera_for(calib, 1920, 1080)
            cams[seg_name] = (calib, None, res[1]) if res[0] is None else (calib, res, "")
        calib, cam, why = cams[seg_name]
        truth = "fault" if clip in FAULTS else "in"
        if cam is None:
            out.append((clip, truth, "NONE", f"excluded: calibration check failed ({why})", None))
            continue
        f, R, C, _ = cam
        cx, cy = 960.0, 540.0
        track = load_predictions(f"cache/fresh/{seg_name}.csv", FPS)
        pts = gated_points(track, court_wedge(calib))
        s0 = float(r["start"])
        a, b = max(0, int((s0 - PRE) * FPS)), min(len(pts) - 1, int((s0 + POST) * FPS))
        win = [p if a <= i <= b else None for i, p in enumerate(pts)]
        segs = b3.segment_flights(win, f, R, C, cx, cy)
        serve = None
        for s in segs:
            rep = b3.seg_report(s)
            if not b3.seg_ok(rep):
                continue
            if abs(rep["end_xy"][1] - rep["start_xy"][1]) >= MIN_TRAVEL:
                serve = (s, rep)
                break
        if serve is None:
            out.append((clip, truth, "NONE", f"no serve flight ({len(segs)} segments in window)", None))
            continue
        lab, detail = call(*serve)
        out.append((clip, truth, lab, detail, serve[1]))

    print(f"{'clip':>4s} {'truth':>6s} {'kind':>9s} {'call':>9s}  detail")
    for clip, truth, lab, detail, rep in out:
        kind = FAULTS.get(clip, V[clip] if V[clip] != "not" else "?")
        print(f"{clip:>4s} {truth:>6s} {kind:>9s} {lab:>9s}  {detail}")

    est = [o for o in out if o[2] != "NONE"]
    n = len(out)
    called_fault = lambda o: o[2] in ("NET", "OUT", "KITCHEN", "ADJACENT")
    tf = [o for o in est if o[1] == "fault"]; tg = [o for o in est if o[1] == "in"]
    cov = len(est) / n
    fr = sum(called_fault(o) for o in tf) / len(tf) if tf else float("nan")
    ff = sum(called_fault(o) for o in tg) / len(tg) if tg else float("nan")
    type_ok = sum(1 for o in tf if o[2].lower() == FAULTS[o[0]])
    print(f"\neligible {n} (faults {sum(1 for o in out if o[1]=='fault')}, good serves {sum(1 for o in out if o[1]=='in')})")
    print(f"(1) estimate produced for {len(est)}/{n} = {cov:.0%}   (bar >= 60%)")
    print(f"(2) true faults called a fault {sum(called_fault(o) for o in tf)}/{len(tf)} = {fr:.0%} (bar >= 50%);"
          f"  good serves called a fault {sum(called_fault(o) for o in tg)}/{len(tg)} = {ff:.0%} (bar <= 25%)")
    print(f"    fault type right (not gated): {type_ok}/{len(tf)}")
    ok = cov >= 0.60 and tf and tg and fr >= 0.50 and ff <= 0.25
    print(f"\nBAR: {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    main()
