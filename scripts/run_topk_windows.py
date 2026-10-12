"""Build the inference windows for Test B and run scripts/infer_topk.py on each video (PIC-226)."""
import collections, glob, json, os, subprocess, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import validate_absolute_ranking as base
import summarise_top_sample as S            # operator verdicts (S.v), prints its summary once
PRE, POST = 8.0, 3.0
TF = "/mnt/fast_scratch/tf215_env/venv/bin/python"
WEIGHTS = "/mnt/fast_scratch/tracknet_weights/weights_k14_epoch19"
jobs = collections.defaultdict(list)       # name -> [(video, calib, [(s,e)])]
# field: every judged clip + the hot-spot clips (already inside S.v)
for (sid, a, b), _ in S.v.items():
    jobs[("field", sid)].append((max(0.0, a - PRE), b + POST))
# dev: every graded rally the production detector matched
for name, csvp, calibp, labp, wend in base.SESSIONS:
    calib = json.load(open(calibp)); segs, _, _ = base.detect(csvp, calib)
    if wend: segs = [s for s in segs if s["end"] <= wend]
    labs = [r for r in (json.loads(l) for l in open(labp) if l.strip()) if r.get("quality") in (1, 2) and (wend is None or r["end"] <= wend)]
    for lab in labs:
        m = base.best_match(lab, segs)
        if m: jobs[("dev", name)].append((max(0.0, m["start"] - PRE), m["end"] + POST))
VIDEO = {"brickwall_30fps": "videos/brickwall_30fps.mp4", "brickwall-SEMI": "videos/brickwall_semi_30fps.mp4",
         "pb_draft_cup": "videos/pb_draft_cup_30fps.mp4", "IMG_7744": "videos/IMG_7744_fixed.mp4"}
CALIB = {n: c for n, _, c, _, _ in base.SESSIONS}
os.makedirs("cache/topk", exist_ok=True)
total = 0
plan = []
for (kind, key), wins in sorted(jobs.items()):
    wins.sort(); merged = []
    for s, e in wins:
        if merged and s <= merged[-1][1] + 1.0: merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else: merged.append((s, e))
    secs = sum(e - s for s, e in merged); total += secs
    video = f"cache/pgc_fieldtest/{key}.mp4" if kind == "field" else VIDEO[key]
    calib = f"cache/pgc_fieldtest/{key}.calib.json" if kind == "field" else CALIB[key]
    out = f"cache/topk/{key[:8] if kind=='field' else key}.csv"
    plan.append((video, calib, merged, out, secs))
print(f"{len(plan)} videos, {sum(len(p[2]) for p in plan)} windows, {total:.0f} s of video = {total*30/60/60:.1f} k-min at 30 fps; ~{total*30/32/60:.0f} min at 32 fps", flush=True)
env = dict(os.environ)
libs = glob.glob("/mnt/fast_scratch/tf215_env/venv/lib/python*/site-packages/nvidia/*/lib")
env["LD_LIBRARY_PATH"] = ":".join(libs + [env.get("LD_LIBRARY_PATH", "")])
for i, (video, calib, merged, out, secs) in enumerate(plan, 1):
    if os.path.exists(out) and os.path.getsize(out) > 20:
        print(f"[{i}/{len(plan)}] skip (exists) {out}", flush=True); continue
    w = ",".join(f"{s:.2f}:{e:.2f}" for s, e in merged)
    print(f"[{i}/{len(plan)}] {video}  {len(merged)} windows, {secs:.0f}s", flush=True)
    subprocess.run([TF, "scripts/infer_topk.py", "--video", video, "--calib", calib, "--model", WEIGHTS,
                    "--windows", w, "--output", out], env=env, check=True)
print("DONE", flush=True)
