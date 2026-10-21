"""Offline end-to-end replay of the Phase-1 highlight path on a real session — NO production touched.

Chain (clip-first):  detect() -> score_segments (rank) -> serve gate (pose) -> Marathon/Firefight badges.
Kitchen War is deferred (Phase 2), so this is the cheap ball+gate path only.

Reads a cached session (footage + predictions on disk). Serve-gate pose runs either LOCALLY (default, validates
the chain on this workstation's GPU) or against the NEW RunPod endpoint (--endpoint, measures the real GPU hop).
Writes ONE JSON to --out (default ./phase1_out/) — no reel row, no share link, no notification, nothing written
back to R2 or the DB. Fully isolated from production.

Run from the repo root:
  local:        .venv/bin/python scripts/phase1_test/replay_phase1.py --session a96cbae3
  via endpoint: export RUNPOD_API_KEY=...
                .venv/bin/python scripts/phase1_test/replay_phase1.py --session a96cbae3 --endpoint <id> --video-url <url>
"""
import os, sys, json, time, glob, argparse, urllib.request
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
import validate_absolute_ranking as base
import eval_bounce_recovery as E
from src.select import net_width_px, score_segments
from src.bounce_eval import project

FPS, NET, SERVE_PRE, SERVE_WIN, SERVE_MIN = 30.0, 22.0, 30, 90, 18.0

ap = argparse.ArgumentParser()
ap.add_argument("--session", required=True); ap.add_argument("--n", type=int, default=15)
ap.add_argument("--imgsz", type=int, default=960); ap.add_argument("--endpoint"); ap.add_argument("--video-url")
ap.add_argument("--out", default="phase1_out")
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
cal = glob.glob(f"cache/pgc_fieldtest/{a.session}*.calib.json")[0]
csvp = glob.glob(f"cache/pgc_fieldtest/{a.session}*.csv")[0]
vid = glob.glob(f"cache/pgc_fieldtest/{a.session}*.mp4")[0]
calib = json.load(open(cal)); Hm = np.array(calib["homography"], float)

T = {}
t = time.perf_counter(); segs, cr, sp = base.detect(csvp, calib); T["clip_s"] = time.perf_counter() - t
t = time.perf_counter(); top = score_segments(segs, cr, sp, net_width_px(calib))[:a.n]; T["rank_s"] = time.perf_counter() - t
windows = [[int(s["start"] * FPS) - SERVE_PRE, int(s["start"] * FPS) + SERVE_WIN] for s in top]

t = time.perf_counter()
if a.endpoint:
    body = json.dumps({"input": {"homography": calib["homography"], "windows": windows,
                                 "imgsz": a.imgsz, "net": NET, "video_url": a.video_url}}).encode()
    req = urllib.request.Request(f"https://api.runpod.ai/v2/{a.endpoint}/runsync", body,
                                 {"Authorization": f"Bearer {os.environ['RUNPOD_API_KEY']}", "Content-Type": "application/json"})
    o = json.load(urllib.request.urlopen(req, timeout=600)); o = o.get("output", o)
    depths = [r["depth"] for r in o["results"]]
else:
    import cv2
    from ultralytics import YOLO
    model = YOLO("yolov8x-pose.pt")
    model.predict(np.zeros((720, 1280, 3), np.uint8), imgsz=a.imgsz, classes=[0], device=0, verbose=False)
    cap = cv2.VideoCapture(vid); depths = []
    for lo, hi in windows:
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, lo)); best = 0.0
        for _ in range(max(0, lo), hi + 1):
            ok, im = cap.read()
            if not ok: break
            r = model.predict(im, imgsz=a.imgsz, classes=[0], device=0, verbose=False)[0]
            for b in r.boxes.xyxy.cpu().numpy():
                cx, cy = project(Hm, (b[0] + b[2]) / 2, b[3])
                if -2 <= cx <= 22 and -6 <= cy <= 50:
                    best = max(best, abs(cy - NET))
        depths.append(round(float(best), 2))
    cap.release()
T["serve_gate_s"] = time.perf_counter() - t

_, _, tracked, _ = E.clip_points({"calib": cal, "csv": csvp})
cyb = {f: project(Hm, x, y)[1] for f, (x, y) in tracked.items()}
def ball_badges(s):
    fs = [f for f in range(int(s["start"] * FPS), int(s["end"] * FPS) + 1) if f in cyb]
    cross = [f for f0, f in zip(fs, fs[1:]) if f - f0 <= 6 and (cyb[f0] - NET) * (cyb[f] - NET) < 0]
    span = (cross[-1] - cross[0]) / FPS if len(cross) >= 2 else 0.0
    return span, len(cross)
surv = []
for s, d in zip(top, depths):
    if d >= SERVE_MIN:
        span, nx = ball_badges(s)
        surv.append(dict(start=round(s["start"], 1), end=round(s["end"], 1), serve_depth=d,
                         marathon=round(span, 1), firefight=nx))
for key in ("marathon", "firefight"):
    v = np.array([x[key] for x in surv], float); m, sd = (v.mean(), v.std() or 1) if len(v) else (0, 1)
    for x in surv: x["z_" + key] = round((x[key] - m) / sd, 2)
for x in surv:
    x["badge"] = "Marathon" if x["z_marathon"] >= x["z_firefight"] else "Firefight"

T["total_s"] = sum(T.values())
res = {"session": a.session, "mode": "endpoint" if a.endpoint else "local", "imgsz": a.imgsz,
       "n_segments": len(segs), "n_candidates": len(top), "n_warmup_dropped": len(top) - len(surv),
       "n_badged": len(surv), "timing_s": {k: round(v, 2) for k, v in T.items()}, "survivors": surv}
outp = os.path.join(a.out, f"{a.session}.json"); json.dump(res, open(outp, "w"), indent=2)
print(json.dumps({k: res[k] for k in ("session", "mode", "n_segments", "n_candidates",
                                       "n_warmup_dropped", "n_badged", "timing_s")}, indent=2))
from collections import Counter
print("badges:", dict(Counter(x["badge"] for x in surv)), "->", outp, "(scratch only; nothing delivered)")
