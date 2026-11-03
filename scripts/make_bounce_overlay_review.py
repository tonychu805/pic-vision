"""Why does the finder miss bounces the tracker had? Overlay clips for operator review (2026-10-16).

Set: bounce chunk 2 labels that are 'visible' and NOT 'discarded' (check_discarded_ball_points.py definitions:
>= 3 non-static raw points near the bounce, >= 3 of them accepted by track_ball) and NOT found by the tile arm.
Clip: frames f-45..f+45 of the source, with the tile arm's tracked point drawn per frame (green; red when it sits
in a static glare cell), a short trail, and a white cross at the labelled bounce point. Operator tags each clip
glare_mixed | sparse | tracked_fine | unsure in CVAT project 'bounce-chunk2-overlay'.

Before the clips are shown, a mechanical call is written to cache/bounce_pilot/chunk2_overlay_pred.json (its
sha256 goes in the commit message), so the two can be compared afterwards:
  glare_mixed   >= 2 tracked points in static cells within +-8 frames
  sparse        else, < 2 tracked points within +-3 frames of the bounce
  tracked_fine  otherwise
Run: .venv/bin/python scripts/make_bounce_overlay_review.py   (then the CVAT upload runs at the end)
"""
import collections, csv, hashlib, json, os, sys, time
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import cv2
import numpy as np
import requests
from src.bounce_eval import recover
from src.calib import court_wedge
from src.tracknet import load_predictions
import eval_bounce_recovery as E
from eval_bounce_chunk2 import TILE, CALIB, LABELS, VIDEO
from check_discarded_ball_points import CELL, STATIC_N, WIN, RAD
from cvat_make_scale_review import BASE as CVAT, token, drop_token

OUT = "clips/bounce_overlay"
PRED = "cache/bounce_pilot/chunk2_overlay_pred.json"
HALF = 45


def select():
    labs = json.load(open(LABELS))["bounces"]
    w = court_wedge(json.load(open(CALIB)), margin_px=400.0)
    raw = {i: (x, y) for i, (_, x, y, *_r) in enumerate(load_predictions(TILE, 30.0)) if x is not None and w(x, y)}
    H, raw_all, tracked, cands = E.clip_points({"calib": CALIB, "csv": TILE})
    cell = lambda p: (int(p[0] // CELL), int(p[1] // CELL))
    cnt = collections.Counter(cell(p) for p in raw.values())
    static = {c for c, k in cnt.items() if k >= STATIC_N}
    chosen = []
    for b in labs:
        f = b["frame"]
        near = [g for g in range(f - WIN, f + WIN + 1) if g in raw and cell(raw[g]) not in static
                and np.hypot(raw[g][0] - b["x"], raw[g][1] - b["y"]) <= RAD]
        acc = [g for g in near if g in tracked and np.hypot(tracked[g][0] - raw[g][0], tracked[g][1] - raw[g][1]) < 1]
        found = recover({"frame": f, "x": b["x"], "y": b["y"], "visible": True}, raw_all, tracked, cands, H)["found"]
        if len(near) >= 3 and len(acc) >= 3 and not found:
            chosen.append(b)
    return chosen, tracked, static, cell


def predict(b, tracked, static, cell):
    f = b["frame"]
    st = sum(1 for g in range(f - WIN, f + WIN + 1) if g in tracked and cell(tracked[g]) in static)
    close = sum(1 for g in range(f - 3, f + 4) if g in tracked)
    return "glare_mixed" if st >= 2 else "sparse" if close < 2 else "tracked_fine"


def render(b, k, tracked, static, cell):
    f0 = b["frame"] - HALF
    cap = cv2.VideoCapture(VIDEO); cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, f0))
    path = f"{OUT}/b-{k:02d}.mp4"
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (1920, 1080))
    for g in range(max(0, f0), b["frame"] + HALF + 1):
        ok, im = cap.read()
        if not ok: break
        trail = [h for h in range(g - 6, g + 1) if h in tracked]
        for h in trail[:-1]:
            p = tuple(int(v) for v in tracked[h]); cv2.circle(im, p, 7, (0, 0, 255) if cell(tracked[h]) in static else (0, 200, 0), -1)
        if g in tracked:
            p = tuple(int(v) for v in tracked[g]); cv2.circle(im, p, 16, (0, 0, 255) if cell(tracked[g]) in static else (0, 255, 0), 5)
        x, y = int(b["x"]), int(b["y"]); c = (255, 255, 255)
        cv2.drawMarker(im, (x, y), c, cv2.MARKER_TILTED_CROSS, 48 if abs(g - b["frame"]) <= 1 else 28, 3)
        cv2.putText(im, f"{g - b['frame']:+d}", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3)
        vw.write(im)
    vw.release(); cap.release()
    return path


def upload(rows):
    h = {"Authorization": f"Token {token()}"}
    try:
        p = requests.post(f"{CVAT}/api/projects", headers=h, json={"name": "bounce-chunk2-overlay", "labels": [
            {"name": n, "type": "any", "attributes": []} for n in ("glare_mixed", "sparse", "tracked_fine", "unsure")]})
        p.raise_for_status(); pid = p.json()["id"]
        for r in rows:
            t = requests.post(f"{CVAT}/api/tasks", headers=h, json={"name": f"b-{r['k']:02d} frame {r['frame']}", "project_id": pid})
            t.raise_for_status(); tid = t.json()["id"]
            with open(r["file"], "rb") as fh:
                requests.post(f"{CVAT}/api/tasks/{tid}/data", headers=h, data={"image_quality": 85},
                              files={"client_files[0]": fh}).raise_for_status()
            for _ in range(120):
                if requests.get(f"{CVAT}/api/tasks/{tid}", headers=h).json().get("size", 0) > 0: break
                time.sleep(1)
        print("project", pid, "tasks", len(rows))
    finally:
        drop_token()


def main():
    os.makedirs(OUT, exist_ok=True)
    chosen, tracked, static, cell = select()
    rows, pred = [], {}
    for k, b in enumerate(chosen, 1):
        rows.append({"k": k, "frame": b["frame"], "file": render(b, k, tracked, static, cell)})
        pred[f"b-{k:02d}"] = predict(b, tracked, static, cell)
    json.dump(pred, open(PRED, "w"), indent=1)
    with open(f"{OUT}/KEY.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=["k", "frame", "file"]); wr.writeheader(); wr.writerows(rows)
    print("clips", len(rows), "prediction sha256", hashlib.sha256(open(PRED, "rb").read()).hexdigest())
    upload(rows)


if __name__ == "__main__":
    main()
