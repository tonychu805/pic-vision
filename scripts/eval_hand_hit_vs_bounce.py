"""Is a hand close to the ball when it changes direction? Hand points as a bounce-vs-paddle-hit cue (2026-10-18, PIC-226).
Pre-registered: this file (events, feature, bar) was committed before any hand or wrist point was computed on these
events.

Context. RTMPose whole-body hand points land on the hand (hand keypoint probe, 31/33 near, 36/36 far, with caveats).
Operator asked whether we can detect paddle hits. A hit happens at the paddle, so a hand should be near the ball;
a bounce happens on the floor, away from hands (except a ball bouncing at a player's feet, which is far from the hand
in the image anyway on this camera).
EVENTS: the 36 operator-tagged finder candidates of chunk 1 (eda301d9 2026-09-25 08:21 s000; 23 bounce, 13 paddle_hit;
  not_ball excluded), same as eval_motion_hit_vs_bounce.py. Already known on these events: the speed-ratio result
  (AUC 0.12 in-sample). Not known: anything about hands. The 28 untagged events of CVAT project 5 stay held out.
POINTS: frames g-3..g+3 around the candidate frame g. Ball = tile-arm tracked point at that frame (the candidate point
  at g). Players = yolov8x-pose boxes on the court (feet inside x -2..22, y -6..50 ft). For each player:
  RTMPose whole-body (rtmw-dw-x-l) on the box, hand points 91-132 (all 42, no score cut: scores are not 0-1).
FEATURE (primary): hand_dist = min over those frames and players of (distance from the ball to the nearest hand
  point) / (that player's box height). Reported, not gated: wrist_dist, the same with yolov8x-pose wrists (9, 10),
  to show whether hand points add anything over the wrist we already have.
BAR (all three): coverage, hand_dist computable for >= 80% of the 36; separable, AUC(bounce > hit) >= 0.85;
  not chance, a label-shuffle test (10,000) of |AUC - 0.5| gives p < 0.01.
REPORTED: hits and bounces by hand_dist; how many of the 6 events the speed-ratio cut (0.95) gets wrong hand_dist
  gets right at the median split between classes (descriptive, in-sample).
One chunk, one camera, n = 23 vs 13, one operator: a pass is a lead for the held-out 28, not a result.
Run: .venv/bin/python scripts/eval_hand_hit_vs_bounce.py --boxes
     /mnt/fast_scratch/handpose_env/bin/python scripts/eval_hand_hit_vs_bounce.py --hands
     .venv/bin/python scripts/eval_hand_hit_vs_bounce.py --score
"""
import json, math, os, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np

D = "cache/hand_hit"
C = "cache/pgc_fieldtest/365c798c-6554-42b1-b0e6-b2825e73d264.calib.json"
TILE = "cache/bounce_pilot/chunk_eda301d9_0821.tile.csv"
VIDEO = "pgc-fieldtest-sept2026/eda301d9-b093-478a-aec1-51a8e7a5c08c/2026-09-25T08-21-01-111Z/session-000.mkv"
WIN = 3


def events():
    import eval_bounce_recovery as E, eval_motion_hit_vs_bounce as M
    _, _, T, cands = E.clip_points({"calib": C, "csv": TILE})
    out = []
    for f, lab in sorted(M.tags().items()):
        if lab not in ("bounce", "paddle_hit"): continue
        g = min(cands, key=lambda c: abs(c - f))
        if abs(g - f) > 3: continue
        ball = {str(k): list(T[k]) for k in range(g - WIN, g + WIN + 1) if k in T}
        ball[str(g)] = list(cands[g])
        sr = M.feats(T, g)
        out.append({"frame": g, "label": lab, "ball": ball, "speed_ratio": sr["speed_ratio"] if sr else None})
    return out


def boxes():
    import cv2
    from ultralytics import YOLO
    from src.bounce_eval import project
    H = json.load(open(C))["homography"]; model = YOLO("yolov8x-pose.pt"); ev = events()
    os.makedirs(D, exist_ok=True); cap = cv2.VideoCapture(VIDEO)
    for e in ev:
        e["players"] = {}
        for k in range(e["frame"] - WIN, e["frame"] + WIN + 1):
            cap.set(cv2.CAP_PROP_POS_FRAMES, k); ok, im = cap.read()
            if not ok: raise RuntimeError(f"decode {k}")
            r = model.predict(im, imgsz=1280, conf=0.25, classes=[0], verbose=False)[0]
            ps = []
            for b, kp in zip(r.boxes.xyxy.cpu().numpy(), r.keypoints.data.cpu().numpy()):
                cx, cy = project(H, (b[0] + b[2]) / 2, b[3])
                if -2 <= cx <= 22 and -6 <= cy <= 50:
                    ps.append({"box": [float(v) for v in b], "wrists": [[float(kp[i][0]), float(kp[i][1])] for i in (9, 10)]})
            e["players"][str(k)] = ps
        print(e["frame"], e["label"], sum(map(len, e["players"].values())), "player boxes")
    json.dump(ev, open(f"{D}/events.json", "w"))


def hands():
    import cv2
    from rtmlib import RTMPose
    rtm = RTMPose("https://download.openmmlab.com/mmpose/v1/projects/rtmw/onnx_sdk/"
                  "rtmw-dw-x-l_simcc-cocktail14_270e-384x288_20231122.zip", model_input_size=(288, 384), backend="onnxruntime", device="cpu")
    ev = json.load(open(f"{D}/events.json")); cap = cv2.VideoCapture(VIDEO)
    for e in ev:
        for k, ps in e["players"].items():
            if not ps: continue
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(k)); ok, im = cap.read()
            kp, _ = rtm(im, bboxes=[p["box"] for p in ps])
            for p, pts in zip(ps, kp):
                p["hands"] = [[float(x), float(y)] for x, y in pts[91:133]]
    json.dump(ev, open(f"{D}/events.json", "w")); print("hands done")


def dist(e, key):
    best = None
    for k, b in e["ball"].items():
        for p in e["players"].get(k, []):
            h = p["box"][3] - p["box"][1]
            d = min(math.hypot(b[0] - x, b[1] - y) for x, y in p[key]) / h
            best = d if best is None else min(best, d)
    return best


def auc(pos, neg):
    return sum((p > q) + 0.5 * (p == q) for p in pos for q in neg) / (len(pos) * len(neg))


def score():
    ev = json.load(open(f"{D}/events.json")); n = len(ev)
    for key, name in (("hands", "hand_dist (primary)"), ("wrists", "wrist_dist (reported)")):
        rows = [(dist(e, key), e) for e in ev]; rows = [(d, e) for d, e in rows if d is not None]
        b = [d for d, e in rows if e["label"] == "bounce"]; h = [d for d, e in rows if e["label"] == "paddle_hit"]
        a = auc(b, h)
        print(f"{name}: coverage {len(rows)}/{n}  bounce median {np.median(b):.2f}  hit median {np.median(h):.2f}  AUC(bounce>hit) {a:.2f}")
        print("   bounce:", " ".join(f"{d:.2f}" for d in sorted(b))); print("   hit:   ", " ".join(f"{d:.2f}" for d in sorted(h)))
        if key == "hands":
            labs = [e["label"] for _, e in rows]; ds = [d for d, _ in rows]; rng = np.random.default_rng(0); obs = abs(a - 0.5)
            perm = []
            for _ in range(10000):
                L = rng.permutation(labs)
                perm.append(abs(auc([d for d, l in zip(ds, L) if l == "bounce"], [d for d, l in zip(ds, L) if l == "paddle_hit"]) - 0.5))
            p = (1 + sum(s >= obs for s in perm)) / 10001
            cov, sep, chance = len(rows) / n >= 0.8, a >= 0.85, p < 0.01
            print(f"   shuffle p = {p:.4f}\n   coverage {'PASS' if cov else 'FAIL'}   separable {'PASS' if sep else 'FAIL'}   "
                  f"not chance {'PASS' if chance else 'FAIL'}   ->  {'PASS' if cov and sep and chance else 'FAIL'}")
            cut = (np.median(b) + np.median(h)) / 2
            wrong = [(d, e) for d, e in rows if e["speed_ratio"] is not None and (e["speed_ratio"] > 0.95) != (e["label"] == "paddle_hit")]
            fixed = sum((d < cut) == (e["label"] == "paddle_hit") for d, e in wrong)
            print(f"   speed-ratio cut 0.95 wrong on {len(wrong)}; hand_dist (cut {cut:.2f}) right on {fixed} of those (descriptive)")


if __name__ == "__main__":
    {"--boxes": boxes, "--hands": hands, "--score": score}[sys.argv[1]]()
