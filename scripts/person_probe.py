"""Person-detection feasibility probe on real venue footage (PIC-197).

Question: can an off-the-shelf person detector see the FAR-side players at our
real camera geometry? Bars agreed with the operator beforehand (PIC-197):
far-side players boxed on >= 80% of frames in >= 7 of 10 clips; false boxes in
<= 10% of frames. Judged on PLAYBACK by the operator; the numbers below are the
automatic proxy.

Side and on-court are decided from each person's FEET placed on the court via the
calibration homography (an earlier version used the net-tape line in the image, which
mis-sorts far players standing near the kitchen: the tape is ~3 ft above the floor).

Anonymous: person class only, boxes only, no identity, no faces, no tracking
across clips. Local weights, no downloads. Overlays are for internal review of
third-party venue footage; do not share.

Run: .venv/bin/python scripts/person_probe.py
"""
import csv, glob, json, os, statistics, subprocess, sys, zipfile
import cv2
sys.path.insert(0, ".")
import numpy as np
from ultralytics import YOLO

CLIPS = ["01", "02", "04", "20", "31", "03", "21", "24", "37", "09"]
WEIGHTS = "yolov8x-pose.pt"          # on disk; person class only is used
IMGSZ, CONF, STEP = 1280, 0.25, 6    # 5 fps sampling on 30 fps video
OUT = "clips/person_probe"
DIR = "cache/pgc_fieldtest"
os.makedirs(OUT, exist_ok=True)

key = {r["clip"]: r for r in csv.DictReader(open("cache/precision_sample_key.csv"))}
model = YOLO(WEIGHTS)
summary = []
for clip in CLIPS:
    r = key[clip]
    sid = [p.split("/")[-1][:-4] for p in glob.glob(f"{DIR}/*.csv") if p.split("/")[-1].startswith(r["session"])][0]
    calib = json.load(open(f"{DIR}/{sid}.calib.json"))
    HM = np.array(calib["homography"], dtype=np.float32)   # image -> court feet (0.17 ft RMSE)
    NET = float(calib["net_y_ft"])                         # 22 ft; near baseline y=0, far baseline y=44
    def to_court(fx, fy):
        q = cv2.perspectiveTransform(np.array([[[fx, fy]]], dtype=np.float32), HM)[0, 0]
        return float(q[0]), float(q[1])
    def on_court(cx, cy):                                   # players may stand behind the baselines
        return -4.0 <= cx <= 24.0 and -8.0 <= cy <= 52.0
    s, e = float(r["start"]), float(r["end"])
    cap = cv2.VideoCapture(f"{DIR}/{sid}.mp4")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(s * fps))
    W, H = int(cap.get(3)), int(cap.get(4))
    tmp = f"{OUT}/_{clip}.mp4"
    vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    held, n_sampled = [], 0
    far_frames = near_frames = off_frames = 0
    counts = []
    i = 0
    nframes = int((e - s) * fps)
    while i < nframes:
        ok, frame = cap.read()
        if not ok:
            break
        if i % STEP == 0:
            res = model.predict(frame, imgsz=IMGSZ, conf=CONF, classes=[0], verbose=False)[0]
            held = []
            far = near = off = 0
            for b in res.boxes.xyxy.cpu().numpy():
                x1, y1, x2, y2 = [float(v) for v in b[:4]]
                fx, fy = (x1 + x2) / 2, y2                  # foot point
                cx, cy = to_court(fx, fy)
                on = on_court(cx, cy)
                side = "far" if cy > NET else "near"        # by the FLOOR position, not the net tape
                held.append((x1, y1, x2, y2, on, side))
                if on:
                    far += side == "far"; near += side == "near"
                else:
                    off += 1
            n_sampled += 1
            far_frames += far > 0; near_frames += near > 0; off_frames += off > 0
            counts.append(far + near)
        for x1, y1, x2, y2, on, side in held:
            col = (60, 220, 60) if on and side == "near" else (255, 160, 40) if on else (150, 150, 150)
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), col, 2)
        on_far = sum(1 for h in held if h[4] and h[5] == "far"); on_near = sum(1 for h in held if h[4] and h[5] == "near")
        cv2.putText(frame, f"far {on_far}   near {on_near}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3, cv2.LINE_AA)
        vw.write(frame)
        i += 1
    vw.release(); cap.release()
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", tmp, "-an", "-vf", "scale=-2:720", "-c:v", "libx264",
                    "-crf", "27", "-preset", "veryfast", "-pix_fmt", "yuv420p", f"{OUT}/{clip}.mp4"], check=True)
    os.remove(tmp)
    summary.append({"clip": clip, "kind": r["group"], "sampled": n_sampled,
                    "far_cov": far_frames / max(1, n_sampled), "near_cov": near_frames / max(1, n_sampled),
                    "off_court": off_frames / max(1, n_sampled), "median_on_court": statistics.median(counts) if counts else 0})
with open("cache/person_probe_summary.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(summary[0])); w.writeheader(); w.writerows(summary)
print(f"{'clip':5s} {'frames':>6s} {'far side boxed':>15s} {'near side boxed':>16s} {'median on court':>16s} {'frames w/ off-court person':>27s}")
for s_ in summary:
    print(f"{s_['clip']:5s} {s_['sampled']:6d} {s_['far_cov']:15.0%} {s_['near_cov']:16.0%} {s_['median_on_court']:16.0f} {s_['off_court']:27.0%}")
met = sum(1 for s_ in summary if s_["far_cov"] >= 0.80)
print(f"\nautomatic proxy for bar 1: far side has >= 1 box on >= 80% of frames in {met} of {len(summary)} clips (bar: 7)")
