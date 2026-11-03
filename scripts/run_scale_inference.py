"""Production inference (pod_infer.py, court mask, k14 weights) on cache/scale_plan.json sessions (usable only)."""
import glob, json, os, subprocess
plan = [c for c in json.load(open("cache/scale_plan.json")) if c["use"]]
TF = "/mnt/fast_scratch/tf215_env/venv/bin/python"; W = "/mnt/fast_scratch/tracknet_weights/weights_k14_epoch19"
env = dict(os.environ)
env["LD_LIBRARY_PATH"] = ":".join(glob.glob("/mnt/fast_scratch/tf215_env/venv/lib/python*/site-packages/nvidia/*/lib") + [env.get("LD_LIBRARY_PATH", "")])
os.makedirs("cache/scale", exist_ok=True)
for i, c in enumerate(plan, 1):
    name = f"{c['cam']}_{c['rec']}_{os.path.basename(c['path'])[:-4]}"
    out = f"cache/scale/{name}.csv"
    json.dump({"calib": c["calib"], "path": c["path"], "dist": c["dist"]}, open(f"cache/scale/{name}.meta.json", "w"))
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        print(f"[{i}/{len(plan)}] skip {name}", flush=True); continue
    print(f"[{i}/{len(plan)}] {name}", flush=True)
    r = subprocess.run([TF, "scripts/pod_infer.py", "--video", c["path"], "--calib", c["calib"], "--model", W, "--output", out], env=env)
    if r.returncode != 0:
        # pod_infer refuses a video that decodes < 98% of its frames (truncated decode): excluded, not guessed
        open("cache/scale/FAILED.txt", "a").write(f"{name}\t{r.returncode}\n")
        if os.path.exists(out): os.remove(out)
print("DONE", flush=True)
