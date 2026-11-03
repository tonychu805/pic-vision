"""Precision at the TOP of each session's ranking (PIC-226).

The reel takes each session's top rallies by the shipped score (build_top_rallies,
n=10), so what a player sees is the head of this ranking. Earlier samples mixed
random and top-3 clips; this takes the top TOP per session (production ranking:
src.rallies.detect_candidates + src.select.score_segments) and excludes every clip
the operator has already judged. Silent, 720p, shuffled, numbered 101.. so they
cannot be confused with earlier sets; key in cache/ (not shown).

Question: of the clips a reel would actually lead with, what share are real
rallies (LABELING v5: live ball, >= 3 contacts, until dead)? Bar, written before
cutting: at least 80% real (no more than 1 bad clip in 5).
Internal review of third-party venue footage; do not share.
"""
import csv, glob, json, os, random, subprocess, sys, zipfile
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import validate_absolute_ranking as base
from src.select import net_width_px, score_segments

TOP, SEED, PAD, ZIP_MB = 5, 20261013, 1.0, 24
DIR, OUT = "cache/pgc_fieldtest", "clips/top_sample"

def sid_of(p): return [x.split("/")[-1][:-4] for x in glob.glob(f"{DIR}/*.csv") if x.split("/")[-1].startswith(p)][0]
judged = []
for f, col in (("cache/blind_check_key.csv", None), ("cache/flag_check_key.csv", "session"), ("cache/precision_sample_key.csv", "session")):
    for r in csv.DictReader(open(f)):
        if col is None:
            if not r["video"].startswith("PGC"): continue
            p = r["video"].split(":")[-1]
        else:
            p = r[col]
        judged.append((sid_of(p), float(r["start"]), float(r["end"])))
def overlaps(a0, a1, b0, b1):
    i = max(0.0, min(a1, b1) - max(a0, b0)); return i / max(1e-6, (a1 - a0) + (b1 - b0) - i) >= 0.5

picks, per_session = [], {}
for p in sorted(glob.glob(f"{DIR}/*.csv")):
    sid = os.path.basename(p)[:-4]
    calib = json.load(open(f"{DIR}/{sid}.calib.json"))
    segs, cr, sp = base.detect(p, calib)
    ranked = score_segments(segs, cr, sp, net_width_px(calib))      # best first
    head = ranked[:TOP]
    per_session[sid[:8]] = len(ranked)
    for rank, s in enumerate(head, 1):
        if any(j[0] == sid and overlaps(s["start"], s["end"], j[1], j[2]) for j in judged):
            continue
        picks.append({"sid": sid, "start": s["start"], "end": s["end"], "dur": s["end"] - s["start"], "score": s["score"], "rank": rank})
random.Random(SEED).shuffle(picks)
print(f"{len(per_session)} sessions; top {TOP} each = {TOP*len(per_session)} slots; already judged {TOP*len(per_session)-len(picks)}; new clips to review: {len(picks)}")

os.makedirs(OUT, exist_ok=True)
rows = []
for i, r in enumerate(picks, 1):
    name = f"{100 + i}"
    ss = max(0.0, r["start"] - PAD)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ss:.3f}", "-i", f"{DIR}/{r['sid']}.mp4",
                    "-t", f"{r['end'] - ss + PAD:.3f}", "-an", "-vf", "scale=-2:720", "-c:v", "libx264",
                    "-crf", "30", "-preset", "veryfast", "-pix_fmt", "yuv420p", f"{OUT}/{name}.mp4"], check=True)
    rows.append([name, r["sid"][:8], r["rank"], f"{r['score']:.0f}", f"{r['start']:.2f}", f"{r['end']:.2f}", f"{r['dur']:.1f}"])
with open("cache/top_sample_key.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["clip", "session", "rank_in_session", "score", "start", "end", "duration"]); w.writerows(rows)

def page(names, title):
    cards = "\n".join(f'''<section class="card"><h2>{n}</h2><video src="{n}.mp4" controls loop muted playsinline preload="metadata"></video>
<div class="opts" data-clip="{n}"><label><input type="radio" name="c{n}" value="real"> real rally</label>
<label><input type="radio" name="c{n}" value="short"> very short (serve + return only)</label>
<label><input type="radio" name="c{n}" value="not"> not a rally</label>
<label><input type="radio" name="c{n}" value="unsure"> can't tell</label></div>
<input class="why" data-clip="{n}" placeholder="if not a rally: what was it? (warm-up, ball machine, feeding, other)"></section>''' for n in names)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>body{{font:16px/1.4 system-ui,sans-serif;margin:0;background:#111;color:#eee}}header{{padding:16px;max-width:900px;margin:auto}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:16px;padding:0 16px 16px;max-width:1500px;margin:auto}}
.card{{background:#1c1c1e;border-radius:10px;padding:12px}}h2{{margin:0 0 8px}}video{{width:100%;border-radius:6px;background:#000}}
.opts{{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px;font-size:15px}}.why{{width:100%;box-sizing:border-box;margin-top:8px;background:#111;color:#eee;border:1px solid #333;border-radius:6px;padding:6px}}
footer{{position:sticky;bottom:0;background:#000;padding:12px 16px;border-top:1px solid #333}}button{{font:inherit;padding:8px 14px;border-radius:6px;border:0;background:#2f6feb;color:#fff;cursor:pointer}}
textarea{{width:100%;box-sizing:border-box;margin-top:8px;background:#111;color:#eee;border:1px solid #333;border-radius:6px;padding:8px}}</style></head><body>
<header><h1>{title}</h1><p><b>Only "is it a rally", not "is it a good one".</b> Real = ball hit back and forth while live, at least 3 contacts, until dead.
Very short = serve and return only. Not a rally = failed serve/fault, toss or feeding, picking up balls, warm-up, ball-machine drill, a tap back after the point.
If it's not a rally, a few words on what it was is very useful.</p></header><div class="grid">{cards}</div>
<footer><span id="count">0 answered</span> <button id="copy">Copy my answers</button><textarea id="out" rows="3" readonly placeholder="Paste this to Claude."></textarea></footer>
<script>const out=document.getElementById('out'),count=document.getElementById('count');
function update(){{const p=[];let n=0;document.querySelectorAll('.opts').forEach(g=>{{const c=g.querySelector('input:checked');if(c){{n++;const w=document.querySelector('.why[data-clip="'+g.dataset.clip+'"]').value.trim();p.push(g.dataset.clip+'='+c.value+(w?' ('+w+')':''))}}}});
count.textContent=n+' answered';out.value=p.join(', ')}}
document.addEventListener('change',update);document.addEventListener('input',update);document.getElementById('copy').onclick=()=>{{out.select();document.execCommand('copy')}};</script></body></html>'''

# split into zips under the upload limit
names = [r[0] for r in rows]
parts, cur, size = [], [], 0.0
for n in names:
    s = os.path.getsize(f"{OUT}/{n}.mp4") / 1048576
    if cur and size + s > ZIP_MB:
        parts.append(cur); cur, size = [], 0.0
    cur.append(n); size += s
if cur: parts.append(cur)
for k, part in enumerate(parts, 1):
    d = f"clips/top_sample_part{k}"
    os.makedirs(d, exist_ok=True)
    for n in part:
        os.replace(f"{OUT}/{n}.mp4", f"{d}/{n}.mp4")
    open(f"{d}/review.html", "w").write(page(part, f"Is it a rally? Part {k} of {len(parts)} (clips {part[0]} to {part[-1]})"))
    z = f"clips/top_sample_part{k}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
        for f in sorted(os.listdir(d)): zf.write(f"{d}/{f}", arcname=f"top_sample_part{k}/{f}")
    print(f"part {k}: {len(part)} clips ({part[0]}-{part[-1]}), {os.path.getsize(z)/1048576:.1f} MB -> {z}")
