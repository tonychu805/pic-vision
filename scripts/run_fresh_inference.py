"""Run production inference (scripts/pod_infer.py, court mask, k14 weights) on the fresh segments (PIC-226)."""
import glob, json, os, subprocess, sys
plan = json.load(open("cache/fresh_plan.json"))
TF = "/mnt/fast_scratch/tf215_env/venv/bin/python"; W = "/mnt/fast_scratch/tracknet_weights/weights_k14_epoch19"
env = dict(os.environ)
env["LD_LIBRARY_PATH"] = ":".join(glob.glob("/mnt/fast_scratch/tf215_env/venv/lib/python*/site-packages/nvidia/*/lib") + [env.get("LD_LIBRARY_PATH", "")])
os.makedirs("cache/fresh", exist_ok=True)
for i, c in enumerate(plan, 1):
    name = f"{c['cam']}_{c['path'].split('/')[2][:19]}_{os.path.basename(c['path'])[:-4]}"
    out = f"cache/fresh/{name}.csv"
    json.dump({"calib": c["calib"], "court": c["court"], "path": c["path"], "dist": c["dist"]}, open(f"cache/fresh/{name}.meta.json", "w"))
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        print(f"[{i}/{len(plan)}] skip {name}", flush=True); continue
    print(f"[{i}/{len(plan)}] {name}", flush=True)
    subprocess.run([TF, "scripts/pod_infer.py", "--video", c["path"], "--calib", c["calib"], "--model", W, "--output", out], env=env, check=True)
print("DONE", flush=True)
