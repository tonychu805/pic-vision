"""Can hand keypoints be seen on our camera? RTMPose whole-body vs MediaPipe Hands (2026-10-17, PIC-226).
Pre-registered: this file (sample rule, both methods, the operator's question and the bar) was committed before any
hand model was run on venue footage and before the operator saw any output.

Operator's idea: infer the paddle from the hand (wrist, knuckles, fingertips), since the paddle is held in the hand
and the body is easy to detect. Our pose model (yolov8x-pose) has wrists but no hand points. My expectation, stated so
it can be proven wrong: far-side hands are ~8-10 px and too small; near-side hands are big enough but often cut off.

SAMPLE: Test L clips (cache/guardrail_fresh/key.json) the operator judged real, not camera de3d1953 (ADR-155):
  12 clips; seed 20261017 picks 10; frames at 1/3 and 2/3 of each clip's detected span -> 20 frames.
PLAYERS: yolov8x-pose person boxes (imgsz 1280, conf >= 0.25) whose feet (box bottom-centre, calibration homography)
  are inside x -2..22 ft, y -6..50 ft (as swing_count_probe.py). Side: near if court y < 22 ft, else far.
METHODS (both on the same boxes):
  RTM  rtmlib RTMPose whole-body (rtmw-x, 384x288, COCO-WholeBody 133 points), top-down on the yolov8 box; 21 points
       per hand, drawn when score >= 0.3
  MP   MediaPipe Hand Landmarker (tasks API, default float16 model) on the player crop (box padded 25%, upscaled so
       the long side is 512 px); up to 2 hands, 21 points each
REVIEW: one zoomed crop per player, the two methods side by side, shuffled, labels hidden behind A/B per crop
  (which side is RTM is randomised and kept in the key). The operator answers per crop, for each panel:
    on   = points sit on a hand, in roughly the hand's shape
    off  = points drawn but not on a hand (or on the wrong hand-sized blob)
    none = no hand points drawn
    hid  = the hands are not visible in the picture (cut off, behind the body), so no answer is possible
BAR, per method and per side, over crops not marked "hid":
  usable on that side  =  "on" >= 70%  (and reported: off, none)
  Fewer than 8 judged crops on a side = underpowered for that side.
REPORTED: hand keypoint score (RTM) by side; person box height by side; MP detections by side.
Run: .venv/bin/python scripts/hand_keypoint_probe.py --boxes                         (frames + yolov8 boxes)
     /mnt/fast_scratch/handpose_env/bin/python scripts/hand_keypoint_probe.py --hands (both hand models, crops, page)
     .venv/bin/python scripts/hand_keypoint_probe.py --score                         (needs D/verdicts.txt)
Internal review of third-party venue footage; do not share.
"""
import json, os, random, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np

SEED, N_CLIPS, TAPO = 20261017, 10, "de3d1953"
D = "cache/hand_probe"
COURT_X, COURT_Y = (-2.0, 22.0), (-6.0, 50.0)
RTM_THR, MP_LONG, PAD = 0.3, 512, 0.25


def clips():
    key = json.load(open("cache/guardrail_fresh/key.json"))
    verd = {r["clip"]: r["verdict"] for r in map(json.loads, open("eval/labels/guardrail_fresh_verdicts.jsonl"))}
    pool = [r for r in key if verd[r["clip"]] == "real" and not r["session"].startswith(TAPO)]
    return random.Random(SEED).sample(sorted(pool, key=lambda r: r["clip"]), N_CLIPS), len(pool)


def boxes():
    import cv2
    from ultralytics import YOLO
    model = YOLO("yolov8x-pose.pt"); picks, n = clips(); print(f"pool {n}, picked {len(picks)}")
    os.makedirs(f"{D}/frames", exist_ok=True); out = []
    for r in picks:
        meta = json.load(open(f"cache/scale/{r['session']}.meta.json")); calib = json.load(open(meta["calib"]))
        H = np.array(calib["homography"], dtype=np.float32)
        for k, frac in (("a", 1 / 3), ("b", 2 / 3)):
            t = r["start"] + frac * (r["end"] - r["start"]); fid = f"{r['clip']}{k}"
            cap = cv2.VideoCapture(r["video"]); cap.set(cv2.CAP_PROP_POS_MSEC, 1000 * t); ok, im = cap.read(); cap.release()
            if not ok: raise RuntimeError(f"decode {fid}")
            h, w = im.shape[:2]; cw, ch = calib.get("calibration_resolution", [w, h]); sx, sy = cw / w, ch / h
            cv2.imwrite(f"{D}/frames/{fid}.png", im)
            res = model.predict(im, imgsz=1280, conf=0.25, classes=[0], verbose=False)[0]
            players = []
            for b in (res.boxes.xyxy.cpu().numpy() if res.boxes is not None else []):
                pt = np.array([[[(b[0] + b[2]) / 2 * sx, b[3] * sy]]], dtype=np.float32)
                cx, cy = (float(v) for v in cv2.perspectiveTransform(pt, H)[0, 0])
                if COURT_X[0] <= cx <= COURT_X[1] and COURT_Y[0] <= cy <= COURT_Y[1]:
                    players.append({"box": [float(v) for v in b], "court": [cx, cy], "side": "near" if cy < 22 else "far"})
            out.append({"frame": fid, "clip": r["clip"], "t": t, "players": players})
            print(fid, len(players), "players")
    json.dump(out, open(f"{D}/boxes.json", "w"), indent=1)


def hands():
    import cv2, mediapipe as mp, urllib.request
    from rtmlib import RTMPose
    rtm = RTMPose("https://download.openmmlab.com/mmpose/v1/projects/rtmw/onnx_sdk/"
                  "rtmw-dw-x-l_simcc-cocktail14_270e-384x288_20231122.zip", model_input_size=(288, 384), backend="onnxruntime", device="cpu")
    task = f"{D}/hand_landmarker.task"
    if not os.path.exists(task):
        urllib.request.urlretrieve("https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task", task)
    from mediapipe.tasks.python import BaseOptions, vision
    lm = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(base_options=BaseOptions(model_asset_path=task), num_hands=2))
    rng = random.Random(SEED + 1); crops, key = [], {}
    os.makedirs(f"{D}/crops", exist_ok=True)
    for fr in json.load(open(f"{D}/boxes.json")):
        im = cv2.imread(f"{D}/frames/{fr['frame']}.png"); H_, W_ = im.shape[:2]
        for i, p in enumerate(fr["players"]):
            x0, y0, x1, y1 = p["box"]; bw, bh = x1 - x0, y1 - y0
            X0, Y0 = int(max(0, x0 - PAD * bw)), int(max(0, y0 - PAD * bh)); X1, Y1 = int(min(W_, x1 + PAD * bw)), int(min(H_, y1 + PAD * bh))
            crop = im[Y0:Y1, X0:X1]; s = MP_LONG / max(crop.shape[:2]); big = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
            kp, sc = rtm(im, bboxes=[p["box"]]); kp, sc = kp[0], sc[0]
            rpan = big.copy(); rs = []
            for j in range(91, 133):
                rs.append(float(sc[j]))
                if sc[j] >= RTM_THR:
                    cv2.circle(rpan, (int((kp[j][0] - X0) * s), int((kp[j][1] - Y0) * s)), 3, (0, 255, 255), -1)
            mpan = big.copy()
            det = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(big, cv2.COLOR_BGR2RGB)))
            for hand in det.hand_landmarks:
                for q in hand:
                    cv2.circle(mpan, (int(q.x * big.shape[1]), int(q.y * big.shape[0])), 3, (255, 0, 255), -1)
            cid = f"{fr['frame']}_{i}"; rtm_left = rng.random() < 0.5
            L, R = (rpan, mpan) if rtm_left else (mpan, rpan)
            pane = np.hstack([L, np.full((L.shape[0], 8, 3), 255, np.uint8), R])
            for txt, x in (("A", 8), ("B", L.shape[1] + 16)):
                cv2.putText(pane, txt, (x, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
            cv2.imwrite(f"{D}/crops/{cid}.jpg", pane)
            key[cid] = {"A": "RTM" if rtm_left else "MP", "side": p["side"], "box_h": bh, "rtm_hand_score": float(np.mean(rs)),
                        "rtm_points": int(sum(v >= RTM_THR for v in rs)), "mp_hands": len(det.hand_landmarks)}
            crops.append(cid)
    rng.shuffle(crops)
    json.dump({"order": crops, "key": key}, open(f"{D}/key.json", "w"), indent=1)
    rows = "\n".join(f'<div class="c"><h3>{n + 1}. {c}</h3><img src="crops/{c}.jpg"></div>' for n, c in enumerate(crops))
    open(f"{D}/index.html", "w").write(f"""<title>Hand points</title><style>body{{font:15px system-ui;margin:16px;background:#111;color:#eee}}
.c{{margin:0 0 28px}} img{{max-width:100%;border:1px solid #444}} h3{{margin:4px 0}}</style>
<h2>Hand points: for each crop, panel A and panel B</h2><p>on = dots sit on a hand, roughly hand-shaped &nbsp; off = dots not on a hand
&nbsp; none = no dots &nbsp; hid = hands not visible. Reply like: <code>401a_0 A=on B=none</code></p>{rows}""")
    print(len(crops), "crops ->", f"{D}/index.html")


def score():
    import collections, re
    k = json.load(open(f"{D}/key.json"))["key"]
    t = collections.defaultdict(collections.Counter)
    for line in open(f"{D}/verdicts.txt"):
        m = re.match(r"\s*(\S+)\s+A=(\w+)\s+B=(\w+)", line)
        if not m: continue
        c, a, b = m.groups(); info = k[c]
        for panel, v in (("A", a), ("B", b)):
            meth = info["A"] if panel == "A" else ("MP" if info["A"] == "RTM" else "RTM")
            t[(meth, info["side"])][v] += 1
    for (meth, side), cnt in sorted(t.items()):
        judged = sum(cnt[v] for v in ("on", "off", "none")); on = cnt["on"] / judged if judged else 0
        verdict = "UNDERPOWERED" if judged < 8 else ("usable" if on >= 0.7 else "not usable")
        print(f"{meth:3s} {side:4s} judged {judged:2d}  on {cnt['on']:2d} off {cnt['off']:2d} none {cnt['none']:2d} hid {cnt['hid']:2d}  -> {on:.0%} {verdict}")
    for side in ("near", "far"):
        v = [x for x in k.values() if x["side"] == side]
        if v: print(f"{side}: n {len(v)}, box height median {np.median([x['box_h'] for x in v]):.0f} px, RTM hand score median "
                    f"{np.median([x['rtm_hand_score'] for x in v]):.2f}, MP found a hand in {sum(x['mp_hands'] > 0 for x in v)}")


if __name__ == "__main__":
    {"--boxes": boxes, "--hands": hands, "--score": score}[sys.argv[1]]()
