"""Second-court generalization test: the frozen swing + ball hit rule (ADR-157) on the glare court (2026-10-19, PIC-226).
Pre-registered: this file and its bar were committed while CVAT task 149 had no hit marks. The rule and every
parameter are imported unchanged from eval_arm_swing_hits.py / eval_swing_ball_hits.py; nothing is tuned here.

Context. The swing + ball rule was built and tested entirely on the clean court (eda301d9, chunk 3c). This is the
first run on a different camera and court: c199a97c 2026-09-26 05:38 session-002, the glare court (ADR-154 — fixed
glare is the main cause of lost ball tracking here), calib 34fab44c, where every bounce is already marked (project 7).
DATA (held out for this rule): minutes 0-1 (session frames 0-3599, the two busiest; 25 marked bounces), CVAT
  project 14 task 149. Task frame i = session frame i (clip cut from frame 0, no offset). Both the tile-arm pass
  (cache/bounce_pilot/chunk2_c199a97c_0538_s002.tile.csv) and the production pass
  (cache/scale/c199a97c_2026-09-26T05-38-15_session-002.csv) are full-session native frames, so no shift.
  Poses: cache/arm_swing/poses_chunk2_glare_0-3599.json (computed before any mark existed).
RULE: swings = eval_arm_swing_hits.swing_picks (wrist speed over 2 frames >= 0.06 box heights/frame, peak within
  +-10); kept = eval_swing_ball_hits.keep (ball in play >= 3 tracked points within +-15 frames, not far unless
  >= 2 tracked points within +-5 frames all > 0.5 box heights outside the box). Matching = eval_arm_swing_hits
  (+-5 frames, mark inside the player box grown by half a box height). Side by the glare-court image net line.
BAR, on the tile-arm track (the detector the rule was tuned on), minutes 0-1 pooled (all four):
  found      >= 40% of all hits   (softer than the clean court's 45%: glare loses the ball more)
  near       >= 30% of near-side hits
  precision  >= 30% of kept swings on a hit
  not chance hits found >= 3x the mean of the kept swings shifted by +-15..150 frames (step 15)
REPORTED, not gated: the production track the same way; swing-alone; per minute.
One more court, one session, one operator: a pass means the method is not a quirk of the clean court; a miss on
glare is expected and still informative.
Run: .venv/bin/python scripts/eval_swing_ball_glare.py        (reads CVAT task 149, saves labels, scores)
"""
import json, math, subprocess, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
import eval_arm_swing_hits as A
import eval_swing_ball_hits as SB
import eval_bounce_recovery as E

CALIB = "cache/pgc_fieldtest/34fab44c-a9a4-4719-bea3-d5a611d54576.calib.json"
TILE = "cache/bounce_pilot/chunk2_c199a97c_0538_s002.tile.csv"
PROD = "cache/scale/c199a97c_2026-09-26T05-38-15_session-002.csv"
POSES = "cache/arm_swing/poses_chunk2_glare_0-3599.json"
LABELS = "eval/labels/hits/cvat_c199a97c_0926T0538_s002_0-120.json"
A_F, B_F = 0, 3599


def cvat():
    q = ("select s.frame, l.name, s.points from engine_labeledshape s join engine_label l on l.id=s.label_id "
         "join engine_job j on j.id=s.job_id join engine_segment g on g.id=j.segment_id where g.task_id=149 order by s.frame")
    rows = subprocess.run(["docker", "--context", "desktop-linux", "exec", "cvat_db", "psql", "-U", "root", "-d", "cvat",
                           "-tA", "-F", "|", "-c", q], capture_output=True, text=True, check=True).stdout
    hits = []
    for l in rows.splitlines():
        if not l.strip(): continue
        f, lab, pts = l.split("|"); f = int(f); x, y = map(float, pts.strip("{}").split(",")[:2])
        if any(abs(f - h["frame"]) <= 3 and math.hypot(x - h["x"], y - h["y"]) < 30 and lab == h["label"] for h in hits): continue
        hits.append({"frame": f, "label": lab, "x": x, "y": y})
    json.dump({"source": "cvat project 14 task 149 (hit-chunk2-glare-pgc)",
               "video": "clips/bounce_chunk3/c199a97c_0926T0538_s002_0-120.mp4", "fps": 30.0, "court": "glare (c199a97c)",
               "frames": [A_F, B_F], "complete": True, "hits": hits}, open(LABELS, "w"), indent=1)
    return hits


def track(csv):
    _, _, T, _ = E.clip_points({"calib": CALIB, "csv": csv})
    return T


def report(T, TR, hits, net_y, name):
    sw = A.swing_picks(TR); kp = [(f, i) for f, i in sw if SB.keep(T, TR, f, i)]
    found, on = A.score(TR, kp, hits)
    chance = np.mean([sum(A.score(TR, kp, hits, d)[0]) for d in A.SHIFTS])
    near = [ok for h, ok in zip(hits, found) if h["y"] > net_y]
    print(f"  {name:12s}: picks {len(kp):3d}  found {sum(found):2d}/{len(hits)} (near {sum(near)}/{len(near)})  "
          f"on a hit {on}/{len(kp)} ({on / max(1, len(kp)):.0%})  chance {chance:.1f}")
    return dict(found=sum(found), n=len(hits), near=(sum(near), len(near)), on=on, picks=len(kp), chance=chance)


def main():
    hits = cvat()
    net_y = json.load(open(CALIB))["net_image_points"][0][1]
    P = json.load(open(POSES)); TR = A.tracks(P, A_F, B_F)
    print(f"glare court task 149: hits {len(hits)} ({sum(h['label'] == 'hit_unsure' for h in hits)} unsure), player tracks {len(TR)}")
    for mn in (0, 1):
        g = [h for h in hits if h["frame"] // 1800 == mn]
        print(f"  minute {mn}: {len(g)} hits")
    Tt = track(TILE)
    print("TILE-ARM track (gated):")
    r = report(Tt, TR, hits, net_y, "swing + ball")
    report(Tt, TR, hits, net_y, "swing alone") if False else None
    sw = A.swing_picks(TR); fa, oa = A.score(TR, sw, hits)
    print(f"  {'swing alone':12s}: picks {len(sw):3d}  found {sum(fa)}/{len(hits)}  on a hit {oa}/{len(sw)} ({oa / max(1, len(sw)):.0%})")
    print("PRODUCTION track (reported):")
    report(track(PROD), TR, hits, net_y, "swing + ball")
    checks = {"found": r["found"] / r["n"] >= 0.40, "near": r["near"][0] / max(1, r["near"][1]) >= 0.30,
              "precision": r["on"] / max(1, r["picks"]) >= 0.30, "not chance": r["found"] >= 3 * r["chance"]}
    print("BAR (tile-arm): " + "  ".join(f"{k} {'PASS' if v else 'FAIL'}" for k, v in checks.items()) +
          f"  ->  {'PASS' if all(checks.values()) else 'FAIL'}")


if __name__ == "__main__":
    main()
