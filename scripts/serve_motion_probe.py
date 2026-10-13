"""Does a serve motion appear before real rally starts, and not in no-serve / practice clips? (PIC-226)

Operator, 2026-10-13: use the serve's mechanical sequence (still at the baseline,
paddle drawn back, forward strike below the waist) as an anchor. Not a rally
detector: failed serves have a perfect serve motion and are NOT negatives here.

Sets (verdicts are the operator's, playback):
  fresh 30 clips (cache/fresh_sample_key.csv, window around the detected start):
    positives = real 15 + serve-and-return-only 3
    negatives = 311 (no serve action), 314 (ball tossed in), 319 (practice)
    not in the bar, reported: the 7 failed serves with a cause (301 302 306 308
    316 324 328) and 320, 322 (serve only, cut off)
  earlier judged clips (scripts/summarise_top_sample.v, PGC sessions in
    cache/pgc_fieldtest, window around the clip start):
    positives = real + very short; negatives = 'not' whose reason says machine /
    warm-up / feeding / practice / drill; other 'not' not used.

Window: detected start - 4.0 s to + 0.5 s (the serve precedes the first crossing),
pose at 30 fps, yolov8x-pose, imgsz 1280, person class, conf >= 0.25.

Serve motion, fixed BEFORE running (nothing tuned on results):
 1. Players: feet (box bottom-centre, calibration homography) inside x -2..22 ft,
    y -6..50 ft; association by nearest court position <= 4 ft, gaps <= 5 frames.
 2. Valid frame: wrist, both shoulders and both hips at keypoint confidence >= 0.5.
    Wrist speed = change of (wrist - mid-shoulder) / torso length between frames x
    30, torso length = mid-shoulder to mid-hip in pixels.
 3. Set phase: >= 15 consecutive valid frames (0.5 s) with BOTH wrists' speed
    < 1.5 torso lengths/s, feet moving < 1.5 ft over the run, and the player's
    court y <= 4 ft or >= 40 ft (at a baseline).
 4. Strike: within 45 frames (1.5 s) after the set phase ends, one wrist at
    >= 4.0 torso lengths/s for >= 3 consecutive valid frames, and at the frame of
    peak speed that wrist's image y is >= mid-hip image y - 0.1 torso lengths
    (at or below the hip line).
 5. Serve motion present = any player satisfies 3 and 4 inside the window.

BAR, fixed before running (fresh + earlier sets pooled):
 - serve motion found in >= 70% of positives, AND
 - serve motion found in <= 25% of negatives.
 Also reported, not gated: by set, by side (near/far), and the rate in the 9 fresh
 fault/cut-off clips. A pass is a lead; a hand check of ~8 detections follows.
Run: .venv/bin/python scripts/serve_motion_probe.py
"""
import contextlib, csv, glob, io, json, os, shutil, subprocess, sys, collections
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import cv2
import numpy as np
import swing_count_probe as SW
from swing_count_probe import tracks_from, FPS, KP, SHO, HIP, WR

JOB = os.environ.get("CLAUDE_JOB_DIR", "/home/tonychu/.claude/jobs/b3136fb4") + "/tmp"
PRE, POST = 4.0, 0.5
STILL_FR, STILL_SPEED, STILL_FT, BASE_NEAR, BASE_FAR = 15, 1.5, 1.5, 4.0, 40.0
STRIKE_FR, STRIKE_SPEED, STRIKE_RUN, HIP_TOL = 45, 4.0, 3, 0.1
NEG_FRESH = {"311", "314", "319"}
FAULT_FRESH = {"301", "302", "306", "308", "316", "324", "328", "320", "322"}
PRACTICE_WORDS = ("machine", "warm", "feeding", "feed", "practice", "drill")


def extract(cid, video, H, scale, s0):
    cache = f"cache/pose_serve/{cid}.json"
    if os.path.exists(cache):
        return json.load(open(cache))["frames"]
    d = f"{JOB}/sm_{cid}"
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, s0):.3f}", "-i", video, "-t", f"{PRE + POST:.1f}",
                    "-an", "-vf", "fps=30", f"{d}/%04d.png"], check=True)
    frames = []
    for f in sorted(glob.glob(f"{d}/*.png")):
        img = cv2.imread(f)
        res = MODEL.predict(img, imgsz=1280, conf=0.25, classes=[0], verbose=False)[0]
        ps = []
        if res.boxes is not None and len(res.boxes):
            for b, k, c in zip(res.boxes.xyxy.cpu().numpy(), res.keypoints.xy.cpu().numpy(), res.keypoints.conf.cpu().numpy()):
                pt = np.array([[[(b[0] + b[2]) / 2.0 * scale[0], b[3] * scale[1]]]], dtype=np.float32)
                cx_, cy_ = cv2.perspectiveTransform(pt, H)[0, 0]
                ps.append({"court": [float(cx_), float(cy_)], "kp": [[float(x), float(y), float(cc)] for (x, y), cc in zip(k, c)]})
        frames.append(ps)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs("cache/pose_serve", exist_ok=True)
    json.dump({"clip": cid, "frames": frames}, open(cache, "w"))
    return frames


def rel_speeds(track):
    """per frame index -> dict(wrist -> speed), plus hip-line test data."""
    info = {}
    prev = {}
    for fi, court, kp in track:
        for w in WR:
            if not all(kp[j][2] >= KP for j in (w,) + SHO + HIP):
                prev.pop(w, None); continue
            ms = ((kp[SHO[0]][0] + kp[SHO[1]][0]) / 2.0, (kp[SHO[0]][1] + kp[SHO[1]][1]) / 2.0)
            mh = ((kp[HIP[0]][0] + kp[HIP[1]][0]) / 2.0, (kp[HIP[0]][1] + kp[HIP[1]][1]) / 2.0)
            torso = float(np.hypot(ms[0] - mh[0], ms[1] - mh[1]))
            if torso < 5.0:
                prev.pop(w, None); continue
            rel = np.array([(kp[w][0] - ms[0]) / torso, (kp[w][1] - ms[1]) / torso])
            sp = None
            if w in prev and fi - prev[w][0] == 1:
                sp = float(np.hypot(*(rel - prev[w][1]))) * FPS
            prev[w] = (fi, rel)
            info.setdefault(fi, {})[w] = {"speed": sp, "below_hip": (kp[w][1] - mh[1]) / torso >= -HIP_TOL, "court": court}
    return info


def serve_motion(track):
    info = rel_speeds(track)
    frames = sorted(info)
    # set phases: runs of consecutive frames with both wrists valid and slow, feet still, at a baseline
    runs, cur = [], []
    for fi in frames:
        d = info[fi]
        ok = len(d) == 2 and all(v["speed"] is not None and v["speed"] < STILL_SPEED for v in d.values())
        y = next(iter(d.values()))["court"][1] if d else 50.0
        at_base = y <= BASE_NEAR or y >= BASE_FAR
        if ok and at_base and (not cur or fi - cur[-1] == 1):
            cur.append(fi)
        else:
            if len(cur) >= STILL_FR: runs.append(cur)
            cur = [fi] if (ok and at_base) else []
    if len(cur) >= STILL_FR: runs.append(cur)
    for run in runs:
        c0 = info[run[0]][WR[0]]["court"]; c1 = info[run[-1]][WR[0]]["court"]
        if np.hypot(c1[0] - c0[0], c1[1] - c0[1]) > STILL_FT:
            continue
        end = run[-1]
        for w in WR:
            streak, best = 0, None
            for fi in range(end + 1, end + STRIKE_FR + 1):
                v = info.get(fi, {}).get(w)
                if v and v["speed"] is not None and v["speed"] >= STRIKE_SPEED:
                    streak += 1
                    if best is None or v["speed"] > best[1]:
                        best = (fi, v["speed"], v["below_hip"])
                    if streak >= STRIKE_RUN and best[2]:
                        return True, ("near" if c0[1] < 22.0 else "far"), run[0] / FPS
                else:
                    streak, best = 0, None
    return False, None, None


def main():
    global MODEL
    from ultralytics import YOLO
    MODEL = YOLO("yolov8x-pose.pt")
    items = []   # (id, set, group, video, H, scale, s0)
    V = SW.V
    for r in csv.DictReader(open("cache/fresh_sample_key.csv")):
        c = r["clip"]
        if c in NEG_FRESH: g = "negative"
        elif V[c] in ("real", "short"): g = "positive"
        elif c in FAULT_FRESH: g = "fault"
        else: continue
        m = json.load(open(f"cache/fresh/{r['segment']}.meta.json"))
        H = np.array(json.load(open(m["calib"]))["homography"], dtype=np.float32)
        items.append((f"f{c}", "fresh", g, m["path"], H, (1.0, 1.0), float(r["start"]) - PRE))
    with contextlib.redirect_stdout(io.StringIO()):
        import summarise_top_sample as S
    for i, ((sid, a, b), (verdict, why)) in enumerate(sorted(S.v.items(), key=lambda kv: (kv[0][0], kv[0][1]))):
        why = (why or "").lower()
        if verdict in ("real", "short"): g = "positive"
        elif verdict == "not" and any(k in why for k in PRACTICE_WORDS): g = "negative"
        else: continue
        calib = json.load(open(f"cache/pgc_fieldtest/{sid}.calib.json"))
        video = f"cache/pgc_fieldtest/{sid}.mp4"
        cap = cv2.VideoCapture(video); vw, vh = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT); cap.release()
        cw, ch = calib.get("calibration_resolution", [vw, vh])
        H = np.array(calib["homography"], dtype=np.float32)
        items.append((f"o{i:03d}", "earlier", g, video, H, (cw / vw, ch / vh), float(a) - PRE))
    print(f"clips: {collections.Counter((s, g) for _, s, g, *_ in items)}", flush=True)
    res = []
    for cid, st, g, video, H, scale, s0 in items:
        frames = extract(cid, video, H, scale, s0)
        found, side, t = False, None, None
        for tr in tracks_from(frames):
            if len(tr) < 20: continue
            f_, s_, t_ = serve_motion(tr)
            if f_:
                found, side, t = True, s_, t_; break
        res.append((cid, st, g, found, side))
        print(f"{cid} {st:7s} {g:8s} serve_motion={'YES ' + str(side) if found else 'no'}", flush=True)
    json.dump(res, open("cache/serve_motion_results.json", "w"))
    print("\n=== serve motion found")
    for st in ("fresh", "earlier", "ALL"):
        for g in ("positive", "negative", "fault"):
            sel = [x for x in res if (st == "ALL" or x[1] == st) and x[2] == g]
            if sel: print(f"{st:8s} {g:9s} {sum(x[3] for x in sel):3d} / {len(sel):3d} = {sum(x[3] for x in sel) / len(sel):4.0%}")
    pos = [x for x in res if x[2] == "positive"]; neg = [x for x in res if x[2] == "negative"]
    pr = sum(x[3] for x in pos) / len(pos); nr = sum(x[3] for x in neg) / len(neg)
    print("\nby side (positives where found):", dict(collections.Counter(x[4] for x in pos if x[3])))
    print(f"\nfound in positives {pr:.0%} (bar >= 70%); found in negatives {nr:.0%} (bar <= 25%)")
    print(f"BAR: {'PASS' if pr >= 0.7 and nr <= 0.25 else 'FAIL'}")


if __name__ == "__main__":
    main()
