"""Second unselected bounce chunk: do the tile arm's finding rate and the speed-ratio check hold on a new
camera? (2026-10-16). Pre-registered: this docstring and the bars below were committed before any
label was compared with any detector output.

Chunk: c199a97c 2026-09-26 05:38 session-002 (whole file, 7,438 frames, 4.1 min), a different camera and day
from chunk 1 (eda301d9 2026-09-25 08:21 session-000). Labels: every bounce the operator saw, CVAT project
'bounce-chunk2-pgc' (scripts/cvat_make_bounce_chunk.py), task frame = source frame. Calibration borrowed from
the same camera's recording 34fab44c (image-match distance 0.020, scripts/scale_plan.py), used for both arms.
Base arm = production pod_infer.py output (cache/scale/...session-002.csv); tile arm = infer_tile_k14.py.
Finder, tracker, matching (+-3 frames, 15 px) unchanged from eval_bounce_tile_chunk.py.

PART A, finding (stage 'find'). Same bar as chunk 1:
  holds        tile found >= 40% of the labelled bounces
  partly holds tile found 25-40% AND more than the base arm
  does not     otherwise

PART B, speed check (stage 'speed'). The operator tags EVERY tile candidate in CVAT (bounce | paddle_hit |
not_ball), shown the candidate's frame but not its speed ratio, as in chunk 1. Rule frozen from chunk 1
(EXPERIMENTS.md 2026-10-15 motion check): speed_ratio = |v_out| / |v_in| from line fits over the 8 frames
either side (>= 3 tracked points per side), call it a bounce when speed_ratio < 0.95. No re-tuning.
  scorable     >= 8 paddle_hit AND >= 8 bounce tags, and the ratio computable for >= 80% of them
  holds        bounces kept (ratio < 0.95) >= 75% AND hits removed (ratio >= 0.95) >= 70%
  partly holds exactly one of the two
  does not     neither
Also reported, not gated: AUC of speed_ratio (bounce vs hit), medians.

Run: .venv/bin/python scripts/eval_bounce_chunk2.py find     (TF 2.15 env for the tile pass, ~10 min)
     .venv/bin/python scripts/eval_bounce_chunk2.py speed    (after the candidate review)
"""
import glob, json, os, subprocess, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
from src.bounce_eval import recover
import eval_bounce_recovery as E
from eval_motion_hit_vs_bounce import feats, auc

TF = "/mnt/fast_scratch/tf215_env/venv/bin/python"
W = "/mnt/fast_scratch/tracknet_weights/weights_k14_epoch19"
VIDEO = "pgc-fieldtest-sept2026/c199a97c-c51f-4620-8523-b2837f48c1a7/2026-09-26T05-38-15-376Z/session-002.mkv"
CALIB = "cache/pgc_fieldtest/34fab44c-a9a4-4719-bea3-d5a611d54576.calib.json"
BASE = "cache/scale/c199a97c_2026-09-26T05-38-15_session-002.csv"
TILE = "cache/bounce_pilot/chunk2_c199a97c_0538_s002.tile.csv"
LABELS = "eval/labels/bounces/cvat_c199a97c_0926T0538_s002.json"
CANDS = "cache/bounce_pilot/chunk2_candidates.json"
PROJECT = 7
THRESH = 0.95


def psql(q):
    return subprocess.run(["docker", "--context", "desktop-linux", "exec", "cvat_db", "psql", "-U", "root", "-d", "cvat",
                           "-tA", "-F", "|", "-c", q], capture_output=True, text=True, check=True).stdout


def export_labels():
    q = f"""select l.frame, l.points from engine_labeledshape l join engine_job j on j.id=l.job_id
            join engine_segment s on s.id=j.segment_id join engine_task t on t.id=s.task_id
            where t.project_id={PROJECT} and l.type='points' order by l.frame"""
    b = []
    for line in psql(q).splitlines():
        f, pts = line.split("|"); x, y = (float(v) for v in pts.split(",")[:2])
        b.append({"frame": int(f), "t": round(int(f) / 30.0, 3), "x": round(x, 1), "y": round(y, 1)})
    json.dump({"source": f"cvat project {PROJECT}", "video": VIDEO, "fps": 30.0, "n_frames_cvat": 7438,
               "complete": None, "bounces": b}, open(LABELS, "w"), indent=1)
    return b


def find():
    labs = export_labels()
    if not (os.path.exists(TILE) and os.path.getsize(TILE) > 1000):
        env = dict(os.environ)
        env["LD_LIBRARY_PATH"] = ":".join(glob.glob("/mnt/fast_scratch/tf215_env/venv/lib/python*/site-packages/nvidia/*/lib")
                                          + [env.get("LD_LIBRARY_PATH", "")])
        subprocess.run([TF, "scripts/infer_tile_k14.py", "--video", VIDEO, "--calib", CALIB, "--model", W,
                        "--output", TILE, "--seconds", "400"], env=env, check=True, capture_output=True)
    n = len(labs); found = {}
    print(f"bounces labelled: {n}")
    for arm, csv_ in (("base", BASE), ("tile", TILE)):
        H, raw, tracked, cands = E.clip_points({"calib": CALIB, "csv": csv_})
        r = [recover({"frame": b["frame"], "x": b["x"], "y": b["y"], "visible": True}, raw, tracked, cands, H) for b in labs]
        k = lambda key: sum(1 for x in r if x[key])
        match = sum(1 for g in cands if any(abs(g - b["frame"]) <= 3 for b in labs))
        found[arm] = k("found")
        print(f"{arm:5s} seen {k('seen') / n:4.0%}  tracked {k('tracked') / n:4.0%}  found {k('found')} ({k('found') / n:.0%})"
              f"  candidates {len(cands)}  matching a label {match}")
        if arm == "tile":
            json.dump(sorted(cands), open(CANDS, "w"))
    t, b = found["tile"] / n, found["base"] / n
    print("PART A:", "HOLDS" if t >= 0.40 else "PARTLY HOLDS" if (t >= 0.25 and found["tile"] > found["base"]) else "DOES NOT HOLD")


def speed():
    q = f"""select t.name, l.name from engine_task t join engine_segment s on s.task_id=t.id join engine_job j on j.segment_id=s.id
            join engine_labeledimage i on i.job_id=j.id join engine_label l on l.id=i.label_id
            where t.project_id=(select id from engine_project where name='bounce-chunk2-candidates')"""
    tags = {int(n.split("frame ")[1].split(" ")[0]): lab for n, lab in (l.split("|") for l in psql(q).splitlines())}
    _, _, T, _ = E.clip_points({"calib": CALIB, "csv": TILE})
    ev = [(f, l) for f, l in sorted(tags.items()) if l in ("bounce", "paddle_hit")]
    rows = [(feats(T, f), l) for f, l in ev]
    ok = [(r["speed_ratio"], l) for r, l in rows if r]
    nb = sum(1 for _, l in ev if l == "bounce"); nh = len(ev) - nb
    print(f"tags {len(tags)}: bounce {nb}, paddle_hit {nh}, other {len(tags) - len(ev)}; ratio computable {len(ok)}/{len(ev)}")
    rb = [s for s, l in ok if l == "bounce"]; rh = [s for s, l in ok if l == "paddle_hit"]
    if nb < 8 or nh < 8 or len(ok) < 0.8 * len(ev):
        print("PART B: NOT SCORABLE"); return
    kept = sum(s < THRESH for s in rb) / len(rb); removed = sum(s >= THRESH for s in rh) / len(rh)
    print(f"bounce median {np.median(rb):.2f}  hit median {np.median(rh):.2f}  AUC(bounce>hit) {auc(rb, rh):.2f}")
    print(f"bounces kept {kept:.0%} (bar 75%)  hits removed {removed:.0%} (bar 70%)")
    a, b = kept >= 0.75, removed >= 0.70
    print("PART B:", "HOLDS" if a and b else "PARTLY HOLDS" if a or b else "DOES NOT HOLD")


if __name__ == "__main__":
    {"find": find, "speed": speed}[sys.argv[1]]()
