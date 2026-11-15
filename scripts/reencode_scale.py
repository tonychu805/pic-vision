"""Re-encode the scale-test sessions that failed the 98% decode guard to constant frame rate (CFR), the
fix pod_infer.py prints, then run inference on the result. Output cache/scale_reenc/<name>.mp4 (git-ignored).
Names come from cache/scale/FAILED.txt; the source path from cache/scale_plan.json.
  ffmpeg -err_detect ignore_err -i IN -c:v h264_nvenc -preset p4 -cq 20 -an -fps_mode cfr -r 30 OUT.mp4
Run: .venv/bin/python scripts/reencode_scale.py [encode|infer]
"""
import glob, json, os, subprocess, sys

TF = "/mnt/fast_scratch/tf215_env/venv/bin/python"; W = "/mnt/fast_scratch/tracknet_weights/weights_k14_epoch19"


def failed():
    names = []
    for l in open("cache/scale/FAILED.txt"):
        n = l.split("\t")[0].strip()
        if n and n not in names: names.append(n)
    plan = {f"{c['cam']}_{c['rec']}_{os.path.basename(c['path'])[:-4]}": c for c in json.load(open("cache/scale_plan.json"))}
    return [(n, plan[n]) for n in names if n in plan]


def encode():
    os.makedirs("cache/scale_reenc", exist_ok=True)
    for n, c in failed():
        out = f"cache/scale_reenc/{n}.mp4"
        if os.path.exists(out) and os.path.getsize(out) > 1000: print("skip", n, flush=True); continue
        print("encode", n, flush=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-err_detect", "ignore_err", "-i", c["path"], "-c:v", "h264_nvenc",
                        "-preset", "p4", "-cq", "20", "-an", "-fps_mode", "cfr", "-r", "30", out], check=False)
    print("ENCODE DONE", flush=True)


def infer():
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = ":".join(glob.glob("/mnt/fast_scratch/tf215_env/venv/lib/python*/site-packages/nvidia/*/lib") + [env.get("LD_LIBRARY_PATH", "")])
    for n, c in failed():
        src = f"cache/scale_reenc/{n}.mp4"; out = f"cache/scale/{n}.csv"
        if not os.path.exists(src) or os.path.exists(out): continue
        json.dump({"calib": c["calib"], "path": src, "dist": c["dist"], "reencoded_from": c["path"]}, open(f"cache/scale/{n}.meta.json", "w"))
        print("infer", n, flush=True)
        r = subprocess.run([TF, "scripts/pod_infer.py", "--video", src, "--calib", c["calib"], "--model", W, "--output", out], env=env)
        if r.returncode != 0:
            open("cache/scale/FAILED_REENC.txt", "a").write(f"{n}\t{r.returncode}\n")
            if os.path.exists(out): os.remove(out)
    print("INFER DONE", flush=True)


if __name__ == "__main__":
    {"encode": encode, "infer": infer}[sys.argv[1]]()
