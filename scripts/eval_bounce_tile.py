"""Does seeing the ball more often turn into more bounces found? (2026-10-15)

Question. On the 42 hand-labelled bounces of the 18 PGC pilot clips, the default finder found
14% (6) with the ball tracked at 74%. Loss analysis: most misses had too few tracked points around
the bounce. The tile arm (scripts/infer_tile_k14.py) made k14 see the ball on 45% -> 63% of frames
on two public excerpts. Does that raise bounces found on PGC?

Arms, both run on the cut clips in clips/bounce_pilot/ (so the comparison is like for like):
  base  scripts/pod_infer.py, whole frame, court mask (the shipped route)
  tile  scripts/infer_tile_k14.py, two overlapping tiles, rule unchanged from 2026-10-13
Same weights (k14), same calibration per clip, same tracker and finder rules (unchanged).
Scored as eval_bounce_recovery.py does: +-3 frames, 15 px; label frame -> clip frame is
frame - ceil(start x 30).

BAR, fixed BEFORE the run:
  clears the bar   tile found >= 40% of 42 (17 or more)   [the pilot's own bar]
  informative gain tile found >= 28% (12 or more, twice the base arm's 6) -- worth pursuing
  no help          tile found < 12
Also reported, not gated: seen / tracked shares, candidates inside the clips and how many match a label.
Run: .venv/bin/python scripts/eval_bounce_tile.py   (needs the TF 2.15 env; ~10 min)
"""
import glob, json, math, os, subprocess, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
from src.bounce_eval import near_half, percentile, recover
import eval_bounce_recovery as E

TF = "/mnt/fast_scratch/tf215_env/venv/bin/python"
W = "/mnt/fast_scratch/tracknet_weights/weights_k14_epoch19"
OUT = "cache/bounce_pilot"


def infer(arm, clip, calib):
    out = f"{OUT}/{clip}.{arm}.csv"
    if os.path.exists(out) and os.path.getsize(out) > 500:
        return out
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = ":".join(glob.glob("/mnt/fast_scratch/tf215_env/venv/lib/python*/site-packages/nvidia/*/lib")
                                      + [env.get("LD_LIBRARY_PATH", "")])
    video = f"clips/bounce_pilot/{clip}.mp4"
    if arm == "base":
        cmd = [TF, "scripts/pod_infer.py", "--video", video, "--calib", calib, "--model", W, "--output", out]
    else:
        cmd = [TF, "scripts/infer_tile_k14.py", "--video", video, "--calib", calib, "--model", W, "--output", out,
               "--seconds", "60"]
    subprocess.run(cmd, env=env, check=True, capture_output=True)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    sample = {c["id"]: c for c in json.load(open("eval/labels/bounces/sample.json"))["clips"]}
    labs = [json.loads(l) for l in open("eval/labels/bounces/labels.jsonl")]
    res = {"base": [], "tile": []}
    cands_n = {"base": [0, 0], "tile": [0, 0]}
    seen_frames = {"base": [0, 0], "tile": [0, 0]}
    for l in labs:
        c = sample[l["clip"]]
        first = math.ceil(c["start"] * 30 - 1e-6)
        for arm in ("base", "tile"):
            csv_ = infer(arm, l["clip"], c["calib"])
            H, raw, tracked, cands = E.clip_points({"calib": c["calib"], "csv": csv_})
            n = max(raw) + 1 if raw else 1
            seen_frames[arm][0] += len(raw); seen_frames[arm][1] += n
            fr = [b["frame"] - first for b in l["bounces"]]
            cands_n[arm][0] += len(cands)
            cands_n[arm][1] += sum(1 for g in cands if any(abs(g - f) <= 3 for f in fr))
            for b, f in zip(l["bounces"], fr):
                res[arm].append(recover({"frame": f, "x": b["x"], "y": b["y"], "visible": True}, raw, tracked, cands, H))
        print(l["clip"], flush=True)
    n = len(res["base"])
    print(f"\nbounces: {n}")
    print(f"{'arm':5s} {'frames w/ ball':>14s} {'seen':>6s} {'tracked':>8s} {'found':>10s} {'candidates':>11s} {'matching':>9s} {'med err ft':>10s}")
    for arm in ("base", "tile"):
        r = res[arm]
        f = lambda k: sum(1 for x in r if x[k])
        errs = [x["cand_err_ft"] for x in r if x["found"]]
        med = percentile(errs, 0.5)
        print(f"{arm:5s} {seen_frames[arm][0] / seen_frames[arm][1]:14.0%} {f('seen') / n:6.0%} {f('tracked') / n:8.0%} "
              f"{f('found'):4d} ({f('found') / n:3.0%}) {cands_n[arm][0]:11d} {cands_n[arm][1]:9d} "
              f"{('%.2f' % med) if med is not None else '-':>10s}")
    t = sum(1 for x in res["tile"] if x["found"])
    print("\nVERDICT:", "CLEARS the bar (>= 40%)" if t >= 17 else "informative gain (>= 28%)" if t >= 12 else "no help (< 12 found)")


if __name__ == "__main__":
    main()
