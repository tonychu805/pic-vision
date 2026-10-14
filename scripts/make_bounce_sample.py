"""Choose the rallies to hand-label for the bounce pilot (2026-10-14). Writes
eval/labels/bounces/sample.json. Reproducible: seed 0, fixed pools.

  pgc     the judged PGC field clips whose verdict is a real rally or serve-and-return
          (cache/fresh_sample_key.csv; verdicts as in eval_rally_formation.py): bounces exist.
          Failed serves are left out.
  public  10 hand-labelled quality-1/2 rallies from each of brickwall_30fps and
          pb_draft_cup_30fps: the easy-case ceiling, reported separately.
Run: .venv/bin/python scripts/make_bounce_sample.py
"""
import csv, json, sys
sys.path.insert(0, ".")
from src.bounce_eval import pick_sample

V = dict(x.split("=") for x in "301=not 302=not 303=real 304=short 305=short 306=not 307=real 308=not 309=real 310=real 311=not 312=short 313=real 314=not 315=real 316=not 317=real 318=real 319=not 320=not 321=real 322=not 323=real 324=not 325=real 326=real 327=real 328=not 329=real 330=real".split())
PUBLIC = [("brickwall_30fps", "cache/brickwall_30fps_predictions_k14.csv", "calib/brickwall_30fps_calib.json",
           "eval/labels/brickwall_30fps.jsonl", "videos/brickwall_30fps.mp4"),
          ("pb_draft_cup", "cache/pb_draft_cup_predictions_k14.csv", "calib/pb_draft_cup_30fps_calib.json",
           "eval/labels/pb_draft_cup_30fps.jsonl", "videos/pb_draft_cup_30fps.mp4")]

clips = []
for f in csv.DictReader(open("cache/fresh_sample_key.csv")):
    if V[f["clip"]] not in ("real", "short"):
        continue
    meta = json.load(open(f"cache/fresh/{f['segment']}.meta.json"))
    clips.append({"id": f"pgc-{f['clip']}", "set": "pgc", "video": meta["path"], "calib": meta["calib"],
                  "csv": f"cache/fresh/{f['segment']}.csv", "start": float(f["start"]), "end": float(f["end"])})
for name, csvp, calib, labp, video in PUBLIC:
    rallies = [json.loads(l) for l in open(labp) if l.strip()]
    rallies = [r for r in rallies if r.get("quality") in (1, 2) and r["end"] - r["start"] <= 25]
    for r in pick_sample(rallies, 10, seed=0):
        clips.append({"id": f"{name}-{r['rally_id']}", "set": "public", "video": video, "calib": calib,
                      "csv": csvp, "start": r["start"], "end": r["end"]})
json.dump({"seed": 0, "clips": clips}, open("eval/labels/bounces/sample.json", "w"), indent=1)
print(len(clips), "clips:", sum(c["set"] == "pgc" for c in clips), "pgc,", sum(c["set"] == "public" for c in clips), "public")
