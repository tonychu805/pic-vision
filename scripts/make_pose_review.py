"""Body-point overlay for operator playback review (PIC-226).

The pose coverage numbers (EXPERIMENTS.md 2026-10-13 pose coverage) are the
model's own confidence, not correctness. This draws the points on 7 of the judged
fresh clips so the operator can judge in playback: are the points on the right
body parts, near and far, and can a swing be seen in them?
Window rally start - 3 s to + 2 s, 30 fps, silent, 720p; near-side people
orange, far-side people cyan; points with confidence >= 0.5 only. Clip numbers
401.. are shuffled; key in cache/pose_review_key.csv. Internal review of
third-party venue footage; do not share, delete after review.
"""
import csv, glob, json, os, random, shutil, subprocess, sys, zipfile
sys.path.insert(0, ".")
import cv2
import numpy as np

SRC = ["303", "307", "318", "323", "301", "316", "306"]
JOB = os.environ.get("CLAUDE_JOB_DIR", "/home/tonychu/.claude/jobs/b3136fb4") + "/tmp"
OUT = "clips/pose_review"
PRE, POST = 3.0, 2.0
EDGES = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (0, 1), (0, 2)]
COL = {"near": (0, 140, 255), "far": (255, 220, 0)}      # BGR


def main():
    from ultralytics import YOLO
    model = YOLO("yolov8x-pose.pt")
    key = {r["clip"]: r for r in csv.DictReader(open("cache/fresh_sample_key.csv"))}
    order = SRC[:]
    random.Random(20261013).shuffle(order)
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for i, src in enumerate(order, 1):
        r = key[src]; name = f"{400 + i}"
        m = json.load(open(f"cache/fresh/{r['segment']}.meta.json"))
        H = np.array(json.load(open(m["calib"]))["homography"], dtype=np.float32)
        s0 = max(0.0, float(r["start"]) - PRE)
        d = f"{JOB}/posev_{name}"; shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s0:.3f}", "-i", m["path"], "-t", f"{PRE + POST:.1f}",
                        "-an", "-vf", "fps=30", f"{d}/%04d.png"], check=True)
        files = sorted(glob.glob(f"{d}/*.png"))
        raw = f"{d}/raw.mp4"
        vw = None
        for fi, f in enumerate(files):
            img = cv2.imread(f)
            res = model.predict(img, imgsz=1280, conf=0.25, classes=[0], verbose=False)[0]
            if res.boxes is not None and len(res.boxes):
                for b, k, c in zip(res.boxes.xyxy.cpu().numpy(), res.keypoints.xy.cpu().numpy(), res.keypoints.conf.cpu().numpy()):
                    fx, fy = (b[0] + b[2]) / 2.0, b[3]
                    cx_, cy_ = cv2.perspectiveTransform(np.array([[[fx, fy]]], dtype=np.float32), H)[0, 0]
                    if not (-6 <= cx_ <= 26 and -6 <= cy_ <= 50):
                        continue
                    col = COL["near" if cy_ < 22.0 else "far"]
                    for a, bb in EDGES:
                        if c[a] >= 0.5 and c[bb] >= 0.5:
                            cv2.line(img, (int(k[a][0]), int(k[a][1])), (int(k[bb][0]), int(k[bb][1])), col, 2, cv2.LINE_AA)
                    for j in range(17):
                        if c[j] >= 0.5:
                            cv2.circle(img, (int(k[j][0]), int(k[j][1])), 5 if j in (9, 10) else 3, (255, 255, 255) if j in (9, 10) else col, -1, cv2.LINE_AA)
            cv2.putText(img, f"{name}  {s0 + fi / 30.0 - float(r['start']):+.1f}s", (24, 54), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3, cv2.LINE_AA)
            if vw is None:
                vw = cv2.VideoWriter(raw, cv2.VideoWriter_fourcc(*"mp4v"), 30, (img.shape[1], img.shape[0]))
            vw.write(img)
        vw.release()
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-an", "-vf", "scale=-2:720", "-c:v", "libx264",
                        "-crf", "26", "-preset", "veryfast", "-pix_fmt", "yuv420p", f"{OUT}/{name}.mp4"], check=True)
        shutil.rmtree(d, ignore_errors=True)
        rows.append([name, src, r["segment"][:8], r["start"]])
        print("done", name, flush=True)
    with open("cache/pose_review_key.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["clip", "source_clip", "segment", "start"]); w.writerows(rows)

    names = [x[0] for x in rows]
    cards = "\n".join(f'''<section class="card"><h2>{n}</h2><video src="{n}.mp4" controls loop muted playsinline preload="metadata"></video>
<div class="q"><b>Orange = near side, cyan = far side, white dots = wrists.</b></div>
<div class="opts" data-q="{n}_near">Near side points on the right body parts?
<label><input type="radio" name="{n}_near" value="yes"> yes</label><label><input type="radio" name="{n}_near" value="mostly"> mostly</label><label><input type="radio" name="{n}_near" value="no"> no</label></div>
<div class="opts" data-q="{n}_far">Far side points on the right body parts?
<label><input type="radio" name="{n}_far" value="yes"> yes</label><label><input type="radio" name="{n}_far" value="mostly"> mostly</label><label><input type="radio" name="{n}_far" value="no"> no</label></div>
<div class="opts" data-q="{n}_swing">Can you see swings (arm moves) in the dots?
<label><input type="radio" name="{n}_swing" value="clearly"> clearly</label><label><input type="radio" name="{n}_swing" value="barely"> barely</label><label><input type="radio" name="{n}_swing" value="no"> no</label></div>
<input class="why" data-clip="{n}" placeholder="anything off? (people missed, spectators boxed, points jumping...)"></section>''' for n in names)
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Body points review</title><style>body{{font:16px/1.4 system-ui,sans-serif;margin:0;background:#111;color:#eee}}header{{padding:16px;max-width:900px;margin:auto}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px;padding:0 16px 16px;max-width:1500px;margin:auto}}
.card{{background:#1c1c1e;border-radius:10px;padding:12px}}h2{{margin:0 0 8px}}video{{width:100%;border-radius:6px;background:#000}}
.opts{{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px;font-size:15px;align-items:center}}.why{{width:100%;box-sizing:border-box;margin-top:8px;background:#111;color:#eee;border:1px solid #333;border-radius:6px;padding:6px}}
footer{{position:sticky;bottom:0;background:#000;padding:12px 16px;border-top:1px solid #333}}button{{font:inherit;padding:8px 14px;border-radius:6px;border:0;background:#2f6feb;color:#fff;cursor:pointer}}
textarea{{width:100%;box-sizing:border-box;margin-top:8px;background:#111;color:#eee;border:1px solid #333;border-radius:6px;padding:8px}}</style></head><body>
<header><h1>Body points review</h1><p>Seven short clips with the body points drawn on. Judge in playback: are the dots on the right body parts, and can you see the arms swing?
Clip time 0.0 s is the detected rally start; clips run from 3 s before to 2 s after. Internal review only.</p></header><div class="grid">{cards}</div>
<footer><span id="count">0 answered</span> <button id="copy">Copy my answers</button><textarea id="out" rows="3" readonly placeholder="Paste this to Claude."></textarea></footer>
<script>const out=document.getElementById('out'),count=document.getElementById('count');
function update(){{const p=[];let n=0;document.querySelectorAll('.opts').forEach(g=>{{const c=g.querySelector('input:checked');if(c){{n++;p.push(g.dataset.q+'='+c.value)}}}});
document.querySelectorAll('.why').forEach(w=>{{if(w.value.trim())p.push(w.dataset.clip+'_note=('+w.value.trim()+')')}});
count.textContent=n+' answered';out.value=p.join(', ')}}
document.addEventListener('change',update);document.addEventListener('input',update);document.getElementById('copy').onclick=()=>{{out.select();document.execCommand('copy')}};</script></body></html>'''
    open(f"{OUT}/review.html", "w").write(html)
    z = "clips/pose_review.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
        for f in sorted(os.listdir(OUT)):
            zf.write(f"{OUT}/{f}", arcname=f"pose_review/{f}")
    print(f"{z}: {os.path.getsize(z)/1048576:.1f} MB")


if __name__ == "__main__":
    main()
