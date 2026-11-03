"""Cut the review sample for the fresh-session pause-rule test (PIC-226).

The frozen rule (both gaps <= 6.0 s) flagged 0 of 68 detected rallies, so the
pre-registered check (>= 70% of flagged are not real play) has nothing to score.
This sample answers the follow-up that IS measurable: what is in the fresh
sessions that the rule did not flag?
  group "near": rallies with ONE gap <= 6.0 s (9 of them) -- exploratory, not part of the bar
  group "rand": 20 random of the rest, seed fixed
Silent, 720p, shuffled, numbered 301.. ; key in cache/ (not shown).
Internal review of third-party venue footage; do not share.
"""
import csv, json, os, random, subprocess, zipfile
SEED, PAD, ZIP_MB, OUT = 20261013, 1.0, 24, "clips/fresh_sample"
R = json.load(open("cache/fresh_rallies.json"))
near = [r for r in R if not r["flag"] and ((r["pre"] is not None and r["pre"] <= 6.0) or (r["post"] is not None and r["post"] <= 6.0))]
rest = [r for r in R if not r["flag"] and r not in near]
rng = random.Random(SEED)
picks = [dict(r, group="near") for r in near] + [dict(r, group="rand") for r in rng.sample(rest, min(20, len(rest)))]
rng.shuffle(picks)
print(f"near {len(near)}, random {len(picks) - len(near)}, total {len(picks)}")
os.makedirs(OUT, exist_ok=True)
rows = []
for i, r in enumerate(picks, 1):
    name = f"{300 + i}"
    ss = max(0.0, r["start"] - PAD)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ss:.3f}", "-i", r["video"],
                    "-t", f"{r['end'] - ss + PAD:.3f}", "-an", "-vf", "scale=-2:720", "-c:v", "libx264",
                    "-crf", "30", "-preset", "veryfast", "-pix_fmt", "yuv420p", f"{OUT}/{name}.mp4"], check=True)
    rows.append([name, r["group"], r["seg"], f"{r['start']:.2f}", f"{r['end']:.2f}", f"{r['end']-r['start']:.1f}",
                 "" if r["pre"] is None else f"{r['pre']:.1f}", "" if r["post"] is None else f"{r['post']:.1f}"])
with open("cache/fresh_sample_key.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["clip", "group", "segment", "start", "end", "duration", "gap_before", "gap_after"]); w.writerows(rows)

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
    d = f"clips/fresh_sample_part{k}"
    os.makedirs(d, exist_ok=True)
    for n in part:
        os.replace(f"{OUT}/{n}.mp4", f"{d}/{n}.mp4")
    open(f"{d}/review.html", "w").write(page(part, f"Is it a rally? Part {k} of {len(parts)} (clips {part[0]} to {part[-1]})"))
    z = f"clips/fresh_sample_part{k}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
        for f in sorted(os.listdir(d)): zf.write(f"{d}/{f}", arcname=f"fresh_sample_part{k}/{f}")
    print(f"part {k}: {len(part)} clips ({part[0]}-{part[-1]}), {os.path.getsize(z)/1048576:.1f} MB -> {z}")
