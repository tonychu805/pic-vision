"""Blind playback check of the rally-level 'one tiny spot' flag (PIC-226).

Flag: >= 30% of a detected rally's tracked points fall in ONE 12x12 px square
(threshold chosen after seeing clip O at 48%, so it is UNVALIDATED: this check
exists to test it). Cuts every flagged field rally (O excluded: already known),
mixed with unflagged controls of similar length from the same sessions,
shuffled, silent, 720p. Key goes to cache/ and is not printed. The operator
answers 'real rally / not a rally / can't tell' per clip. Internal review of
third-party venue footage: do not share.
"""
import collections, csv, glob, json, os, random, subprocess, sys
sys.path.insert(0, ".")
from src.ball import net_line_y, crossing_times, cluster_crossings
from src.calib import court_wedge
from src.track import track_ball
from src.tracknet import load_predictions

THR, SQ, MIN_PTS, PAD, SEED, N_CTRL = 0.30, 12, 8, 1.0, 20261012, 3
DIR, OUT = "cache/pgc_fieldtest", "clips/flag_check"
O_START = None

def rallies(sid):
    calib = json.load(open(f"{DIR}/{sid}.calib.json"))
    track = load_predictions(f"{DIR}/{sid}.csv", 30.0)
    wedge = court_wedge(calib)
    times = [t for t, *_ in track]
    frames = [[(x, y, c if c is not None else 1.0)] if wedge(x, y) else [] for _, x, y, w, h, c in track]
    ys, xs = track_ball(frames, max_jump=150, reset_after=15, return_x=True)
    cr = crossing_times(list(zip(times, ys)), net_y=net_line_y(calib), band=0.0)
    out = []
    for s in cluster_crossings(cr, gap_sec=3.0, min_crossings=6):
        pts = [(round(xs[i] / SQ), round(ys[i] / SQ)) for i, t in enumerate(times)
               if ys[i] is not None and s["start"] <= t <= s["end"]]
        if len(pts) < MIN_PTS:
            continue
        share = collections.Counter(pts).most_common(1)[0][1] / len(pts)
        out.append({"sid": sid, "start": s["start"], "end": s["end"], "dur": s["end"] - s["start"], "share": share})
    return out

key_o = [r for r in csv.DictReader(open("cache/blind_check_key.csv")) if r["clip"] == "O"][0]
allr = []
for p in sorted(glob.glob(f"{DIR}/*.csv")):
    sid = os.path.basename(p)[:-4]
    allr += rallies(sid)
flagged = [r for r in allr if r["share"] >= THR
           and not (r["sid"].startswith(key_o["video"].split(":")[-1]) and abs(r["start"] - float(key_o["start"])) < 1.0)]
sessions = {r["sid"] for r in flagged}
lo, hi = min(r["dur"] for r in flagged), max(r["dur"] for r in flagged)
pool = [r for r in allr if r["share"] < 0.15 and r["sid"] in sessions and lo * 0.7 <= r["dur"] <= hi * 1.3]
rng = random.Random(SEED)
controls = rng.sample(pool, min(N_CTRL, len(pool)))
picks = [("flag", r) for r in flagged] + [("control", r) for r in controls]
rng.shuffle(picks)

os.makedirs(OUT, exist_ok=True)
start_letter = 18                       # S, after A..R
rows = []
for i, (grp, r) in enumerate(picks):
    letter = chr(ord("A") + start_letter + i)
    ss = max(0.0, r["start"] - PAD)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ss:.3f}", "-i", f"{DIR}/{r['sid']}.mp4",
                    "-t", f"{r['end'] - ss + PAD:.3f}", "-an", "-vf", "scale=-2:720", "-c:v", "libx264",
                    "-crf", "26", "-preset", "veryfast", "-pix_fmt", "yuv420p", f"{OUT}/{letter}.mp4"], check=True)
    rows.append([letter, r["sid"][:8], grp, f"{r['start']:.2f}", f"{r['end']:.2f}", f"{r['dur']:.1f}", f"{r['share']:.2f}"])
with open("cache/flag_check_key.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["clip", "session", "group", "start", "end", "duration", "top_square_share"]); w.writerows(rows)

letters = [r[0] for r in rows]
cards = "\n".join(f'''<section class="card"><h2>{L}</h2><video src="{L}.mp4" controls loop muted playsinline preload="metadata"></video>
<div class="opts" data-clip="{L}"><label><input type="radio" name="{L}" value="real rally"> real rally</label>
<label><input type="radio" name="{L}" value="not a rally"> not a rally</label>
<label><input type="radio" name="{L}" value="can't tell"> can't tell</label></div></section>''' for L in letters)
html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Real rally?</title><style>body{{font:16px/1.4 system-ui,sans-serif;margin:0;background:#111;color:#eee}}
header{{padding:16px;max-width:900px;margin:auto}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:16px;padding:0 16px 16px;max-width:1500px;margin:auto}}
.card{{background:#1c1c1e;border-radius:10px;padding:12px}}h2{{margin:0 0 8px}}video{{width:100%;border-radius:6px;background:#000}}
.opts{{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px}}footer{{position:sticky;bottom:0;background:#000;padding:12px 16px;border-top:1px solid #333}}
button{{font:inherit;padding:8px 14px;border-radius:6px;border:0;background:#2f6feb;color:#fff;cursor:pointer}}
textarea{{width:100%;box-sizing:border-box;margin-top:8px;background:#111;color:#eee;border:1px solid #333;border-radius:6px;padding:8px}}</style></head><body>
<header><h1>Is this a real rally?</h1><p>Silent clips. A <b>real rally</b> is players actually hitting the ball back and forth after a serve.
<b>Not a rally</b> = a failed serve, someone tossing or bouncing a ball, picking balls up, warm-up noise, nothing real going on.
If you can see the ball being hit by players, it's real. Judge only what you see.</p></header>
<div class="grid">{cards}</div>
<footer><span id="count">0 / {len(letters)} answered</span> <button id="copy">Copy my answers</button>
<textarea id="out" rows="3" readonly placeholder="Paste this to Claude."></textarea></footer>
<script>const out=document.getElementById('out'),count=document.getElementById('count');
function update(){{const p=[];let n=0;document.querySelectorAll('.opts').forEach(g=>{{const c=g.querySelector('input:checked');if(c){{n++;p.push(g.dataset.clip+'='+c.value)}}}});
count.textContent=n+' / {len(letters)} answered';out.value=p.join(', ')}}
document.addEventListener('change',update);document.getElementById('copy').onclick=()=>{{out.select();document.execCommand('copy')}};</script></body></html>'''
open(f"{OUT}/review.html", "w").write(html)

import zipfile
z = "clips/flag_check_review.zip"
with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
    for f in sorted(os.listdir(OUT)):
        zf.write(f"{OUT}/{f}", arcname=f"flag_check/{f}")
d = lambda g: [float(r[5]) for r in rows if r[2] == g]
print(f"flagged rallies found (O excluded): {len(flagged)}; controls drawn: {len(controls)}; clips {letters[0]}..{letters[-1]}")
print(f"flag group length {min(d('flag')):.0f}-{max(d('flag')):.0f}s; control group length {min(d('control')):.0f}-{max(d('control')):.0f}s")
print(f"zip: {z} {os.path.getsize(z)/1048576:.1f} MB (key in cache/flag_check_key.csv, not shown)")
