"""Count arm swings by side and test it against the judged clips (PIC-226).

Gate passed (operator playback, 2026-10-13, 7 clips): body points on the right
body parts, near and far, 7 of 7 each; swings clearly visible in 5 of 7
(all 4 real rallies; 1 of 3 faults).

Idea: a rally is at least 3 contacts (LABELING v5). Count the players' arm swings
instead of ball crossings. No ball and no serve motion needed.

Set: the 30 judged fresh clips (cache/fresh_sample_key.csv) as the operator saw
them: detected start - 1.0 s to end + 1.0 s, pose at 30 fps, imgsz 1280, person
class, conf >= 0.25. Anonymous: body points only, no identity, no faces.

Rules, fixed BEFORE running (nothing tuned on results):
 1. Players: persons whose feet (box bottom-centre, placed on the court by the
    calibration homography) are inside x -2..22 ft, y -6..50 ft. Spectators at
    the fence fall outside. Frame-to-frame association by nearest court position
    (<= 4 ft), gaps <= 5 frames.
 2. Swing signal, per player and wrist: wrist position relative to the
    mid-shoulder, divided by torso length (mid-shoulder to mid-hip, pixels), is
    differenced between frames and multiplied by 30 = speed in torso lengths
    per second. A frame counts only if that wrist, both shoulders and both hips
    have keypoint confidence >= 0.5.
 3. A swing = speed >= 4.0 torso lengths/s on >= 3 consecutive valid frames
    (0.1 s). Swings of players on the same side within 0.5 s merge into one.
 4. Side = near if the player's court y < 22 ft, else far.
 5. Call, from swings sorted by time: RALLY = >= 3 swings with >= 2 changes of
    side; EXCHANGE = >= 2 swings with >= 1 change (and not RALLY); ONE_SIDE = >= 1
    swing, all on one side; NONE = 0.

BAR, fixed before running:
 - RALLY is called on >= 60% of the 15 real clips, AND
 - RALLY is called on <= 20% of the 15 clips that are not a rally (12 not-a-rally
   + 3 serve-and-return-only).
 Descriptive, not gated: the full call table by verdict. 30 clips, one venue, one
 weekend: a pass is a lead, not a result.
Run: .venv/bin/python scripts/swing_count_probe.py
"""
import csv, glob, json, os, shutil, subprocess, sys, collections
sys.path.insert(0, ".")
import cv2
import numpy as np

JOB = os.environ.get("CLAUDE_JOB_DIR", "/home/tonychu/.claude/jobs/b3136fb4") + "/tmp"
V = dict(x.split("=") for x in "301=not 302=not 303=real 304=short 305=short 306=not 307=real 308=not 309=real 310=real 311=not 312=short 313=real 314=not 315=real 316=not 317=real 318=real 319=not 320=not 321=real 322=not 323=real 324=not 325=real 326=real 327=real 328=not 329=real 330=real".split())
FPS, KP, THRESH, MIN_RUN, MERGE_S, ASSOC_FT = 30.0, 0.5, 4.0, 3, 0.5, 4.0
SHO, HIP, WR = (5, 6), (11, 12), (9, 10)


def extract(model, r, H, video):
    cache = f"cache/pose30/{r['clip']}.json"
    if os.path.exists(cache):
        return json.load(open(cache))
    s0 = max(0.0, float(r["start"]) - 1.0)
    dur = float(r["end"]) - float(r["start"]) + 2.0
    d = f"{JOB}/sw_{r['clip']}"
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s0:.3f}", "-i", video, "-t", f"{dur:.2f}",
                    "-an", "-vf", "fps=30", f"{d}/%04d.png"], check=True)
    frames = []
    for f in sorted(glob.glob(f"{d}/*.png")):
        img = cv2.imread(f)
        res = model.predict(img, imgsz=1280, conf=0.25, classes=[0], verbose=False)[0]
        ps = []
        if res.boxes is not None and len(res.boxes):
            for b, k, c in zip(res.boxes.xyxy.cpu().numpy(), res.keypoints.xy.cpu().numpy(), res.keypoints.conf.cpu().numpy()):
                cx_, cy_ = cv2.perspectiveTransform(np.array([[[(b[0] + b[2]) / 2.0, b[3]]]], dtype=np.float32), H)[0, 0]
                ps.append({"court": [float(cx_), float(cy_)], "kp": [[float(x), float(y), float(cc)] for (x, y), cc in zip(k, c)]})
        frames.append(ps)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs("cache/pose30", exist_ok=True)
    json.dump({"clip": r["clip"], "frames": frames}, open(cache, "w"))
    return {"clip": r["clip"], "frames": frames}


def tracks_from(frames):
    tracks, live = [], []                     # track: list of (frame, court, kp)
    for fi, ps in enumerate(frames):
        ps = [p for p in ps if -2 <= p["court"][0] <= 22 and -6 <= p["court"][1] <= 50]
        used = set()
        for tr in live:
            best, bd = None, ASSOC_FT
            for j, p in enumerate(ps):
                if j in used:
                    continue
                d = np.hypot(p["court"][0] - tr[-1][1][0], p["court"][1] - tr[-1][1][1])
                if d <= bd:
                    best, bd = j, d
            if best is not None:
                used.add(best); tr.append((fi, ps[best]["court"], ps[best]["kp"]))
        for j, p in enumerate(ps):
            if j not in used:
                t = [(fi, p["court"], p["kp"])]; tracks.append(t); live.append(t)
        live = [tr for tr in live if fi - tr[-1][0] <= 5]
    return tracks


def swings_for(track):
    """Return [(frame, side)] for each swing of this player."""
    out = []
    for w in WR:
        prev, run, run_start, best_f = None, 0, None, None
        for fi, court, kp in track:
            ok = all(kp[j][2] >= KP for j in (w,) + SHO + HIP)
            if not ok:
                prev, run = None, 0
                continue
            ms = ((kp[SHO[0]][0] + kp[SHO[1]][0]) / 2.0, (kp[SHO[0]][1] + kp[SHO[1]][1]) / 2.0)
            mh = ((kp[HIP[0]][0] + kp[HIP[1]][0]) / 2.0, (kp[HIP[0]][1] + kp[HIP[1]][1]) / 2.0)
            torso = float(np.hypot(ms[0] - mh[0], ms[1] - mh[1]))
            if torso < 5.0:
                prev, run = None, 0
                continue
            rel = np.array([(kp[w][0] - ms[0]) / torso, (kp[w][1] - ms[1]) / torso])
            if prev is not None and fi - prev[0] == 1:
                sp = float(np.hypot(*(rel - prev[1]))) * FPS
                if sp >= THRESH:
                    run += 1
                    if run == MIN_RUN:
                        out.append((fi, "near" if court[1] < 22.0 else "far"))
                else:
                    run = 0
            else:
                run = 0
            prev = (fi, rel)
    return out


def call(events):
    events = sorted(events)
    merged = []
    for fi, side in events:
        if merged and merged[-1][1] == side and (fi - merged[-1][0]) / FPS <= MERGE_S:
            continue
        merged.append((fi, side))
    n = len(merged)
    ch = sum(1 for a, b in zip(merged, merged[1:]) if a[1] != b[1])
    if n >= 3 and ch >= 2:
        return "RALLY", merged
    if n >= 2 and ch >= 1:
        return "EXCHANGE", merged
    if n >= 1:
        return "ONE_SIDE", merged
    return "NONE", merged


def main():
    from ultralytics import YOLO
    model = YOLO("yolov8x-pose.pt")
    rows = list(csv.DictReader(open("cache/fresh_sample_key.csv")))
    res = []
    for r in rows:
        m = json.load(open(f"cache/fresh/{r['segment']}.meta.json"))
        H = np.array(json.load(open(m["calib"]))["homography"], dtype=np.float32)
        data = extract(model, r, H, m["path"])
        evs = []
        for tr in tracks_from(data["frames"]):
            if len(tr) >= 10:
                evs += swings_for(tr)
        c, merged = call(evs)
        res.append((r["clip"], V[r["clip"]], c, merged, len(data["frames"])))
        print(f"clip {r['clip']} {V[r['clip']]:5s} -> {c:9s} swings {[(round(f / FPS, 1), s) for f, s in merged]}", flush=True)
    print("\n=== calls by judged verdict")
    tab = collections.defaultdict(collections.Counter)
    for clip, v, c, _, _ in res:
        tab[v][c] += 1
    print(f"{'verdict':8s} {'n':>3s} {'RALLY':>6s} {'EXCHANGE':>9s} {'ONE_SIDE':>9s} {'NONE':>5s}")
    for v in ("real", "short", "not"):
        t = tab[v]; n = sum(t.values())
        print(f"{v:8s} {n:3d} {t['RALLY']:6d} {t['EXCHANGE']:9d} {t['ONE_SIDE']:9d} {t['NONE']:5d}")
    real = [x for x in res if x[1] == "real"]; non = [x for x in res if x[1] != "real"]
    r_hit = sum(x[2] == "RALLY" for x in real) / len(real)
    n_hit = sum(x[2] == "RALLY" for x in non) / len(non)
    print(f"\nRALLY called on real clips: {sum(x[2]=='RALLY' for x in real)}/{len(real)} = {r_hit:.0%} (bar >= 60%)")
    print(f"RALLY called on non-rally clips: {sum(x[2]=='RALLY' for x in non)}/{len(non)} = {n_hit:.0%} (bar <= 20%)")
    print(f"\nBAR: {'PASS' if r_hit >= 0.6 and n_hit <= 0.2 else 'FAIL'}")


if __name__ == "__main__":
    main()
