"""How usable are body points on the venue clips, near side and far side? (PIC-226)

Operator, 2026-10-13: start using player position and pose around the serve.
The pose model (yolov8x-pose, on disk) was only ever used for boxes on this
footage. Before building a "did the receiver swing after the serve" check, measure
what it gives us. Descriptive measurement, no pass/fail bar on rallies.

Set: the 30 judged fresh clips (cache/fresh_sample_key.csv), window = detected
rally start - 3.0 s to + 2.0 s, 10 fps, imgsz 1280, person class, conf >= 0.25.
Anonymous: boxes and 17 body points per person, no identity, no faces, no
tracking across clips. Output cache/pose/<clip>.json (local, not committed).

Positions: each person's feet (bottom-centre of the box) are placed on the court
with the calibration homography (image -> court feet); on-court = within 6 ft of
the 20 x 44 ft court; near side = court y < 22, far side = y >= 22.

Measured per side: persons found per frame; share of frames with >= 2 persons on
that side; per person, how many of the 17 body points have confidence >= 0.5;
share of persons with BOTH wrists >= 0.5 (what a swing check would need), and
with both shoulders and both hips.

Decision rule, fixed before running: a swing-from-pose check is worth building for
a side only if, on that side, >= 60% of person detections have both wrists >= 0.5
AND >= 2 persons are found on that side in >= 70% of frames. If the far side fails
and the near side passes, the check can only judge serves received on the near
side (about half), and that is reported as such.
Run: .venv/bin/python scripts/pose_coverage_probe.py
"""
import csv, glob, json, os, shutil, statistics as st, subprocess, sys
sys.path.insert(0, ".")
import cv2
import numpy as np

JOB_TMP = os.environ.get("CLAUDE_JOB_DIR", "/home/tonychu/.claude/jobs/b3136fb4") + "/tmp"
PRE, POST, FPS_SAMPLE, IMGSZ, CONF, KP_CONF = 3.0, 2.0, 10, 1280, 0.25, 0.5
WRISTS, SHOULDERS, HIPS = (9, 10), (5, 6), (11, 12)


def main():
    from ultralytics import YOLO
    model = YOLO("yolov8x-pose.pt")
    rows = list(csv.DictReader(open("cache/fresh_sample_key.csv")))
    os.makedirs("cache/pose", exist_ok=True)
    per_side = {"near": [], "far": []}      # one entry per person detection
    frames_ok = {"near": [], "far": []}     # per frame: persons on that side
    clip_summ = []
    meta_cache = {}
    for r in rows:
        seg = r["segment"]
        if seg not in meta_cache:
            m = json.load(open(f"cache/fresh/{seg}.meta.json"))
            meta_cache[seg] = (m["path"], np.array(json.load(open(m["calib"]))["homography"], dtype=np.float32))
        video, H = meta_cache[seg]
        s0 = max(0.0, float(r["start"]) - PRE)
        d = f"{JOB_TMP}/pose_{r['clip']}"
        shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s0:.3f}", "-i", video, "-t", f"{PRE + POST:.1f}",
                        "-an", "-vf", f"fps={FPS_SAMPLE}", f"{d}/%04d.png"], check=True)
        files = sorted(glob.glob(f"{d}/*.png"))
        out_frames = []
        clip_near = clip_far = 0
        for fi, f in enumerate(files):
            img = cv2.imread(f)
            res = model.predict(img, imgsz=IMGSZ, conf=CONF, classes=[0], verbose=False)[0]
            persons = []
            if res.boxes is not None and len(res.boxes):
                boxes = res.boxes.xyxy.cpu().numpy()
                kxy = res.keypoints.xy.cpu().numpy()
                kcf = res.keypoints.conf.cpu().numpy() if res.keypoints.conf is not None else np.ones(kxy.shape[:2])
                for b, k, c in zip(boxes, kxy, kcf):
                    fx, fy = (b[0] + b[2]) / 2.0, b[3]
                    cx_, cy_ = cv2.perspectiveTransform(np.array([[[fx, fy]]], dtype=np.float32), H)[0, 0]
                    if not (-6 <= cx_ <= 26 and -6 <= cy_ <= 50):
                        continue
                    side = "near" if cy_ < 22.0 else "far"
                    good = c >= KP_CONF
                    persons.append({"side": side, "court": [round(float(cx_), 1), round(float(cy_), 1)],
                                    "kp_ok": int(good.sum()), "wrists": bool(good[list(WRISTS)].all()),
                                    "shoulders_hips": bool(good[list(SHOULDERS + HIPS)].all()),
                                    "box": [round(float(v)) for v in b],
                                    "kp": [[round(float(x)), round(float(y)), round(float(cc), 2)] for (x, y), cc in zip(k, c)]})
            n_near = sum(p["side"] == "near" for p in persons); n_far = sum(p["side"] == "far" for p in persons)
            frames_ok["near"].append(n_near); frames_ok["far"].append(n_far)
            for p in persons:
                per_side[p["side"]].append(p)
            out_frames.append({"i": fi, "t": s0 + fi / FPS_SAMPLE, "persons": persons})
        shutil.rmtree(d, ignore_errors=True)
        json.dump({"clip": r["clip"], "fps": FPS_SAMPLE, "frames": out_frames}, open(f"cache/pose/{r['clip']}.json", "w"))
        clip_summ.append((r["clip"], len(files)))
        print(f"clip {r['clip']}: {len(files)} frames", flush=True)

    print("\n=== body points by side (all 30 clips pooled; one row per person detection)")
    print(f"{'side':5s} {'persons':>8s} {'median kp>=0.5 of 17':>22s} {'both wrists':>12s} {'shoulders+hips':>15s} {'frames with >=2 persons':>25s}")
    verdict = {}
    for side in ("near", "far"):
        P = per_side[side]
        n = len(P)
        kp = st.median([p["kp_ok"] for p in P]) if P else 0
        w = sum(p["wrists"] for p in P) / n if n else 0.0
        sh = sum(p["shoulders_hips"] for p in P) / n if n else 0.0
        fr = sum(1 for c in frames_ok[side] if c >= 2) / len(frames_ok[side])
        print(f"{side:5s} {n:8d} {kp:22.0f} {w:12.0%} {sh:15.0%} {fr:25.0%}")
        verdict[side] = (w >= 0.60 and fr >= 0.70)
    print("\ndecision rule (>= 60% persons with both wrists AND >= 2 persons in >= 70% of frames):")
    for side in ("near", "far"):
        print(f"  {side}: {'usable' if verdict[side] else 'NOT usable'}")
    print("\nper clip: frames sampled:", ", ".join(f"{c}:{n}" for c, n in clip_summ))


if __name__ == "__main__":
    main()
