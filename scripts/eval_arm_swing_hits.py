"""Paddle hits from arm swings: a peak in a player's wrist speed, no ball needed (2026-10-19, PIC-226).
Pre-registered: this file (rule, numbers, matching, bar) was committed after developing on minute 1 and before the
finder was run on minute 2. Minute 2's hit marks were already read (for the ball-track finder, ADR-156); this rule was
not looked at against them.

Context. The ball is seen at contact for about half the hits and almost none on the near side (hit visibility,
minute 1); a hit finder on the ball track failed on held-out play (ADR-156). A hit is a fast arm movement by the
player next to the ball, which yolov8x-pose sees whether or not the ball is visible.
RULE, fixed on minute 1 (chunk 3c frames 0-1799, 22 hits, 11 near / 11 far):
  Players: yolov8x-pose (imgsz 1280, conf 0.25) on every frame, kept when the feet are on court (x -2..22, y -6..50 ft),
  linked frame to frame by nearest feet position (<= 3 ft x sqrt(gap), gaps <= 5 frames); tracks < 15 frames dropped.
  Wrist speed of a player at frame f = max over both wrists (keypoint conf >= 0.3) of the wrist's move from f-2 to f,
  per frame, in box heights. SWING = a frame where that speed is >= 0.06 and the largest within +-10 frames.
  Minute 1 (in-sample): 55 swings, 16 of 22 hits found (near 7/11, far 9/11), 16 of 55 swings on a hit (29%).
  Chance check: the same swings shifted by +-15..150 frames find 3.0 hits on average (max 6).
  Contact falls -5..+5 frames from the swing peak (median about +1). Tried and not chosen: speed relative to
  the hips/shoulders (no better), 1-frame speed (more noise), cut-offs 0.08 / 0.10 (fewer hits, higher precision).
MATCHING: a hit is found if a swing is within +-5 frames and the hit mark lies inside that player's box grown by half
  a box height on every side (at any frame within +-3 of the mark). A swing is on a hit by the same test.
  Side: hit mark below the image net line = near.
DATA (held out for this rule): minute 2, chunk 3c frames 1800-3599, 22 hits (9 near / 13 far),
  eval/labels/hits/cvat_eda301d9_0926T0538_s000_180-240.json.
BAR, minute 2 (all four):
  found      >= 50% of all hits
  near       >= 40% of near-side hits (the ones the ball tracker can't see)
  precision  >= 20% of swings on a hit
  not chance hits found >= 3x the mean of the same swings shifted by +-15..150 frames (step 15)
REPORTED: per side; swings per minute; precision with the cut-offs 0.08 and 0.10 (not gated).
One camera, one court, two minutes: a pass is a lead for a hit candidate generator, not a hit counter.
Run: .venv/bin/python scripts/eval_arm_swing_hits.py --poses     (yolov8x-pose on chunk 3c frames 0-3599, cached)
     .venv/bin/python scripts/eval_arm_swing_hits.py --dev       (minute 1)
     .venv/bin/python scripts/eval_arm_swing_hits.py --score     (minute 2, saved labels)
"""
import json, math, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np

CALIB = "cache/pgc_fieldtest/7358ef3f-6a41-4abe-b431-807eba7bc9f1.calib.json"
META = "cache/scale/eda301d9_2026-09-26T05-38-19_session-000.meta.json"
POSES = "cache/arm_swing/poses_chunk3c_0-3599.json"
OFFSET = 3600                                    # chunk 3c frame 0 = source frame 3600
MIN1 = "eval/labels/hits/cvat_eda301d9_0926T0538_s000_120-180.json"
MIN2 = "eval/labels/hits/cvat_eda301d9_0926T0538_s000_180-240.json"
CONF, MAXD, GAP, MINLEN = 0.3, 3.0, 5, 15        # wrist confidence; track linking (ft, frames); short tracks dropped
LAG, W, S = 2, 10, 0.06                          # wrist speed over LAG frames; peak = max within +-W, >= S box heights/frame
TOL, PAD = 5, 0.5                                # match: +-TOL frames, mark inside the player box grown by PAD box heights


def poses():
    import cv2
    from ultralytics import YOLO
    from src.bounce_eval import project
    H = json.load(open(CALIB))["homography"]; model = YOLO("yolov8x-pose.pt")
    cap = cv2.VideoCapture(json.load(open(META))["path"]); cap.set(cv2.CAP_PROP_POS_FRAMES, OFFSET); out = []
    for i in range(3600):
        ok, im = cap.read()
        if not ok: raise RuntimeError(f"decode {i}")
        r = model.predict(im, imgsz=1280, conf=0.25, classes=[0], verbose=False)[0]; ps = []
        for b, kp in zip(r.boxes.xyxy.cpu().numpy(), r.keypoints.data.cpu().numpy()):
            cx, cy = project(H, (b[0] + b[2]) / 2, b[3])
            if -2 <= cx <= 22 and -6 <= cy <= 50:
                ps.append({"box": [round(float(v), 1) for v in b], "court": [round(float(cx), 2), round(float(cy), 2)],
                           "kp": [[round(float(x), 1), round(float(y), 1), round(float(c), 3)] for x, y, c in kp]})
        out.append(ps)
    json.dump(out, open(POSES, "w"))


def tracks(P, a, b):
    """Link on-court players frame to frame by nearest feet position (greedy, bottom of screen first)."""
    T = []
    for f in range(a, b + 1):
        used = set()
        for p in sorted(P[f], key=lambda p: -p["box"][3]):
            best = None
            for i, t in enumerate(T):
                lf = max(t)
                if i in used or f - lf > GAP: continue
                d = math.dist(t[lf]["court"], p["court"])
                if d <= MAXD * (f - lf) ** 0.5 and (best is None or d < best[0]): best = (d, i)
            if best: T[best[1]][f] = p; used.add(best[1])
            else: T.append({f: p}); used.add(len(T) - 1)
    return [t for t in T if len(t) >= MINLEN]


def wrist_speed(t, lag=LAG):
    s = {}
    for f in t:
        g = f - lag
        if g not in t: continue
        p0, p1 = t[g], t[f]; h = p1["box"][3] - p1["box"][1]
        v = [math.dist(p0["kp"][k][:2], p1["kp"][k][:2]) / h / lag for k in (9, 10)
             if p0["kp"][k][2] >= CONF and p1["kp"][k][2] >= CONF]
        if v: s[f] = max(v)
    return s


def swing_picks(TR, w=W, s=S, lag=LAG):
    out = []
    for i, t in enumerate(TR):
        sp = wrist_speed(t, lag)
        out += [(f, i) for f, v in sp.items() if v >= s and all(v >= sp.get(g, 0) for g in range(f - w, f + w + 1))]
    return out


def inbox(p, h, pad=PAD):
    x0, y0, x1, y1 = p["box"]; hh = y1 - y0
    return x0 - pad * hh <= h["x"] <= x1 + pad * hh and y0 - pad * hh <= h["y"] <= y1 + pad * hh


def matcher(TR, shift=0):
    def ok(pk, h):
        f, i = pk; t = TR[i]
        return abs(f + shift - h["frame"]) <= TOL and any(g in t and inbox(t[g], h) for g in range(h["frame"] - 3, h["frame"] + 4))
    return ok


def score(TR, picks, hits, shift=0):
    ok = matcher(TR, shift)
    return [any(ok(p, h) for p in picks) for h in hits], sum(any(ok(p, h) for h in hits) for p in picks)


SHIFTS = list(range(-150, -14, 15)) + list(range(15, 151, 15))


def run(path, a, b, gated):
    P = json.load(open(POSES)); hits = json.load(open(path))["hits"]; TR = tracks(P, a, b)
    net_y = json.load(open(CALIB))["net_image_points"][0][1]
    pk = swing_picks(TR); found, on = score(TR, pk, hits)
    chance = np.mean([sum(score(TR, pk, hits, d)[0]) for d in SHIFTS])
    print(f"frames {a}-{b}: hits {len(hits)}, player tracks {len(TR)}, swings {len(pk)}")
    res = {}
    for side in ("near", "far", "all"):
        g = [ok for h, ok in zip(hits, found) if side == "all" or (side == "near") == (h["y"] > net_y)]
        res[side] = (sum(g), len(g)); print(f"  {side:4s} found {sum(g):2d}/{len(g)}")
    print(f"  swings on a hit {on}/{len(pk)} ({on / max(1, len(pk)):.0%});  time-shifted swings find {chance:.1f} hits on average")
    for s in (0.08, 0.10):
        p2 = swing_picks(TR, s=s); f2, o2 = score(TR, p2, hits)
        print(f"  (reported) cut-off {s}: swings {len(p2)}, found {sum(f2)}, on a hit {o2} ({o2 / max(1, len(p2)):.0%})")
    if not gated: return
    checks = {"found": res["all"][0] / res["all"][1] >= 0.50, "near": res["near"][0] / max(1, res["near"][1]) >= 0.40,
              "precision": on / max(1, len(pk)) >= 0.20, "not chance": res["all"][0] >= 3 * chance}
    print("BAR: " + "  ".join(f"{k} {'PASS' if v else 'FAIL'}" for k, v in checks.items()) +
          f"  ->  {'PASS' if all(checks.values()) else 'FAIL'}")


if __name__ == "__main__":
    {"--poses": poses, "--dev": lambda: run(MIN1, 0, 1799, False), "--score": lambda: run(MIN2, 1800, 3599, True)}[sys.argv[1]]()
