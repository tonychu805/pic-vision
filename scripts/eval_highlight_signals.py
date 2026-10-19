"""Do the new pose signals (player movement, swing activity) help rank highlight-worthy rallies? (2026-10-19, PIC-226)
Pre-registered: this file (features, target, metric, bar) was committed before pose was run on brickwall.

Context. Hits are not production-ready as a counter (39% precision), but ranking highlights needs rank-correlation,
not per-event accuracy. The quality rubric (LABELING.md) lists three marks of a highlight: length/intensity,
momentum swing (a side scrambling / out of position and still winning), sustained tension (a dinking battle). The
shipped ranker (src/select.py) uses duration + peak crossing-rate + velocity; it has no measure of player movement
(scrambling) and proxies dinking only by raw crossings (noted there as over-rewarding dink rallies). Player movement
and swing activity are the new signals; this tests whether they separate graded rallies and add over the baseline.

DATA: brickwall_30fps (dev set, not the locked eval IMG_7743), 49 hand-graded rallies (13 grade-1 highlight-worthy,
  36 grade-2 ordinary; eval/labels/brickwall_30fps.jsonl). Calib calib/brickwall_30fps_calib.json, ball predictions
  cache/brickwall_30fps_predictions_k14.csv. Pose yolov8x-pose over each rally's frames (cached).
FEATURES, per rally (all rate-normalised by rally duration so a long rally is not favoured twice; duration kept raw):
  baseline   duration (s); crossing_rate = net crossings / s (tracked ball, court y across 22).
  new        move_rate  = total court-feet travelled by on-court players / s (per-frame feet position through the
                          homography, per-player step capped at 3 ft to reject pose jitter, summed over players);
             peak_speed = max over players of a 5-frame-smoothed court speed (ft/s) — the "scramble" measure;
             swing_rate = wrist-speed swing peaks (eval_arm_swing_hits.swing_picks) / s.
TARGET: quality grade 1 (highlight) vs 2 (ordinary).
METRIC: AUC(grade1 > grade2) for each feature. Added value: leave-one-out logistic-regression AUC of the baseline
  {duration, crossing_rate} vs baseline + each new feature.
BAR (a LEAD, not a validation — the grade rubric is first-draft and never consistency-checked, LABELING.md):
  a new feature is a lead if its own AUC >= 0.65 AND it raises the leave-one-out AUC over the baseline by >= 0.03.
REPORTED: every feature's AUC and median by grade; the baseline AUC; correlations among features.
One video, 49 rallies, soft grades: a lead says "worth wiring into the ranker and validating on held-out graded
footage", not "ship it".
Run: .venv/bin/python scripts/eval_highlight_signals.py --poses   (compute+cache pose over rally frames)
     .venv/bin/python scripts/eval_highlight_signals.py --score
"""
import json, math, os, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np

TARGETS = {
    "brickwall": dict(lab="eval/labels/brickwall_30fps.jsonl", calib="calib/brickwall_30fps_calib.json",
                      csv="cache/brickwall_30fps_predictions_k14.csv", video="videos/brickwall_30fps.mp4",
                      poses="cache/arm_swing/poses_brickwall_rallies.json"),
    "pbdc": dict(lab="eval/labels/pb_draft_cup_30fps.jsonl", calib="calib/pb_draft_cup_30fps_calib.json",
                 csv="cache/pb_draft_cup_predictions_k14.csv", video="videos/pb_draft_cup_30fps.mp4",
                 poses="cache/arm_swing/poses_pbdc_rallies.json"),
    "img7743": dict(lab="eval/labels/IMG_7743.jsonl", calib="calib/IMG_7743_calib.json",
                    csv="cache/IMG_7743_predictions_k14.csv", video="videos/IMG_7743_fixed.mp4",
                    poses="cache/arm_swing/poses_img7743_rallies.json"),
}
LAB = CALIB = CSV = VIDEO = POSES = None
FPS = 30.0


def set_target(name):
    global LAB, CALIB, CSV, VIDEO, POSES
    t = TARGETS[name]; LAB, CALIB, CSV, VIDEO, POSES = t["lab"], t["calib"], t["csv"], t["video"], t["poses"]
STEP_CAP, SMOOTH = 3.0, 5


def rallies():
    rs = [json.loads(l) for l in open(LAB) if l.strip()]
    return [r for r in rs if r.get("quality") in (1, 2)]


def rally_frames(r):
    return range(int(round(r["start"] * FPS)), int(round(r["end"] * FPS)) + 1)


def poses():
    import cv2
    from ultralytics import YOLO
    from src.bounce_eval import project
    H = json.load(open(CALIB))["homography"]; model = YOLO("yolov8x-pose.pt")
    want = sorted(set(f for r in rallies() for f in rally_frames(r)))
    wantset = set(want); lo, hi = want[0], want[-1]
    cap = cv2.VideoCapture(VIDEO); cap.set(cv2.CAP_PROP_POS_FRAMES, lo); out = {}; n = 0
    for f in range(lo, hi + 1):
        ok, im = cap.read()
        if not ok: break
        if f not in wantset: continue
        n += 1
        r = model.predict(im, imgsz=960, conf=0.25, classes=[0], device=0, verbose=False)[0]; ps = []
        for b, kp in zip(r.boxes.xyxy.cpu().numpy(), r.keypoints.data.cpu().numpy()):
            cx, cy = project(H, (b[0] + b[2]) / 2, b[3])
            if -2 <= cx <= 22 and -6 <= cy <= 50:
                ps.append({"box": [round(float(v), 1) for v in b], "court": [round(float(cx), 2), round(float(cy), 2)],
                           "kp": [[round(float(x), 1), round(float(y), 1), round(float(c), 3)] for x, y, c in kp]})
        out[f] = ps
        if n % 500 == 0: print(n, "/", len(want), flush=True)
    json.dump(out, open(POSES, "w")); print("poses cached", len(out))


def crossings_per_rally():
    import eval_bounce_recovery as E
    _, _, tracked, _ = E.clip_points({"calib": CALIB, "csv": CSV})
    H = np.array(json.load(open(CALIB))["homography"], float)
    from src.bounce_eval import project
    cy = {f: project(H, x, y)[1] for f, (x, y) in tracked.items()}
    out = {}
    for r in rallies():
        fs = [f for f in rally_frames(r) if f in cy]
        c = 0
        for a, b in zip(fs, fs[1:]):
            if b - a <= 6 and (cy[a] - 22) * (cy[b] - 22) < 0: c += 1
        out[r["rally_id"]] = c
    return out


def features():
    import eval_arm_swing_hits as A
    P = {int(k): v for k, v in json.load(open(POSES)).items()}
    cr = crossings_per_rally(); rows = []
    for r in rallies():
        fs = list(rally_frames(r)); dur = max(0.5, r["end"] - r["start"])
        Pl = [P.get(f, []) for f in fs]
        TR = A.tracks(Pl, 0, len(fs) - 1)
        move = 0.0; peak = 0.0
        for t in TR:
            ks = sorted(t); pos = {k: t[k]["court"] for k in ks}
            for a, b in zip(ks, ks[1:]):
                if b - a <= 3:
                    d = math.dist(pos[a], pos[b])
                    if d <= STEP_CAP * (b - a): move += d
            sm = [pos[k] for k in ks]
            for i in range(len(sm) - SMOOTH):
                d = math.dist(sm[i], sm[i + SMOOTH]) / (SMOOTH / FPS)
                peak = max(peak, d)
        nsw = len(A.swing_picks(TR))
        rows.append(dict(rid=r["rally_id"], q=r["quality"], dur=dur, cross_rate=cr.get(r["rally_id"], 0) / dur,
                         move_rate=move / dur, peak_speed=peak, swing_rate=nsw / dur))
    return rows


def auc(pos, neg):
    return sum((p > q) + 0.5 * (p == q) for p in pos for q in neg) / max(1, len(pos) * len(neg))


def loo_auc(X, y):
    try:
        from sklearn.linear_model import LogisticRegression
    except Exception:
        return None
    X = np.array(X, float); y = np.array(y); X = (X - X.mean(0)) / (X.std(0) + 1e-9); s = np.zeros(len(y))
    for i in range(len(y)):
        m = np.ones(len(y), bool); m[i] = False
        if len(set(y[m])) < 2: s[i] = 0.5; continue
        s[i] = LogisticRegression(max_iter=1000).fit(X[m], y[m]).predict_proba(X[i:i + 1])[0, 1]
    return auc(s[y == 1], s[y == 0])


def score():
    rows = features(); g1 = [r for r in rows if r["q"] == 1]; g2 = [r for r in rows if r["q"] == 2]
    print(f"rallies {len(rows)}: grade-1 {len(g1)}, grade-2 {len(g2)}")
    feats = ["dur", "cross_rate", "move_rate", "peak_speed", "swing_rate"]
    print(f"\n{'feature':12s} {'AUC(1>2)':>9s} {'med g1':>9s} {'med g2':>9s}")
    aucs = {}
    for f in feats:
        p = [r[f] for r in g1]; n = [r[f] for r in g2]; a = auc(p, n); aucs[f] = a
        print(f"{f:12s} {a:9.2f} {np.median(p):9.2f} {np.median(n):9.2f}")
    y = [1 if r["q"] == 1 else 0 for r in rows]
    base = [[r["dur"], r["cross_rate"]] for r in rows]; ba = loo_auc(base, y)
    print(f"\nbaseline (duration + crossing_rate) leave-one-out AUC: {ba}")
    if ba is not None:
        for f in ("move_rate", "peak_speed", "swing_rate"):
            a = loo_auc([[r["dur"], r["cross_rate"], r[f]] for r in rows], y)
            lead = aucs[f] >= 0.65 and (a - ba) >= 0.03
            print(f"  + {f:11s}: LOO AUC {a:.2f}  (delta {a - ba:+.2f})  own AUC {aucs[f]:.2f}  ->  {'LEAD' if lead else 'no'}")
    import itertools
    print("\nfeature correlations:")
    for a, b in itertools.combinations(feats, 2):
        c = np.corrcoef([r[a] for r in rows], [r[b] for r in rows])[0, 1]
        if abs(c) >= 0.4: print(f"  {a} ~ {b}: {c:+.2f}")


if __name__ == "__main__":
    set_target(sys.argv[2] if len(sys.argv) > 2 else "brickwall")
    if sys.argv[1] == "--poses": poses()
    else: score()
