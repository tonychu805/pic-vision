"""Precision sample of detected rallies on the PGC field test (PIC-226).

Objective (fixed before cutting): of the rallies the production detector
reports on real venue footage, what fraction are actually rallies? ONLY "is it
a rally" (LABELING v5: >= 3 contacts, live ball until dead), never "is it a
good rally". Not recall. See the PIC-226 comment for the decision rule.

Sample = 20 random from all detected field rallies + 20 from the top 3 by
shipped score (src/select.score_segments) in each session. The 16 clips the
operator already judged (K L N P Q R O M, S..Z) are excluded. Seeded, shuffled,
silent, numbered 01..40. Key -> cache/precision_sample_key.csv (not shown).
"""
import csv, glob, json, os, random, subprocess, sys, zipfile
sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
import validate_absolute_ranking as base
from src.select import net_width_px, score_segments

DIR, OUT, SEED, PAD = "cache/pgc_fieldtest", "clips/precision_sample", 20261012, 1.0
N_RANDOM, N_TOP, TOP_PER_SESSION = 20, 20, 3

def judged_windows():
    w = []
    for f in ("cache/blind_check_key.csv", "cache/flag_check_key.csv"):
        for r in csv.DictReader(open(f)):
            sid8 = r["video"].split(":")[-1] if "video" in r else r["session"]
            if "video" in r and not r["video"].startswith("PGC"):
                continue
            w.append((sid8, float(r["start"]), float(r["end"])))
    return w

def overlaps(a0, a1, b0, b1):
    i = max(0.0, min(a1, b1) - max(a0, b0))
    return i / max(1e-6, (a1 - a0) + (b1 - b0) - i) >= 0.5

judged = judged_windows()
pool = []
for p in sorted(glob.glob(f"{DIR}/*.csv")):
    sid = os.path.basename(p)[:-4]
    calib = json.load(open(f"{DIR}/{sid}.calib.json"))
    segs, crossed, speeds = base.detect(p, calib)
    scored = score_segments(segs, crossed, speeds, net_width_px(calib))   # best first
    for rank, s in enumerate(scored, 1):
        if any(sid.startswith(j[0]) and overlaps(s["start"], s["end"], j[1], j[2]) for j in judged):
            continue
        pool.append({"sid": sid, "start": s["start"], "end": s["end"], "dur": s["end"] - s["start"],
                     "score": s["score"], "rank": rank})
rng = random.Random(SEED)
top_pool = [r for r in pool if r["rank"] <= TOP_PER_SESSION]
top = rng.sample(top_pool, min(N_TOP, len(top_pool)))
rest = [r for r in pool if r not in top]
rand = rng.sample(rest, min(N_RANDOM, len(rest)))
picks = [("top3", r) for r in top] + [("random", r) for r in rand]
rng.shuffle(picks)

os.makedirs(OUT, exist_ok=True)
rows = []
for i, (grp, r) in enumerate(picks, 1):
    name = f"{i:02d}"
    ss = max(0.0, r["start"] - PAD)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ss:.3f}", "-i", f"{DIR}/{r['sid']}.mp4",
                    "-t", f"{r['end'] - ss + PAD:.3f}", "-an", "-vf", "scale=-2:720", "-c:v", "libx264",
                    "-crf", "28", "-preset", "veryfast", "-pix_fmt", "yuv420p", f"{OUT}/{name}.mp4"], check=True)
    rows.append([name, r["sid"][:8], grp, f"{r['start']:.2f}", f"{r['end']:.2f}", f"{r['dur']:.1f}", f"{r['score']:.0f}", r["rank"]])
with open("cache/precision_sample_key.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["clip", "session", "group", "start", "end", "duration", "score", "rank_in_session"]); w.writerows(rows)

names = [r[0] for r in rows]
cards = "\n".join(f'''<section class="card"><h2>{n}</h2><video src="{n}.mp4" controls loop muted playsinline preload="metadata"></video>
<div class="opts" data-clip="{n}"><label><input type="radio" name="c{n}" value="real"> real rally</label>
<label><input type="radio" name="c{n}" value="short"> very short (serve + return only)</label>
<label><input type="radio" name="c{n}" value="not"> not a rally</label>
<label><input type="radio" name="c{n}" value="unsure"> can't tell</label></div></section>''' for n in names)
html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Is it a rally?</title><style>body{{font:16px/1.4 system-ui,sans-serif;margin:0;background:#111;color:#eee}}
header{{padding:16px;max-width:900px;margin:auto}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:16px;padding:0 16px 16px;max-width:1500px;margin:auto}}
.card{{background:#1c1c1e;border-radius:10px;padding:12px}}h2{{margin:0 0 8px}}video{{width:100%;border-radius:6px;background:#000}}
.opts{{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px;font-size:15px}}footer{{position:sticky;bottom:0;background:#000;padding:12px 16px;border-top:1px solid #333}}
button{{font:inherit;padding:8px 14px;border-radius:6px;border:0;background:#2f6feb;color:#fff;cursor:pointer}}
textarea{{width:100%;box-sizing:border-box;margin-top:8px;background:#111;color:#eee;border:1px solid #333;border-radius:6px;padding:8px}}</style></head><body>
<header><h1>Is this a rally?</h1>
<p><b>Only "is it a rally", not "is it a good one".</b> A dull rally is still a rally.</p>
<p><b>Real rally</b>: players hit the ball back and forth while it is live, at least 3 contacts (serve, return, one more shot), until the ball goes dead.<br>
<b>Very short</b>: a serve and a return only, then dead. Counted as NOT a rally, but ticked separately.<br>
<b>Not a rally</b>: failed serve or fault, tossing or retrieving a ball, picking balls up, warm-up dinking, a tap back to the server after the point.<br>
<b>Can't tell</b> is fine. Judge what you see on the clip.</p></header>
<div class="grid">{cards}</div>
<footer><span id="count">0 / {len(names)} answered</span> <button id="copy">Copy my answers</button>
<textarea id="out" rows="3" readonly placeholder="Paste this to Claude."></textarea></footer>
<script>const out=document.getElementById('out'),count=document.getElementById('count');
function update(){{const p=[];let n=0;document.querySelectorAll('.opts').forEach(g=>{{const c=g.querySelector('input:checked');if(c){{n++;p.push(g.dataset.clip+'='+c.value)}}}});
count.textContent=n+' / {len(names)} answered';out.value=p.join(', ')}}
document.addEventListener('change',update);document.getElementById('copy').onclick=()=>{{out.select();document.execCommand('copy')}};</script></body></html>'''
open(f"{OUT}/review.html", "w").write(html)
sizes = []
z = "clips/precision_sample_review.zip"
with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
    for f in sorted(os.listdir(OUT)):
        zf.write(f"{OUT}/{f}", arcname=f"precision_sample/{f}")
g = lambda grp, k: [float(r[k]) for r in rows if r[2] == grp]
print(f"pool after excluding judged: {len(pool)} rallies; top-3 pool {len(top_pool)}")
print(f"cut {len(rows)} clips ({sum(1 for r in rows if r[2]=='random')} random, {sum(1 for r in rows if r[2]=='top3')} top-3); "
      f"{len({r[1] for r in rows})} sessions represented")
print(f"clip length {min(float(r[5]) for r in rows):.0f}-{max(float(r[5]) for r in rows):.0f}s; zip {os.path.getsize(z)/1048576:.1f} MB")
