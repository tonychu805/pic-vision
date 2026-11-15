"""Blind review page for rally clips ("is it a rally?"), shared by the review-sample scripts."""


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
