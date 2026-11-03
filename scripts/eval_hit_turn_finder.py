"""A hit finder from the ball track: flag sharp turns and sudden speed-ups that are not floor bounces (2026-10-19, PIC-226).
Pre-registered: this file (rule, numbers, data, matching, bar) was committed after developing on minute 1 and before
any minute-2 hit mark was read from CVAT.

Context. The bounce finder flags the ball's lowest on-screen point (a dip), so it boxes a hit only when the hit looks
like a dip: 3 of 22 marked hits in minute 1 (hit visibility, minute 1). A far-side hit sends the ball back down the
screen, a hit speeds the ball up, and a near hit often reverses it sideways; none of those is a dip.
RULE, fixed on minute 1 (chunk 3c frames 0-1799, 22 hits, 8 of them tracked on both sides):
  Track: the tile-arm tracked ball of chunk 3c (eval_bounce_recovery.clip_points, as every chunk-3c test).
  At each tracked frame f, v_in = mean velocity from the tracked point 3 frames before (or 4, 5 if missing) to f,
  v_out = mean velocity from f to the point 3 frames after (or 4, 5). Both speeds >= 2.0 px/frame.
  TURN if the angle between v_in and v_out >= 30 deg, or SPEED-UP if |v_out| / |v_in| >= 1.8.
  Not a bounce shape: drop it if v_in goes down the screen and v_out up (y+ then y-) without a sideways reversal
  (v_in_x * v_out_x >= -4).
  Picks within 5 frames of each other collapse to one (speed-ups first, then the larger angle).
  Minute 1 (in-sample): 32 picks, 7 of 22 hits found (6 of the 8 reachable), 7 of 32 picks on a hit,
  5 on a bounce. Requiring more track support around f, or excluding bounce-finder boxes, lost hits.
DATA (held out): minute 2, task frames 1800-3599 of CVAT task 147 (jobs 181-183), deduplicated as minute 1 was
  (same label within 3 frames and 30 px), `hit` and `hit_unsure` both counted (reported separately).
MATCHING (same as hit visibility): a hit is found if a pick is within +-3 frames and 30 px of the mark; a pick is on
  a hit / on a bounce by the same test against the hit marks / the operator's bounce marks of chunk 3c.
  Reachable = >= 3 tracked points in the 8 frames before and in the 8 frames after the mark.
BAR, minute 2 (all three):
  reach      finds >= 50% of the reachable hits   (fewer than 5 reachable -> inconclusive on reach)
  beats      finds more hits than the bounce finder boxes on the same minute
  precision  >= 15% of picks are on a hit
REPORTED: recall over all hits, per side (image net line), picks on bounces, precision with +-8 frames.
One camera, one court, two minutes: a pass is a lead for a candidate generator, not a hit counter.
Run: .venv/bin/python scripts/eval_hit_turn_finder.py --dev      (minute 1, from the committed labels)
     .venv/bin/python scripts/eval_hit_turn_finder.py --score    (minute 2, reads CVAT task 147, saves the labels)
"""
import json, math, subprocess, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np

CSV = "cache/bounce_pilot/chunk3c_eda301d9_0538_s000.tile.csv"
CALIB = "cache/pgc_fieldtest/7358ef3f-6a41-4abe-b431-807eba7bc9f1.calib.json"
BOUNCES = "eval/labels/bounces/cvat_eda301d9_0926T0538_s000_120-360.json"
MIN1 = "eval/labels/hits/cvat_eda301d9_0926T0538_s000_120-180.json"
MIN2 = "eval/labels/hits/cvat_eda301d9_0926T0538_s000_180-240.json"
K, SMIN, ANG, SPEEDUP, MERGE = 3, 2.0, 30.0, 1.8, 5
TOL, PX = 3, 30


def velocities(T, f):
    def side(d):
        for j in range(K, K + 3):
            if f + d * j in T: return (np.array(T[f + d * j]) - np.array(T[f])) * d / j
        return None
    return side(-1), side(1)


def picks(T, a, b):
    ev = []
    for f in sorted(T):
        if not a <= f <= b: continue
        vin, vout = velocities(T, f)
        if vin is None or vout is None: continue
        si, so = np.linalg.norm(vin), np.linalg.norm(vout)
        if si < SMIN or so < SMIN: continue
        ang = math.degrees(math.acos(max(-1.0, min(1.0, float(vin @ vout) / si / so))))
        up = so / si >= SPEEDUP
        if not (ang >= ANG or up): continue
        if vin[1] > 0 and vout[1] < 0 and vin[0] * vout[0] >= -4: continue
        ev.append((f, ang + 180 * up))
    out = []
    for f, s in ev:
        if out and f - out[-1][0] <= MERGE:
            if s > out[-1][1]: out[-1] = (f, s)
        else: out.append((f, s))
    return [f for f, _ in out]


def cvat_minute2():
    q = ("select s.frame, l.name, s.points from engine_labeledshape s join engine_label l on l.id=s.label_id "
         "join engine_job j on j.id=s.job_id join engine_segment g on g.id=j.segment_id "
         "where g.task_id=147 and s.frame >= 1800 and s.frame < 3600 order by s.frame")
    rows = subprocess.run(["docker", "--context", "desktop-linux", "exec", "cvat_db", "psql", "-U", "root", "-d", "cvat",
                           "-tA", "-F", "|", "-c", q], capture_output=True, text=True, check=True).stdout
    hits = []
    for l in rows.splitlines():
        if not l.strip(): continue
        f, lab, pts = l.split("|"); f = int(f); x, y = map(float, pts.strip("{}").split(",")[:2])
        if any(abs(f - h["frame"]) <= 3 and math.hypot(x - h["x"], y - h["y"]) < 30 and lab == h["label"] for h in hits): continue
        hits.append({"frame": f, "label": lab, "x": x, "y": y})
    json.dump({"source": "cvat project 13 task 147 (hit-chunk3c-pgc)", "video": "clips/bounce_chunk3/eda301d9_0926T0538_s000_120-240.mp4",
               "source_frame_offset": 3600, "fps": 30.0, "minute": 2, "frames": [1800, 3599], "complete": True, "hits": hits},
              open(MIN2, "w"), indent=1)
    return hits


def run(hits, a, b, gated):
    import eval_bounce_recovery as E
    H, raw, T, cands = E.clip_points({"calib": CALIB, "csv": CSV})
    net_y = json.load(open(CALIB))["net_image_points"][0][1]
    bounces = [m for m in json.load(open(BOUNCES))["bounces"] if a <= m["frame"] <= b]
    fs = picks(T, a, b)
    on = lambda f, e, tol=TOL: abs(f - e["frame"]) <= tol and math.hypot(T[f][0] - e["x"], T[f][1] - e["y"]) <= PX
    found = lambda e: any(on(f, e) for f in fs)
    boxed = lambda e: any(abs(c - e["frame"]) <= TOL and math.hypot(cands[c][0] - e["x"], cands[c][1] - e["y"]) <= PX for c in cands)
    reach = lambda e: (sum(g in T for g in range(e["frame"] - 8, e["frame"])) >= 3 and
                       sum(g in T for g in range(e["frame"] + 1, e["frame"] + 9)) >= 3)
    print(f"frames {a}-{b}: hits {len(hits)} ({sum(h['label'] == 'hit_unsure' for h in hits)} unsure), bounces {len(bounces)}, picks {len(fs)}")
    for side in ("near", "far", "all"):
        g = [h for h in hits if side == "all" or (side == "near") == (h["y"] > net_y)]
        print(f"  {side:4s} hits {len(g):2d}  reachable {sum(map(reach, g)):2d}  found {sum(map(found, g)):2d}  "
              f"found of reachable {sum(found(h) for h in g if reach(h)):2d}  bounce finder boxes {sum(map(boxed, g)):2d}")
    on_hit = sum(any(on(f, e) for e in hits) for f in fs); on_b = sum(any(on(f, e) for e in bounces) for f in fs)
    on_hit8 = sum(any(on(f, e, 8) for e in hits) for f in fs)
    print(f"  picks on a hit {on_hit}/{len(fs)} ({on_hit / max(1, len(fs)):.0%}), within +-8 frames {on_hit8}, on a bounce {on_b}")
    if not gated: return
    R = [h for h in hits if reach(h)]; fr = sum(found(h) for h in R)
    reach_ok = None if len(R) < 5 else fr / len(R) >= 0.50
    beats = sum(map(found, hits)) > sum(map(boxed, hits)); prec = on_hit / max(1, len(fs)) >= 0.15
    print("BAR: reach " + ("inconclusive (<5 reachable)" if reach_ok is None else ("PASS" if reach_ok else "FAIL")) +
          f" ({fr}/{len(R)})  beats {'PASS' if beats else 'FAIL'}  precision {'PASS' if prec else 'FAIL'}  ->  " +
          ("PASS" if reach_ok and beats and prec else ("INCONCLUSIVE" if reach_ok is None and beats and prec else "FAIL")))


if __name__ == "__main__":
    if sys.argv[1] == "--dev":
        run(json.load(open(MIN1))["hits"], 0, 1799, gated=False)
    else:
        run(cvat_minute2(), 1800, 3599, gated=True)
