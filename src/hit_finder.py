"""Rally finding from paddle swings (the "hit finder"), for the pod (2026-11-12, staging).

A port of scripts/hit_detector.py on feat/ball-recall-eval (and the helpers it
imports from eval_arm_swing_hits, eval_swing_ball_hits, eval_shot_rules_gated,
eval_serve_detector), with the same constants and the same arithmetic, so a
rally list from here matches the research runs it was judged on: every swing
pick (pose wrist speed) gets 16 features, a frozen gradient-boosted tree
(hit_finder_v0.json, exported from sklearn, no sklearn on the pod) scores it
as a real hit or not, and accepted hits chain into rallies.

v0 is tournament-trained (the YouTube practice set) and is NOT the final
model: the retrain on recreational labels (option A) replaces it.

Pose is the cost: yolov8n-pose on EVERY frame, twice (whole frame, and a
close-up of the far court where players are small). Measured locally at
about 3 min per 5-min part; the pod budget is about 2.5 min (EXPERIMENTS
2026-11-10), not yet measured on the pod.
"""
import bisect
import json
import math
import os
import time

import numpy as np

FPS = 30.0
NET = 22.0                                       # court feet from the near baseline
COURT_X, COURT_Y = (-3.0, 23.0), (-8.0, 52.0)    # players counted inside these (feet)
WIN, OVERLAP = 60.0, 5.0                         # player tracks are linked in windows of WIN s
# Player tracks and swings (eval_arm_swing_hits).
CONF, MAXD, TRACK_GAP, MINLEN = 0.3, 3.0, 5, 15
LAG, W, S = 2, 10, 0.06
# Ball check around a swing (eval_swing_ball_hits).
PLAY_W, PLAY_N, NEAR_W, NEAR_N, FAR = 15, 3, 5, 2, 0.5
AFTER = 46                                       # frames looked at for a net crossing after/before a swing
# Chains into rallies (hit_detector.py, settings as frozen 2026-11-10/11).
MIN_TURNS, DEEP_FT, DEEP_MAX_FT, DEEP_WINDOW = 4, 15.0, 28.0, 3.0
CROSS_GAP = 6.0
SERVE_PAUSE, SERVE_QUIET = 1.5, 1.0
SETUP_FT, SETUP_HOLD, SETUP_DEAD = 1.0, 2.0, 1.5
# Cost (2026-11-12): pose every STRIDE-th frame. 2 halves the pose work; on
# the 9 PGC parts it found 6 fewer of 89 real rallies and flagged 22 fewer
# (F 0.610 vs 0.604, EXPERIMENTS 2026-11-12). Serve set-ups are sampled
# every SETUP_STEP frames, a multiple of STRIDE so every sample was posed
# (the research code used 3, i.e. every 0.1 s, at STRIDE 1).
STRIDE = 2
SETUP_STEP = 6

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hit_finder_v0.json")
FEATURES = ("behind", "from_net", "wide", "wrist", "own_side", "other_side", "ball_near", "ball_3s", "ball_check",
            "cross_after", "cross_before", "away", "opp_before", "opp_after", "same_1s", "any_5s")


# --- The frozen model ---

class Model:
    """sklearn HistGradientBoostingClassifier (binary), evaluated from its exported trees."""

    def __init__(self, path=MODEL_PATH):
        d = json.load(open(path))
        if list(d["features"]) != list(FEATURES):
            raise ValueError(f"{path}: features {d['features']} do not match this code's {FEATURES}")
        self.baseline = d["baseline"]
        self.trees = d["trees"]
        self.cut = d["setting"]["cut"]
        self.gap = d["setting"]["gap"]
        self.check = d.get("check")

    def _tree(self, t, x):
        i = 0
        while not t["is_leaf"][i]:
            v = x[t["feature_idx"][i]]
            if v != v:                                   # NaN
                i = t["left"][i] if t["missing_go_to_left"][i] else t["right"][i]
            else:
                i = t["left"][i] if v <= t["num_threshold"][i] else t["right"][i]
        return t["value"][i]

    def predict_proba(self, rows):
        """Probability of "real hit" for each row (a list of FEATURES values)."""
        raw = [self.baseline + sum(self._tree(t, x) for t in self.trees) for x in rows]
        return [1.0 / (1.0 + math.exp(-r)) for r in raw]


# --- Geometry ---

def calibration_size(calib, w, h):
    """The resolution the calibration's pixels are in (eval_serve_detector's rule)."""
    return calib.get("calibration_resolution") or \
        ((1920, 1080) if max(p[0] for p in calib["image_points"]) > w else (w, h))


def homography(calib, w, h):
    cw, ch = calibration_size(calib, w, h)
    return np.array(calib["homography"]) @ np.diag([cw / w, ch / h, 1.0])


def far_crop_box(calib, w, h):
    """A 16:9 box around the far court (players there are a few pixels tall in the whole frame)."""
    cw, _ = calibration_size(calib, w, h)
    pts = {n: (x * w / cw, y * w / cw) for n, (x, y) in zip(calib["point_names"], calib["image_points"])}
    far = [pts["far-left corner"], pts["far-right corner"]]
    nvz = [pts["far NVZ line x left sideline"], pts["far NVZ line x right sideline"]]
    width = abs(far[1][0] - far[0][0])
    xs = [p[0] for p in far + nvz]
    x0, x1 = min(xs) - 0.5 * width, max(xs) + 0.5 * width
    y1 = max(p[1] for p in nvz) + 0.1 * width
    y0 = min(p[1] for p in far) - 0.6 * width
    if (x1 - x0) / (y1 - y0) < 16 / 9:
        grow = ((y1 - y0) * 16 / 9 - (x1 - x0)) / 2
        x0, x1 = x0 - grow, x1 + grow
    else:
        grow = ((x1 - x0) * 9 / 16 - (y1 - y0)) / 2
        y0, y1 = y0 - grow, y1 + grow
    return int(max(0, x0)), int(max(0, y0)), int(min(w, x1)), int(min(h, y1))


# --- Players, swings, ball ---

def people_per_frame(full, far, n, k):
    """Per frame, the on-court people: near half from the whole-frame pass, far half from the close-up.
    k scales pose pixels into calibration pixels (the ball predictions' units)."""
    P = [[] for _ in range(n)]
    for have, is_far in ((full, False), (far, True)):
        for f in range(n):
            P[f] += [{**p, "box": [v * k for v in p["box"]], "kp": [[x * k, y * k, c] for x, y, c in p["kp"]]}
                     for p in have.get(str(f), [])
                     if (p["court"][1] >= NET) == is_far
                     and COURT_X[0] <= p["court"][0] <= COURT_X[1] and COURT_Y[0] <= p["court"][1] <= COURT_Y[1]]
    return P


def tracks(P, a, b):
    """Link on-court players frame to frame by nearest feet position (greedy, bottom of screen first)."""
    T = []
    for f in range(a, b + 1):
        used = set()
        for p in sorted(P[f], key=lambda p: -p["box"][3]):
            best = None
            for i, t in enumerate(T):
                lf = max(t)
                if i in used or f - lf > TRACK_GAP:
                    continue
                d = math.dist(t[lf]["court"], p["court"])
                if d <= MAXD * (f - lf) ** 0.5 and (best is None or d < best[0]):
                    best = (d, i)
            if best:
                T[best[1]][f] = p
                used.add(best[1])
            else:
                T.append({f: p})
                used.add(len(T) - 1)
    return [t for t in T if len(t) >= MINLEN]


def wrist_speed(t, lag=LAG):
    s = {}
    for f in t:
        g = f - lag
        if g not in t:
            continue
        p0, p1 = t[g], t[f]
        h = p1["box"][3] - p1["box"][1]
        v = [math.dist(p0["kp"][k][:2], p1["kp"][k][:2]) / h / lag for k in (9, 10)
             if p0["kp"][k][2] >= CONF and p1["kp"][k][2] >= CONF]
        if v:
            s[f] = max(v)
    return s


def swing_picks(TR, w=W, s=S, lag=LAG):
    out = []
    for i, t in enumerate(TR):
        sp = wrist_speed(t, lag)
        out += [(f, i) for f, v in sp.items() if v >= s and all(v >= sp.get(g, 0) for g in range(f - w, f + w + 1))]
    return out


def keep(T, TR, f, i):
    """The swing happened while the ball was in play and was not seen far from this player."""
    if sum(g in T for g in range(f - PLAY_W, f + PLAY_W + 1)) < PLAY_N:
        return False
    x0, y0, x1, y1 = TR[i][f]["box"]
    hh = y1 - y0
    d = [max(0, x0 - T[g][0], T[g][0] - x1, y0 - T[g][1], T[g][1] - y1) / hh
         for g in range(f - NEAR_W, f + NEAR_W + 1) if g in T]
    return not (len(d) >= NEAR_N and min(d) > FAR)


def ball_points(csv_path, calib):
    """{frame: (x, y)} of the tracked ball, calibration pixels (production's court wedge + tracker)."""
    from src.calib import court_wedge
    from src.track import max_jump_for_fps, reset_after_for_fps, track_ball
    from src.tracknet import load_predictions
    tr = load_predictions(csv_path, FPS)
    inc = court_wedge(calib)
    frames = [[(x, y, c if c is not None else 1.0)] if inc(x, y) else [] for _, x, y, w, h, c in tr]
    ys, xs = track_ball(frames, max_jump=max_jump_for_fps(FPS), reset_after=reset_after_for_fps(FPS), return_x=True)
    return {f: (x, y) for f, (x, y) in enumerate(zip(xs, ys)) if y is not None}


def crosses(T, ny, frames):
    ys = [T[g][1] for g in frames if g in T]
    return any((a - ny) * (b - ny) < 0 for a, b in zip(ys, ys[1:]))


def candidates(P, n, T, ny):
    """Every swing pick with its features, sorted by time."""
    out = {}
    for lo in range(0, n, int((WIN - OVERLAP) * FPS)):
        TR = tracks(P, lo, min(n - 1, lo + int(WIN * FPS)))
        ws = [wrist_speed(t) for t in TR]
        for f, i in swing_picks(TR):
            x, y = TR[i][f]["court"]
            near = y < NET
            if (f, near) in out:
                continue
            after = [T[g][1] for g in range(f, f + 16) if g in T]
            out[f, near] = {
                "t": f / FPS, "side": "near" if near else "far",
                "behind": -y if near else y - 44, "from_net": abs(y - NET), "wide": max(0, -x, x - 20),
                "wrist": ws[i][f],
                "own_side": sum((p["court"][1] < NET) == near for p in P[f]),
                "other_side": sum((p["court"][1] < NET) != near for p in P[f]),
                "ball_near": sum(g in T for g in range(f - 15, f + 16)),
                "ball_3s": sum(g in T for g in range(f - 90, f + 91)),
                "ball_check": int(keep(T, TR, f, i)),
                "cross_after": int(crosses(T, ny, range(f, f + AFTER))),
                "cross_before": int(crosses(T, ny, range(f - AFTER, f))),
                "away": (after[-1] - after[0]) * (1 if near else -1) if len(after) >= 2 else 0.0,
            }
    C = sorted(out.values(), key=lambda c: c["t"])
    for c in C:
        dt = [(d["t"] - c["t"], d["side"] == c["side"]) for d in C if d is not c and abs(d["t"] - c["t"]) <= 5]
        c["opp_before"] = sum(not same and -3 <= d <= -0.4 for d, same in dt)
        c["opp_after"] = sum(not same and 0.4 <= d <= 3 for d, same in dt)
        c["same_1s"] = sum(same and abs(d) <= 1 for d, same in dt)
        c["any_5s"] = len(dt)
    return C


# --- Chains into rallies ---

def serve_setups(full, far, crossings, step=None):
    """Start times (s) of serve set-ups: someone at/behind each baseline, held, ball dead (sampled every `step` frames)."""
    if SETUP_FT is None or not full:
        return []
    step = step or SETUP_STEP
    hold = int(round(SETUP_HOLD * FPS / step))
    n = max(int(f) for f in full) + 1
    out, run, t0 = [], 0, None
    for f in range(0, n, step):
        ys = [p["court"][1] for p in full.get(str(f), []) if p["court"] and p["court"][1] < NET] + \
             [p["court"][1] for p in far.get(str(f), []) if p["court"] and p["court"][1] >= NET]
        ys = [y for y in ys if -8 <= y <= 52]
        back = any(y <= SETUP_FT for y in ys) and any(y >= 44 - SETUP_FT for y in ys)
        if not back:
            run = 0
            continue
        t0 = f / FPS if run == 0 else t0
        run += 1
        if run == hold and not any(t0 <= x <= t0 + SETUP_DEAD for x in crossings):
            out.append(t0)
    return out


def split_at_dead_ball(ch, crossings, g):
    """Cut a chain at the middle of every stretch of at least g s with no net crossing."""
    edges = [ch[0]["t"]] + [t for t in crossings if ch[0]["t"] < t < ch[-1]["t"]] + [ch[-1]["t"]]
    cuts = [(a + b) / 2 for a, b in zip(edges, edges[1:]) if b - a >= g]
    pieces = [[c for c in ch if lo < c["t"] <= hi] for lo, hi in zip([-1e9] + cuts, cuts + [1e9])]
    return [p for p in pieces if p]


def build(C, prob, cut, gap, crossings=None, setups=None):
    """Accepted hits (prob >= cut) chained while gaps <= gap s, cut between points; [{start, end}] in seconds."""
    xs = sorted(crossings or [])
    chains = []
    for c in (c for c, p in zip(C, prob) if p >= cut):
        pause = c["t"] - chains[-1][-1]["t"] if chains else None
        # A ball crossing the net during the pause means the rally is still on.
        live = crossings is not None and pause is not None and \
            bisect.bisect_left(xs, chains[-1][-1]["t"] + SERVE_QUIET) < bisect.bisect_right(xs, c["t"])
        serve = SERVE_PAUSE is not None and pause is not None and pause >= SERVE_PAUSE and not live \
            and DEEP_FT <= c["from_net"] <= DEEP_MAX_FT
        if chains and pause <= gap and not serve:
            chains[-1].append(c)
        else:
            chains.append([c])
    if CROSS_GAP is not None and crossings is not None:
        chains = [p for ch in chains for p in split_at_dead_ball(ch, crossings, CROSS_GAP)]
    if setups:
        chains = [p for ch in chains for p in
                  ([c for c in ch if lo <= c["t"] < hi] for lo, hi in
                   zip([-1e9] + [t for t in setups if ch[0]["t"] < t < ch[-1]["t"]],
                       [t for t in setups if ch[0]["t"] < t < ch[-1]["t"]] + [1e9])) if p]
    out = []
    for ch in chains:
        if 1 + sum(a["side"] != b["side"] for a, b in zip(ch, ch[1:])) < MIN_TURNS or \
                not any(DEEP_FT <= c["from_net"] <= DEEP_MAX_FT for c in ch if c["t"] - ch[0]["t"] <= DEEP_WINDOW):
            continue
        out.append({"start": ch[0]["t"] - 0.5, "end": ch[-1]["t"] + 1.5})
    return out


def rallies_from_poses(full, far, n, w, csv_path, calib, crossings, model, setup_step=None):
    """Rallies from already-posed frames (both passes, keyed by str(frame))."""
    from src.ball import net_line_y
    k = (calib.get("calibration_resolution") or [w])[0] / w
    P = people_per_frame(full, far, n, k)
    C = candidates(P, n, ball_points(csv_path, calib), net_line_y(calib))
    prob = model.predict_proba([[c[f] for f in FEATURES] for c in C]) if C else []
    segs = build(C, prob, model.cut, model.gap, crossings, serve_setups(full, far, crossings, setup_step)) if C else []
    return segs, {"candidates": len(C), "accepted": sum(p >= model.cut for p in prob)}


def find_rallies(video, csv_path, calib, crossings, pose_model, progress=None, model=None, stride=None, keep_full=None):
    """Pose every `stride`-th frame of `video` (whole frame + far close-up, one decode) and return (rallies, info).

    keep_full, a dict, receives the whole-frame poses ({str(frame): [person]}): badges reuse them
    rather than posing those frames again."""
    import cv2
    from src.pose import CropModel, pose_video_passes
    stride = stride or STRIDE
    cap = cv2.VideoCapture(video)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    model = model or Model()
    H = homography(calib, w, h)
    frames = list(range(0, n, stride))
    t0 = time.perf_counter()
    posed = pose_video_passes(video, frames, {"full": pose_model, "far": CropModel(pose_model, far_crop_box(calib, w, h))},
                              H, progress=progress and (lambda d, t: progress("both", d, t)))
    t1 = time.perf_counter()
    if keep_full is not None:
        keep_full.update(posed["full"])
    setup_step = SETUP_STEP if stride == STRIDE else 3 * stride
    segs, info = rallies_from_poses(posed["full"], posed["far"], n, w, csv_path, calib, crossings, model, setup_step)
    # Where the time went: pose (decode + GPU) vs features and chaining (pure Python).
    info.update(frames=n, posed=len(frames), stride=stride,
                pose_sec=round(t1 - t0, 1), features_sec=round(time.perf_counter() - t1, 1))
    return segs, info
