"""Does the tile arm's bounce gain hold on an UNSELECTED stretch? (2026-10-15)

The 18 pilot clips are rallies the system had already flagged and a person judged real, and
they motivated the hypothesis (tile arm: 19 of 42 found vs 8, EXPERIMENTS.md 2026-10-15). This
is one continuous 3-minute PGC chunk (eda301d9, 2026-09-25 08:21, session-000, 5,390 frames)
in which the operator marked every bounce they saw (33), not chosen for being rally-like.

Arms on the whole chunk: base = the cached scripts/pod_infer.py output
(cache/fresh/eda301d9_2026-09-25T08-21-01_session-000.csv, same video, same calibration);
tile = scripts/infer_tile_k14.py, rule unchanged. Calibration is borrowed from the same camera's
10:01 recording (365c798c): it feeds the court mask and gate for BOTH arms, and the court-error
figures here are weak. Scored as eval_bounce_recovery.py (+-3 frames, 15 px).

BAR, fixed BEFORE the run:
  holds        tile found >= 40% of 33 (14 or more)   [the pilot's bar]
  partly holds tile found 10-13 AND more than the base arm
  does not     tile found < 10, or no more than the base arm
Also reported, not gated: seen / tracked, candidates and how many match a label.
Run: .venv/bin/python scripts/eval_bounce_tile_chunk.py   (TF 2.15 env, ~5-10 min)
"""
import glob, json, os, subprocess, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from src.bounce_eval import near_half, percentile, recover
import eval_bounce_recovery as E

TF = "/mnt/fast_scratch/tf215_env/venv/bin/python"
W = "/mnt/fast_scratch/tracknet_weights/weights_k14_epoch19"
CALIB = "cache/pgc_fieldtest/365c798c-6554-42b1-b0e6-b2825e73d264.calib.json"
LABELS = "eval/labels/bounces/cvat_eda301d9_0925T0821_s000.json"
BASE = "cache/fresh/eda301d9_2026-09-25T08-21-01_session-000.csv"
TILE = "cache/bounce_pilot/chunk_eda301d9_0821.tile.csv"


def main():
    L = json.load(open(LABELS))
    if not (os.path.exists(TILE) and os.path.getsize(TILE) > 1000):
        env = dict(os.environ)
        env["LD_LIBRARY_PATH"] = ":".join(glob.glob("/mnt/fast_scratch/tf215_env/venv/lib/python*/site-packages/nvidia/*/lib")
                                          + [env.get("LD_LIBRARY_PATH", "")])
        subprocess.run([TF, "scripts/infer_tile_k14.py", "--video", L["video"], "--calib", CALIB, "--model", W,
                        "--output", TILE, "--seconds", "400"], env=env, check=True, capture_output=True)
    n = len(L["bounces"])
    print(f"bounces: {n}")
    print(f"{'arm':5s} {'seen':>6s} {'tracked':>8s} {'found':>10s} {'candidates':>11s} {'matching':>9s} {'med err ft':>10s}")
    found = {}
    for arm, csv_ in (("base", BASE), ("tile", TILE)):
        H, raw, tracked, cands = E.clip_points({"calib": CALIB, "csv": csv_})
        r = [recover({"frame": b["frame"], "x": b["x"], "y": b["y"], "visible": True}, raw, tracked, cands, H)
             for b in L["bounces"]]
        f = lambda k: sum(1 for x in r if x[k])
        errs = [x["cand_err_ft"] for x in r if x["found"]]
        med = percentile(errs, 0.5)
        lf = [b["frame"] for b in L["bounces"]]
        match = sum(1 for g in cands if any(abs(g - h) <= 3 for h in lf))
        found[arm] = f("found")
        print(f"{arm:5s} {f('seen') / n:6.0%} {f('tracked') / n:8.0%} {f('found'):4d} ({f('found') / n:3.0%}) "
              f"{len(cands):11d} {match:9d} {('%.2f' % med) if med is not None else '-':>10s}")
    t, b = found["tile"], found["base"]
    print("\nVERDICT:", "HOLDS (>= 40%)" if t >= 14 else "PARTLY HOLDS" if (t >= 10 and t > b) else "DOES NOT HOLD")


if __name__ == "__main__":
    main()
