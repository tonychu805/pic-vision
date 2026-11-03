"""Paddle hits from an arm swing checked against the ball (2026-10-19, PIC-226).
Pre-registered: this file (rule, numbers, data, matching, bar) was committed after developing on minutes 1-2 and
before any minute-3 hit mark existed (the operator had not started CVAT task 148).

Context. Wrist-speed swings (eval_arm_swing_hits.py, PASS narrowly on minute 2: 12/22 hits, near 4/9, 22% of
swings on a hit). Most swings are not hits: between points, or the ball is somewhere else. The ball track can't
find hits (ADR-156) but can say whether the ball is in play and whether it is far from the swinging player.
RULE, fixed on minutes 1-2 (chunk 3c frames 0-3599, 44 hits):
  Swings: exactly as eval_arm_swing_hits.py (wrist speed over 2 frames >= 0.06 box heights/frame, peak within +-10).
  Ball: the tile-arm tracked ball of chunk 3c (eval_bounce_recovery.clip_points).
  KEEP a swing at frame f by player p only if
    in play    >= 3 tracked ball points within f-15..f+15, and
    not far    NOT (>= 2 tracked ball points within f-5..f+5 and every one of them more than 0.5 box heights
               outside p's box at f).  A ball not seen near the swing does not veto (near-side hits).
  Minutes 1-2 (in-sample): swings 109 -> kept 70; hits found 28 -> 27 of 44; on a hit 26% -> 39%.
  Tried and not kept: one swing per moment (nearest the ball within 5-15 frames): +3 points precision, lost hits.
MATCHING: as eval_arm_swing_hits.py (+-5 frames, mark inside the player box grown by half a box height).
DATA (held out): minute 3, chunk 3c frames 3600-5399 (source 4:00-5:00), CVAT project 13 task 148, task frame
  i = chunk frame 3600 + i; deduplicated as before; `hit` and `hit_unsure` both counted, reported separately.
  Poses: cache/arm_swing/poses_chunk3c_3600-5399.json (computed before any minute-3 mark existed).
BAR, minute 3 (all five):
  found      >= 45% of all hits
  near       >= 35% of near-side hits (image net line)
  precision  >= 30% of kept swings on a hit
  better     precision above the swing rule alone on minute 3, losing at most 2 of the hits the swing alone finds
  not chance hits found >= 3x the mean of the kept swings shifted by +-15..150 frames (step 15)
REPORTED: the swing rule alone on minute 3 against its own (eval_arm_swing_hits.py) bar, as a replication.
One camera, one court: a pass is a hit candidate generator on this court, not a hit counter.
Run: .venv/bin/python scripts/eval_swing_ball_hits.py --dev     (minutes 1-2)
     .venv/bin/python scripts/eval_swing_ball_hits.py --score   (minute 3: reads CVAT task 148, saves the labels)
"""
import json, math, subprocess, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
import eval_arm_swing_hits as A

CSV = "cache/bounce_pilot/chunk3c_eda301d9_0538_s000.tile.csv"
MIN3 = "eval/labels/hits/cvat_eda301d9_0926T0538_s000_240-300.json"
PLAY_W, PLAY_N, NEAR_W, NEAR_N, FAR = 15, 3, 5, 2, 0.5


def keep(T, TR, f, i):
    if sum(g in T for g in range(f - PLAY_W, f + PLAY_W + 1)) < PLAY_N: return False
    x0, y0, x1, y1 = TR[i][f]["box"]; hh = y1 - y0
    d = [max(0, x0 - T[g][0], T[g][0] - x1, y0 - T[g][1], T[g][1] - y1) / hh for g in range(f - NEAR_W, f + NEAR_W + 1) if g in T]
    return not (len(d) >= NEAR_N and min(d) > FAR)


def cvat_minute3():
    q = ("select s.frame, l.name, s.points from engine_labeledshape s join engine_label l on l.id=s.label_id "
         "join engine_job j on j.id=s.job_id join engine_segment g on g.id=j.segment_id where g.task_id=148 order by s.frame")
    rows = subprocess.run(["docker", "--context", "desktop-linux", "exec", "cvat_db", "psql", "-U", "root", "-d", "cvat",
                           "-tA", "-F", "|", "-c", q], capture_output=True, text=True, check=True).stdout
    hits = []
    for l in rows.splitlines():
        if not l.strip(): continue
        f, lab, pts = l.split("|"); f = int(f) + 3600; x, y = map(float, pts.strip("{}").split(",")[:2])
        if any(abs(f - h["frame"]) <= 3 and math.hypot(x - h["x"], y - h["y"]) < 30 and lab == h["label"] for h in hits): continue
        hits.append({"frame": f, "label": lab, "x": x, "y": y})
    json.dump({"source": "cvat project 13 task 148 (hit-chunk3c-pgc, minute 3)",
               "video": "clips/bounce_chunk3/eda301d9_0926T0538_s000_240-300.mp4", "source_frame_offset": 3600,
               "frame_note": "frames are chunk-3c frames (task frame + 3600)", "fps": 30.0, "minute": 3,
               "frames": [3600, 5399], "complete": True, "hits": hits}, open(MIN3, "w"), indent=1)
    return hits


def evaluate(T, P, hits, a, b, net_y, label):
    TR = A.tracks(P, a, b); sw = A.swing_picks(TR); kp = [(f, i) for f, i in sw if keep(T, TR, f, i)]
    out = {}
    for name, pk in (("swing alone", sw), ("swing + ball", kp)):
        found, on = A.score(TR, pk, hits)
        chance = np.mean([sum(A.score(TR, pk, hits, d)[0]) for d in A.SHIFTS])
        near = [ok for h, ok in zip(hits, found) if h["y"] > net_y]
        out[name] = dict(found=found, on=on, n=len(pk), near=(sum(near), len(near)), chance=chance)
        print(f"{label} {name:12s}: picks {len(pk):3d}  hits found {sum(found):2d}/{len(hits)} (near {sum(near)}/{len(near)})  "
              f"on a hit {on}/{len(pk)} ({on / max(1, len(pk)):.0%})  chance {chance:.1f}")
    return out


def main(dev):
    import eval_bounce_recovery as E, eval_hit_turn_finder as F
    _, _, T, _ = E.clip_points({"calib": A.CALIB, "csv": CSV})
    net_y = json.load(open(A.CALIB))["net_image_points"][0][1]
    if dev:
        P = json.load(open(A.POSES))
        for path, a, b, lab in ((A.MIN1, 0, 1799, "min1"), (A.MIN2, 1800, 3599, "min2")):
            evaluate(T, P, json.load(open(path))["hits"], a, b, net_y, lab)
        return
    hits = cvat_minute3()
    print(f"minute 3: hits {len(hits)} ({sum(h['label'] == 'hit_unsure' for h in hits)} unsure)")
    P = [[] for _ in range(3600)] + json.load(open(A.POSES3))
    r = evaluate(T, P, hits, 3600, 5399, net_y, "min3")
    s, c = r["swing alone"], r["swing + ball"]
    nf = sum(c["found"]); lost = sum(a and not b for a, b in zip(s["found"], c["found"]))
    checks = {"found": nf / len(hits) >= 0.45, "near": c["near"][0] / max(1, c["near"][1]) >= 0.35,
              "precision": c["on"] / max(1, c["n"]) >= 0.30,
              "better": c["on"] / max(1, c["n"]) > s["on"] / max(1, s["n"]) and lost <= 2, "not chance": nf >= 3 * c["chance"]}
    print(f"swing + ball loses {lost} of the swing-alone hits")
    print("BAR: " + "  ".join(f"{k} {'PASS' if v else 'FAIL'}" for k, v in checks.items()) + f"  ->  {'PASS' if all(checks.values()) else 'FAIL'}")
    sf = sum(s["found"])
    rep = {"found": sf / len(hits) >= 0.50, "near": s["near"][0] / max(1, s["near"][1]) >= 0.40,
           "precision": s["on"] / max(1, s["n"]) >= 0.20, "not chance": sf >= 3 * s["chance"]}
    print("REPLICATION (swing alone vs its own bar): " + "  ".join(f"{k} {'PASS' if v else 'FAIL'}" for k, v in rep.items()) +
          f"  ->  {'PASS' if all(rep.values()) else 'FAIL'}")


if __name__ == "__main__":
    main(sys.argv[1] == "--dev")
