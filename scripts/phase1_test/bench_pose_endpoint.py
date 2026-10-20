"""Benchmark the standalone RunPod pose endpoint (Phase-1 serve gate) — cold start + warm throughput.

Runs LOCALLY (this workstation), calls the NEW pose endpoint over the RunPod API. Touches no production surface:
posts serve-window frame ranges, reads back depths + timing. Video is a session already in R2 (presigned URL)
or already on the pod (--video-path). Serve windows come from a real cached session's detect+rank (same
clip-first path as production), so this measures the actual Phase-1 gate work.

Reports:
  COLD — wall-clock of the first call after the worker was idle (queue + spin-up + model load + infer).
  WARM — median wall-clock of repeat calls (hot) + infer-only fps from the handler's timing.

Run from the repo root:
  export RUNPOD_API_KEY=...
  .venv/bin/python scripts/phase1_test/bench_pose_endpoint.py --endpoint <id> --session a96cbae3 --video-url <url>
"""
import os, sys, json, time, glob, argparse, urllib.request
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import validate_absolute_ranking as base
from src.select import net_width_px, score_segments

FPS, NET, SERVE_PRE, SERVE_WIN = 30.0, 22.0, 30, 90

ap = argparse.ArgumentParser()
ap.add_argument("--endpoint", required=True)
ap.add_argument("--video-url"); ap.add_argument("--video-path")
ap.add_argument("--session", required=True, help="8-char sid of a cached pgc_fieldtest session (for calib+windows)")
ap.add_argument("--n", type=int, default=15); ap.add_argument("--imgsz", type=int, default=960)
ap.add_argument("--warm", type=int, default=3)
a = ap.parse_args()
KEY = os.environ["RUNPOD_API_KEY"]
URL = f"https://api.runpod.ai/v2/{a.endpoint}/runsync"

cal = glob.glob(f"cache/pgc_fieldtest/{a.session}*.calib.json")[0]
csvp = glob.glob(f"cache/pgc_fieldtest/{a.session}*.csv")[0]
calib = json.load(open(cal))
segs, cr, sp = base.detect(csvp, calib)
top = score_segments(segs, cr, sp, net_width_px(calib))[:a.n]
windows = [[int(s["start"] * FPS) - SERVE_PRE, int(s["start"] * FPS) + SERVE_WIN] for s in top]
payload = {"input": {"homography": calib["homography"], "windows": windows, "imgsz": a.imgsz, "net": NET}}
if a.video_url:
    payload["input"]["video_url"] = a.video_url
elif a.video_path:
    payload["input"]["video_path"] = a.video_path
else:
    sys.exit("need --video-url or --video-path")
print(f"session {a.session}: {len(top)} candidates, {sum(h-l for l,h in windows)} serve-window frames to pose")


def call():
    body = json.dumps(payload).encode()
    req = urllib.request.Request(URL, body, {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    t = time.time()
    r = json.load(urllib.request.urlopen(req, timeout=600))
    return time.time() - t, r.get("output", r)


print("\nCOLD call (first after idle)…")
w0, o0 = call(); tm = o0.get("timing", {})
print(f"  wall {w0:.1f}s | model_load {tm.get('model_load_s')}s download {tm.get('download_s')}s "
      f"decode {tm.get('decode_s')}s infer {tm.get('infer_s')}s | cold={o0.get('cold')} dev={o0.get('device')}")
walls = []
for i in range(a.warm):
    w, o = call(); walls.append(w); tm = o.get("timing", {})
    print(f"  warm {i+1}: wall {w:.1f}s infer {tm.get('infer_s')}s")
walls.sort(); warm = walls[len(walls)//2]
frames = sum(h - l for l, h in windows); infer = (o.get("timing", {}).get("infer_s") or 1)
print(f"\n=== endpoint {a.endpoint} | imgsz {a.imgsz} | {len(top)} candidates / {frames} frames ===")
print(f"  COLD wall (reel-ready from cold):        {w0:.1f}s")
print(f"  WARM wall (per-session serve gate, hot): {warm:.1f}s")
print(f"  infer-only throughput: {frames/infer:.1f} fps")
print("  => compare COLD/WARM wall to the reel turnaround target. Production is 1 endpoint cold-start per job.")
