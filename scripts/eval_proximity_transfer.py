"""Does "a player's wrist is next to the ball" tell a paddle hit from a bounce on new events? (2026-10-18, PIC-226)
Pre-registered: this file (rule, cut-off, events, bar) was committed before any tag exists in CVAT project 5, and the
predictions are computed and their hash committed before the operator tags.

RULE, fixed from chunk 1 (eval_hand_hit_vs_bounce.py, 23 bounces / 13 hits): wrist_dist = min over frames g-3..g+3
  and on-court players of (ball to nearest yolov8x-pose wrist) / box height. HIT if wrist_dist < 0.25, else BOUNCE.
  0.25 = midway between chunk 1's class medians (bounce 0.35, hit 0.15). The wrist is primary because it matched the
  hand points on chunk 1 (AUC 0.97 vs 0.95) without a second model; hand_dist (RTMPose, cut 0.22) is reported only.
EVENTS: the 28 tile-arm candidates of the 18 PGC pilot clips (CVAT project 5 'pilot-candidate-review'), the same events
  as the speed-ratio transfer test (eval_motion_transfer.py, ce54d9a). Primary set: the 25 not from camera de3d1953
  (ADR-155); all 28 reported. Operator tags: bounce / paddle_hit / not_ball / unsure; only bounce and hit are scored.
BAR (primary set, bounce/hit-tagged events), mirroring the speed transfer test:
  coverage   wrist_dist computable (a ball point and an on-court player in the window) for >= 70%
  accuracy   >= 75% of computable events classified correctly at 0.25
  hits       if >= 6 hits: >= 60% of hits have wrist_dist < 0.25 (else inconclusive on hits)
  direction  AUC(bounce > hit) >= 0.75
REPORTED: hand_dist the same way; the speed-ratio rule on the same events and how often the two cues agree; per camera.
Run: .venv/bin/python scripts/eval_proximity_transfer.py --predict   (before tagging; prints the predictions' sha256)
     /mnt/fast_scratch/handpose_env/bin/python scripts/eval_proximity_transfer.py --hands
     .venv/bin/python scripts/eval_proximity_transfer.py --score
"""
import hashlib, json, math, os, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np

D = "cache/proximity_transfer"; P = f"{D}/predictions.json"
CUT_WRIST, CUT_HAND, WIN = 0.25, 0.22, 3
TAPO = "de3d1953"


def predict():
    import cv2
    from ultralytics import YOLO
    import eval_bounce_recovery as E
    import eval_motion_hit_vs_bounce as M
    from src.bounce_eval import project
    meta = json.load(open("cache/bounce_pilot/pilot_candidate_review.json"))
    sample = {c["id"]: c for c in json.load(open("eval/labels/bounces/sample.json"))["clips"]}
    model = YOLO("yolov8x-pose.pt"); tracks = {}; out = []
    for o in meta:
        c = sample[o["clip"]]; H = json.load(open(c["calib"]))["homography"]
        if o["clip"] not in tracks:
            tracks[o["clip"]] = E.clip_points({"calib": c["calib"], "csv": f"cache/bounce_pilot/{o['clip']}.tile.csv"})[2]
        T = tracks[o["clip"]]; g = o["clip_frame"]; shift = o["src_frame"] - g
        ball = {k: list(T[k]) for k in range(g - WIN, g + WIN + 1) if k in T}
        ball[g] = [o["x"], o["y"]]
        cap = cv2.VideoCapture(o["video"]); players = {}
        for k in ball:
            cap.set(cv2.CAP_PROP_POS_FRAMES, k + shift); ok, im = cap.read()
            if not ok: raise RuntimeError(f"decode p-{o['n']} frame {k + shift}")
            h, w = im.shape[:2]; cw, ch = o["calib_res"]
            r = model.predict(im, imgsz=1280, conf=0.25, classes=[0], verbose=False)[0]; ps = []
            for b, kp in zip(r.boxes.xyxy.cpu().numpy(), r.keypoints.data.cpu().numpy()):
                cx, cy = project(H, (b[0] + b[2]) / 2 * cw / w, b[3] * ch / h)
                if -2 <= cx <= 22 and -6 <= cy <= 50:
                    ps.append({"box": [float(v) for v in b], "wrists": [[float(kp[i][0]), float(kp[i][1])] for i in (9, 10)]})
            players[k] = ps
        cap.release()
        sr = M.feats(T, g)
        rec = {"n": o["n"], "clip": o["clip"], "tapo": TAPO in o["video"], "video": o["video"], "shift": shift,
               "ball": {str(k): v for k, v in ball.items()}, "players": {str(k): v for k, v in players.items()},
               "speed_ratio": sr["speed_ratio"] if sr else None}
        rec["wrist_dist"] = dist(rec, "wrists"); rec["call"] = None if rec["wrist_dist"] is None else ("hit" if rec["wrist_dist"] < CUT_WRIST else "bounce")
        out.append(rec); print(f"p-{o['n']:02d} {o['clip']} wrist_dist {rec['wrist_dist']} -> {rec['call']}")
    os.makedirs(D, exist_ok=True); json.dump(out, open(P, "w"), sort_keys=True)
    print("predictions sha256", hashlib.sha256(open(P, "rb").read()).hexdigest())


def hands():
    import cv2
    from rtmlib import RTMPose
    rtm = RTMPose("https://download.openmmlab.com/mmpose/v1/projects/rtmw/onnx_sdk/"
                  "rtmw-dw-x-l_simcc-cocktail14_270e-384x288_20231122.zip", model_input_size=(288, 384), backend="onnxruntime", device="cpu")
    ev = json.load(open(P))
    for e in ev:
        cap = cv2.VideoCapture(e["video"])
        for k, ps in e["players"].items():
            if not ps: continue
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(k) + e["shift"]); ok, im = cap.read()
            kp, _ = rtm(im, bboxes=[p["box"] for p in ps])
            for p, pts in zip(ps, kp): p["hands"] = [[float(x), float(y)] for x, y in pts[91:133]]
        cap.release()
    json.dump(ev, open(f"{D}/with_hands.json", "w"), sort_keys=True); print("hands done")


def dist(e, key):
    best = None
    for k, b in e["ball"].items():
        for p in e["players"].get(k, []):
            if key not in p: continue
            d = min(math.hypot(b[0] - x, b[1] - y) for x, y in p[key]) / (p["box"][3] - p["box"][1])
            best = d if best is None else min(best, d)
    return best


def auc(pos, neg):
    return sum((p > q) + 0.5 * (p == q) for p in pos for q in neg) / max(1, len(pos) * len(neg))


def score():
    import eval_motion_transfer as T
    tg = T.tags(); src = f"{D}/with_hands.json" if os.path.exists(f"{D}/with_hands.json") else P
    ev = json.load(open(src))
    print(f"tagged {len(tg)} of {len(ev)}: " + ", ".join(f"{k} {list(tg.values()).count(k)}" for k in ("bounce", "paddle_hit", "not_ball", "unsure")))
    for name, sel in (("PRIMARY (no Tapo)", lambda e: not e["tapo"]), ("all 28", lambda e: True)):
        rows = [(e, tg[e["n"]]) for e in ev if sel(e) and tg.get(e["n"]) in ("bounce", "paddle_hit")]
        print(f"\n{name}: bounce/hit events {len(rows)}")
        for key, cut in (("wrists", CUT_WRIST), ("hands", CUT_HAND)):
            ok = [(dist(e, key), lab) for e, lab in rows]; ok = [(d, l) for d, l in ok if d is not None]
            b = [d for d, l in ok if l == "bounce"]; h = [d for d, l in ok if l == "paddle_hit"]
            if not ok: print(f"  {key}: not computable"); continue
            acc = (sum(d >= cut for d in b) + sum(d < cut for d in h)) / len(ok); a = auc(b, h)
            cov = len(ok) / max(1, len(rows)); hr = sum(d < cut for d in h) / len(h) if h else None
            print(f"  {key:6s} cut {cut}: coverage {len(ok)}/{len(rows)} ({cov:.0%})  accuracy {acc:.0%}  "
                  f"hits caught {sum(d < cut for d in h)}/{len(h)}  bounces kept {sum(d >= cut for d in b)}/{len(b)}  AUC(bounce>hit) {a:.2f}")
            if key == "wrists" and name.startswith("PRIMARY"):
                checks = {"coverage": cov >= 0.70, "accuracy": acc >= 0.75, "direction": a >= 0.75}
                hits_ok = None if len(h) < 6 else hr >= 0.60
                print("  BAR: " + "  ".join(f"{k} {'PASS' if v else 'FAIL'}" for k, v in checks.items()) +
                      f"  hits {'inconclusive (<6)' if hits_ok is None else ('PASS' if hits_ok else 'FAIL')}"
                      f"  ->  {'PASS' if all(checks.values()) and hits_ok is not False else 'FAIL'}"
                      + ("" if hits_ok is not None else " (hits inconclusive)"))
        both = [(e, l) for e, l in rows if e["speed_ratio"] is not None and e["call"] is not None]
        sp = sum((e["speed_ratio"] >= 0.95) == (l == "paddle_hit") for e, l in both)
        agree = [(e, l) for e, l in both if (e["speed_ratio"] >= 0.95) == (e["call"] == "hit")]
        print(f"  speed ratio (0.95) right on {sp}/{len(both)}; cues agree on {len(agree)}, of which right "
              f"{sum((e['call'] == 'hit') == (l == 'paddle_hit') for e, l in agree)}")


if __name__ == "__main__":
    {"--predict": predict, "--hands": hands, "--score": score}[sys.argv[1]]()
