"""Review set: the labelled rallies the base k14 arm misses (PIC-228).

The union arm showed rally-level recall does not follow ball visibility: of 18 missed
rallies, 12 have fewer than 6 net crossings inside them and 6 have a segment that
overlaps with IoU < 0.5. This cuts all 18 (public tournament footage, 720p, silent,
shuffled, numbered 501..) with the pipeline's own view drawn on: the net row the
crossing counter uses (thin line), the tracked ball (green dot and trail), and a
running count of net crossings. Key (with the reason category) in cache/missed_review_key.csv.
Internal review.
"""
import csv, json, os, random, shutil, subprocess, sys, zipfile
sys.path.insert(0, ".")
import cv2
import numpy as np
from eval.harness import match_intervals, load_labels, iou
from src.ball import crossing_times, cluster_crossings, net_line_y
from src.calib import court_wedge
from src.track import track_ball
from src.tracknet import load_predictions

WIN, OUT = 600.0, "clips/missed_review"
JOB = os.environ.get("CLAUDE_JOB_DIR", "/home/tonychu/.claude/jobs/b3136fb4") + "/tmp"
EXC = [("pb_draft_cup", "videos/pb_draft_cup_30fps.mp4", "cache/pb_draft_cup_predictions_k14.csv", "calib/pb_draft_cup_30fps_calib.json", "eval/labels/pb_draft_cup_30fps.jsonl"),
       ("brickwall-SEMI", "videos/brickwall_semi_30fps.mp4", "cache/brickwall_semi_predictions_k14.csv", "calib/brickwall_semi_calib.json", "eval/labels/brickwall-SEMI.jsonl")]


def main():
    items = []
    for name, vid, kp, cp, lp in EXC:
        calib = json.load(open(cp)); w = court_wedge(calib)
        labels = [r for r in load_labels(lp) if r["end"] <= WIN]
        tr = load_predictions(kp, 30.0); n = int(WIN * 30)
        frames = [[(x, y, c if c is not None else 1.0)] if (x is not None and w(x, y)) else [] for _, x, y, _w, _h, c in tr[:n]]
        ys, xs = track_ball(frames, max_jump=150, reset_after=15, return_x=True)
        cr = crossing_times(list(zip([i / 30.0 for i in range(n)], ys)), net_y=net_line_y(calib), band=0.0)
        segs = [s for s in cluster_crossings(cr, gap_sec=3.0, min_crossings=6) if s["end"] <= WIN]
        preds = [{"start": s["start"], "end": s["end"]} for s in segs]
        m = match_intervals(preds, labels)
        for gi in m["missed"]:
            lab = labels[gi]
            ncr = sum(lab["start"] <= t <= lab["end"] for t in cr)
            best = max((iou(lab, p) for p in preds), default=0.0)
            cat = "overlaps_low_iou" if best >= 0.1 else ("few_crossings" if ncr < 6 else "enough_no_segment")
            items.append(dict(name=name, vid=vid, lab=lab, cat=cat, ncr=ncr, ys=ys, xs=xs, cr=cr, ny=net_line_y(calib)))
    random.Random(20261013).shuffle(items)
    shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
    rows = []
    for i, it in enumerate(items, 1):
        clip = f"{500 + i}"
        s0 = max(0.0, it["lab"]["start"] - 1.0); s1 = it["lab"]["end"] + 1.0
        f0, f1 = int(s0 * 30), int(s1 * 30)
        cap = cv2.VideoCapture(it["vid"]); cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
        raw = f"{JOB}/{clip}_raw.mp4"; vw = None
        crs = [int(t * 30) for t in it["cr"]]
        for f in range(f0, f1 + 1):
            ok, img = cap.read()
            if not ok: break
            h, wd = img.shape[:2]
            cv2.line(img, (0, int(it["ny"])), (wd, int(it["ny"])), (200, 200, 200), 1, cv2.LINE_AA)
            trail = [(it["xs"][g], it["ys"][g]) for g in range(max(f0, f - 15), f + 1) if g < len(it["ys"]) and it["ys"][g] is not None]
            for k, (x, y) in enumerate(trail):
                cv2.circle(img, (int(x), int(y)), 3 if k < len(trail) - 1 else 7, (60, 220, 60), -1, cv2.LINE_AA)
            so_far = sum(1 for c in crs if f0 <= c <= f)
            if any(0 <= f - c <= 6 for c in crs if f0 <= c):
                cv2.circle(img, (60, 130), 28, (0, 0, 255), 4, cv2.LINE_AA)
            cv2.putText(img, f"{clip}   net crossings so far: {so_far}", (24, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 3, cv2.LINE_AA)
            if vw is None:
                vw = cv2.VideoWriter(raw, cv2.VideoWriter_fourcc(*"mp4v"), 30, (wd, h))
            vw.write(img)
        vw.release(); cap.release()
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-an", "-vf", "scale=-2:720", "-c:v", "libx264", "-crf", "30",
                        "-preset", "veryfast", "-pix_fmt", "yuv420p", f"{OUT}/{clip}.mp4"], check=True)
        os.remove(raw)
        rows.append([clip, it["name"], f"{it['lab']['start']:.2f}", f"{it['lab']['end']:.2f}", it["cat"], it["ncr"]])
        print("done", clip, it["cat"], flush=True)
    with open("cache/missed_review_key.csv", "w", newline="") as fh:
        wtr = csv.writer(fh); wtr.writerow(["clip", "excerpt", "start", "end", "category", "net_crossings_inside"]); wtr.writerows(rows)

    names = [r[0] for r in rows]
    def radio(group, opts):
        return "".join(f'<label><input type="radio" name="{group}" value="{v}"> {t}</label>' for v, t in opts)
    cards = "\n".join(f'''<section class="card"><h2>{n}</h2><video src="{n}.mp4" controls loop muted playsinline preload="metadata"></video>
<div class="opts" data-q="{n}_what">What is it?{radio(n + "_what", [("dink", "slow dinks near the net"), ("normal", "normal rally"), ("fast", "fast hitting exchange"), ("serve_return", "serve + return only"), ("not", "not a real rally"), ("unsure", "can't tell")])}</div>
<div class="opts" data-q="{n}_dot">Does the green dot follow the ball?{radio(n + "_dot", [("yes", "yes"), ("partly", "partly"), ("no", "no")])}</div>
<input class="why" data-clip="{n}" placeholder="what do you notice? (ball hidden, dot on something else, rally cut off...)"></section>''' for n in names)
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Missed rallies review</title><style>body{{font:16px/1.4 system-ui,sans-serif;margin:0;background:#111;color:#eee}}header{{padding:16px;max-width:900px;margin:auto}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px;padding:0 16px 16px;max-width:1500px;margin:auto}}
.card{{background:#1c1c1e;border-radius:10px;padding:12px}}h2{{margin:0 0 8px}}video{{width:100%;border-radius:6px;background:#000}}
.opts{{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px;font-size:15px;align-items:center}}.why{{width:100%;box-sizing:border-box;margin-top:8px;background:#111;color:#eee;border:1px solid #333;border-radius:6px;padding:6px}}
footer{{position:sticky;bottom:0;background:#000;padding:12px 16px;border-top:1px solid #333}}button{{font:inherit;padding:8px 14px;border-radius:6px;border:0;background:#2f6feb;color:#fff;cursor:pointer}}
textarea{{width:100%;box-sizing:border-box;margin-top:8px;background:#111;color:#eee;border:1px solid #333;border-radius:6px;padding:8px}}</style></head><body>
<header><h1>Rallies the detector missed</h1><p>These are hand-labelled rallies that our current pipeline did not find. On each clip: the thin grey line is the net row the counter uses, the green dot is the ball position the tracker accepted, and the red ring flashes when a net crossing is counted. Judge from playback: what kind of rally is it, and does the green dot follow the ball? Internal review of public tournament footage.</p></header>
<div class="grid">{cards}</div>
<footer><span id="count">0 answered</span> <button id="copy">Copy my answers</button><textarea id="out" rows="3" readonly placeholder="Paste this to Claude."></textarea></footer>
<script>const out=document.getElementById('out'),count=document.getElementById('count');
function update(){{const p=[];let n=0;document.querySelectorAll('.opts').forEach(g=>{{const c=g.querySelector('input:checked');if(c){{n++;p.push(g.dataset.q+'='+c.value)}}}});
document.querySelectorAll('.why').forEach(w=>{{if(w.value.trim())p.push(w.dataset.clip+'_note=('+w.value.trim()+')')}});
count.textContent=n+' answered';out.value=p.join(', ')}}
document.addEventListener('change',update);document.addEventListener('input',update);document.getElementById('copy').onclick=()=>{{out.select();document.execCommand('copy')}};</script></body></html>'''
    open(f"{OUT}/review.html", "w").write(html)
    z = "clips/missed_review.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
        for f in sorted(os.listdir(OUT)):
            zf.write(f"{OUT}/{f}", arcname=f"missed_review/{f}")
    print(f"{z}: {os.path.getsize(z) / 1048576:.1f} MB")


if __name__ == "__main__":
    main()
