"""Verify the 'scenery-heavy' false alarms by eye (PIC-226).

For judged not-real clips (very short, or not-a-rally excluding practice) where
>= 30% of the detector's tracked points fall in globally hot squares (>= 20x the
median re-detection count in that recording), draw red rings on those fixed
spots and a green trail on the path the detector followed. 3 s padding as the
reel does. Question for the operator: what is at the red rings (light / glare /
dots, the ball, a person, other), and is there a real rally. Silent, 720p.
Internal review of third-party venue footage; do not share.
"""
import collections, csv, glob, json, os, statistics, subprocess, sys, zipfile
import cv2
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import validate_absolute_ranking as base
import summarise_top_sample as S
from src.calib import court_wedge
from src.track import track_ball
from src.tracknet import load_predictions
DIR, OUT, SQ, PAD = "cache/pgc_fieldtest", "clips/hotspot_check", 12, 3.0
os.makedirs(OUT, exist_ok=True)
cache = {}
def prep(sid):
    if sid in cache: return cache[sid]
    calib = json.load(open(f"{DIR}/{sid}.calib.json")); tr = load_predictions(f"{DIR}/{sid}.csv", 30.0)
    w = court_wedge(calib); times = [t for t, *_ in tr]
    fr = [[(x, y, c if c is not None else 1.0)] if w(x, y) else [] for _, x, y, _w, _h, c in tr]
    ys, xs = track_ball(fr, max_jump=150, reset_after=15, return_x=True)
    cnt = collections.Counter((round(x / SQ), round(y / SQ)) for _, x, y, *_ in tr if x is not None)
    med = statistics.median(cnt.values()); hot = {s for s, n in cnt.items() if n >= 20 * med}
    segs, cr, _ = base.detect(f"{DIR}/{sid}.csv", calib)
    cache[sid] = (times, xs, ys, hot, segs); return cache[sid]
picks = []
for (sid, a, b), (verdict, why) in S.v.items():
    if verdict not in ("short", "not"): continue
    if verdict == "not" and why and any(k in why for k in ("machine", "warm", "feeding", "practice")): continue
    times, xs, ys, hot, segs = prep(sid)
    best = max(segs, key=lambda s: base.iou({"start": a, "end": b}, s), default=None)
    if best is None or base.iou({"start": a, "end": b}, best) < 0.5: continue
    pts = [(round(xs[i] / SQ), round(ys[i] / SQ)) for i, t in enumerate(times) if ys[i] is not None and best["start"] <= t <= best["end"]]
    if len(pts) < 8: continue
    share = sum(1 for p in pts if p in hot) / len(pts)
    if share >= 0.30:
        picks.append({"sid": sid, "start": best["start"], "end": best["end"], "share": share, "verdict": verdict, "why": why})
print(f"scenery-heavy not-real clips: {len(picks)} ({sum(p['verdict']=='short' for p in picks)} very short, {sum(p['verdict']=='not' for p in picks)} other)")
rows = []
for i, p in enumerate(picks, 1):
    name = f"{200 + i}"
    times, xs, ys, hot, segs = prep(p["sid"])
    used = {(round(xs[k] / SQ), round(ys[k] / SQ)) for k, t in enumerate(times) if ys[k] is not None and p["start"] <= t <= p["end"]} & hot
    cap = cv2.VideoCapture(f"{DIR}/{p['sid']}.mp4"); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    s0 = max(0.0, p["start"] - PAD); cap.set(cv2.CAP_PROP_POS_FRAMES, int(s0 * fps))
    W, H = int(cap.get(3)), int(cap.get(4)); tmp = f"{OUT}/_{name}.mp4"
    vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    n = int((p["end"] + PAD - s0) * fps)
    f0 = int(s0 * fps)
    for j in range(n):
        ok, fr = cap.read()
        if not ok: break
        for (sx, sy) in used:
            cv2.circle(fr, (sx * SQ, sy * SQ), 26, (0, 0, 255), 3)
        for back in range(0, 20):                      # trail of the last ~0.6 s of tracked points
            k = f0 + j - back
            if 0 <= k < len(ys) and ys[k] is not None:
                cv2.circle(fr, (int(xs[k]), int(ys[k])), 6 if back == 0 else 3, (60, 220, 60), -1)
        inside = p["start"] <= (f0 + j) / fps <= p["end"]
        cv2.putText(fr, f"red ring = fixed bright spot   green = path the detector followed   {'RALLY WINDOW' if inside else ''}",
                    (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        vw.write(fr)
    vw.release(); cap.release()
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", tmp, "-an", "-vf", "scale=-2:720", "-c:v", "libx264", "-crf", "28",
                    "-preset", "veryfast", "-pix_fmt", "yuv420p", f"{OUT}/{name}.mp4"], check=True)
    os.remove(tmp)
    rows.append([name, p["sid"][:8], p["verdict"], p["why"], f"{p['start']:.2f}", f"{p['end']:.2f}", f"{p['share']:.2f}"])
with open("cache/hotspot_check_key.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["clip", "session", "verdict", "why", "start", "end", "share_in_fixed_spots"]); w.writerows(rows)
names = [r[0] for r in rows]
cards = "\n".join(f'''<section class="card"><h2>{n}</h2><video src="{n}.mp4" controls loop muted playsinline preload="metadata"></video>
<div class="q"><b>What is inside the red rings?</b><div class="opts" data-clip="{n}" data-q="ring">
<label><input type="radio" name="r{n}" value="light/glare/dots"> light, glare or bright dots</label>
<label><input type="radio" name="r{n}" value="ball"> the ball</label><label><input type="radio" name="r{n}" value="person"> a person / clothing</label>
<label><input type="radio" name="r{n}" value="other"> something else</label><label><input type="radio" name="r{n}" value="nothing"> nothing visible</label></div></div>
<div class="q"><b>Is there a real rally in this clip?</b><div class="opts" data-clip="{n}" data-q="rally">
<label><input type="radio" name="y{n}" value="yes"> yes</label><label><input type="radio" name="y{n}" value="short"> only serve + return</label>
<label><input type="radio" name="y{n}" value="no"> no</label></div></div></section>''' for n in names)
html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>What are the red rings?</title><style>body{{font:16px/1.4 system-ui,sans-serif;margin:0;background:#111;color:#eee}}header{{padding:16px;max-width:900px;margin:auto}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px;padding:0 16px 16px;max-width:1500px;margin:auto}}.card{{background:#1c1c1e;border-radius:10px;padding:12px}}
h2{{margin:0 0 8px}}video{{width:100%;border-radius:6px;background:#000}}.q{{margin-top:10px;font-size:15px}}.opts{{display:flex;gap:10px;flex-wrap:wrap;margin-top:4px}}
footer{{position:sticky;bottom:0;background:#000;padding:12px 16px;border-top:1px solid #333}}button{{font:inherit;padding:8px 14px;border-radius:6px;border:0;background:#2f6feb;color:#fff;cursor:pointer}}
textarea{{width:100%;box-sizing:border-box;margin-top:8px;background:#111;color:#eee;border:1px solid #333;border-radius:6px;padding:8px}}</style></head><body>
<header><h1>What are the red rings?</h1><p>Red rings mark spots the detector keeps marking as "the ball" across the whole recording. The green dots are the path it followed.
Watch the whole clip. These are clips you called not a rally or very short; I want to know whether the rings are lights/glare or something else.</p></header>
<div class="grid">{cards}</div><footer><span id="count">0 answered</span> <button id="copy">Copy my answers</button>
<textarea id="out" rows="3" readonly placeholder="Paste this to Claude."></textarea></footer>
<script>const out=document.getElementById('out'),count=document.getElementById('count');
function update(){{const m={{}};let n=0;document.querySelectorAll('.opts').forEach(g=>{{const c=g.querySelector('input:checked');if(c){{n++;(m[g.dataset.clip]=m[g.dataset.clip]||[]).push(g.dataset.q+':'+c.value)}}}});
count.textContent=n+' answers';out.value=Object.entries(m).map(([k,v])=>k+' ['+v.join(', ')+']').join('; ')}}
document.addEventListener('change',update);document.getElementById('copy').onclick=()=>{{out.select();document.execCommand('copy')}};</script></body></html>'''
open(f"{OUT}/review.html", "w").write(html)
z = "clips/hotspot_check_review.zip"
with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
    for f in sorted(os.listdir(OUT)):
        zf.write(f"{OUT}/{f}", arcname=f"hotspot_check/{f}")
print(f"clips {names[0]}..{names[-1]}; zip {os.path.getsize(z)/1048576:.1f} MB")
