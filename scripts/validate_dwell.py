"""Test A: does a DWELL rule remove false rallies without losing real ones? (PIC-226)

Idea: a ball in flight does not keep reappearing in the same few pixels; scenery
does. For each in-court detection, count the earlier detections that fell
within R px of it in the previous WINDOW frames. If that count is >= K the
detection is dropped BEFORE tracking, crossing counting and speed.

Parameters fixed before running, from physics and NOT from clip O or M:
  R = 6 px, WINDOW = 30 frames (1 s at 30 fps), K = 4 (primary) and 8
  (conservative). A real ball moves several pixels per frame except at the
  top of an arc, so 4+ repeats inside 1 s within 6 px is already unusual.

PASS RULE (written before running; all must hold for a variant):
  (a) ZERO of the 90 hand-graded dev rallies matched unfiltered are lost;
  (b) ZERO of the operator-judged REAL field clips are lost;
  (c) clip O (failed serve made of sunlight) is gone;
  (d) pooled chance quality:1 > quality:2 not more than 0.03 below unfiltered.
Reported, not judged: how many of the judged NOT-a-rally field clips vanish.
Field set = every field clip the operator has judged (about 55; "very short"
counts as not a rally per LABELING v5; undecided clips excluded). IMG_7743 not read.
"""
import collections, csv, glob, json, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import validate_absolute_ranking as base
from eval.harness import iou
from src.ball import net_line_y, crossing_times, cluster_crossings
from src.calib import court_wedge
from src.select import frame_speeds, net_width_px, score_segments
from src.track import track_ball
from src.tracknet import load_predictions

R, WINDOW = 6.0, 30

def detect(csv_path, calib, k=None):
    in_court = court_wedge(calib)
    track = load_predictions(csv_path, base.FPS)
    keep = [False] * len(track)
    recent = collections.deque()                 # (frame, x, y) of earlier in-court detections
    for i, (t, x, y, w, h, c) in enumerate(track):
        if x is None or not in_court(x, y):
            continue
        while recent and i - recent[0][0] > WINDOW:
            recent.popleft()
        dwell = sum(1 for _, xx, yy in recent if (x - xx) ** 2 + (y - yy) ** 2 <= R * R)
        keep[i] = not (k is not None and dwell >= k)
        recent.append((i, x, y))                 # counted whether or not it was kept
    times = [t for t, *_ in track]
    frames = [[(x, y, c if c is not None else 1.0)] if keep[i] else [] for i, (_, x, y, w, h, c) in enumerate(track)]
    ys = track_ball(frames, max_jump=150, reset_after=15)
    crossed = crossing_times(list(zip(times, ys)), net_y=net_line_y(calib), band=0.0)
    segs = cluster_crossings(crossed, gap_sec=base.GAP_SEC, min_crossings=base.MIN_CROSSINGS)
    raw = sorted([(t, x, y) for i, (t, x, y, *_r) in enumerate(track) if keep[i]], key=lambda p: p[0])
    return segs, crossed, frame_speeds(raw)

# ---- the operator-judged field clips -------------------------------------------------
def sid_of(prefix):
    return [p.split("/")[-1][:-4] for p in glob.glob("cache/pgc_fieldtest/*.csv") if p.split("/")[-1].startswith(prefix)][0]
judged = []                                       # (session_id, start, end, is_real, label)
bk = {r["clip"]: r for r in csv.DictReader(open("cache/blind_check_key.csv"))}
for c in ("K", "L", "N", "P", "Q", "R", "O", "M"):
    r = bk[c]; judged.append((sid_of(r["video"].split(":")[-1]), float(r["start"]), float(r["end"]), c in "KLNPQR", f"blind {c}"))
fk = {r["clip"]: r for r in csv.DictReader(open("cache/flag_check_key.csv"))}
fan = {"S": 0, "T": 1, "U": 0, "V": 0, "W": 0, "X": 1, "Y": 1, "Z": 0}
for c, real in fan.items():
    r = fk[c]; judged.append((sid_of(r["session"]), float(r["start"]), float(r["end"]), bool(real), f"flag {c}"))
pk = {r["clip"]: r for r in csv.DictReader(open("cache/precision_sample_key.csv"))}
REAL = {"01","02","04","05","06","08","10","11","12","13","16","17","19","20","22","23","25","27","28","31","32","33","34","38"}
NOT = {"03","07","09","14","15","18","21","24","26","29","30","36","37","39","40"}   # 35 = can't tell, excluded
for c in sorted(REAL | NOT):
    r = pk[c]; judged.append((sid_of(r["session"]), float(r["start"]), float(r["end"]), c in REAL, f"sample {c}"))
print(f"judged field clips: {len(judged)} ({sum(j[3] for j in judged)} real, {sum(not j[3] for j in judged)} not a rally)\n")

def detected(sid, kk):
    return cache.setdefault((sid, kk), detect(f"cache/pgc_fieldtest/{sid}.csv", json.load(open(f"cache/pgc_fieldtest/{sid}.calib.json")), kk)[0])
cache = {}
def present(j, kk):
    win = {"start": j[1], "end": j[2]}
    return any(iou(win, s) >= 0.5 for s in detected(j[0], kk))

for kk in (4, 8):
    # graded dev videos
    lost = nb = 0; pool_b = ([], []); pool_m = ([], [])
    for name, csvp, calibp, labp, wend in base.SESSIONS:
        calib = json.load(open(calibp)); npx = net_width_px(calib)
        bs, bc, bsp = detect(csvp, calib); ms, mc, msp = detect(csvp, calib, kk)
        if wend: bs = [s for s in bs if s["end"] <= wend]; ms = [s for s in ms if s["end"] <= wend]
        labs = [r for r in (json.loads(l) for l in open(labp) if l.strip()) if r.get("quality") in (1, 2) and (wend is None or r["end"] <= wend)]
        bsc = {(r["start"], r["end"]): r["score"] for r in score_segments(bs, bc, bsp, npx)}
        msc = {(r["start"], r["end"]): r["score"] for r in score_segments(ms, mc, msp, npx)}
        for lab in labs:
            b, m = base.best_match(lab, bs), base.best_match(lab, ms)
            if b is not None: nb += 1; pool_b[lab["quality"] - 1].append(bsc[(b["start"], b["end"])])
            if m is not None: pool_m[lab["quality"] - 1].append(msc[(m["start"], m["end"])])
            lost += (b is not None and m is None)
    cb, cm = base.chance_q1_beats_q2(*pool_b), base.chance_q1_beats_q2(*pool_m)
    real_lost = [j[4] for j in judged if j[3] and present(j, None) and not present(j, kk)]
    real_base_missing = [j[4] for j in judged if j[3] and not present(j, None)]
    not_removed = [j[4] for j in judged if (not j[3]) and present(j, None) and not present(j, kk)]
    not_present_base = sum(1 for j in judged if (not j[3]) and present(j, None))
    o_gone = not any(present(j, kk) for j in judged if j[4] == "blind O")
    tot_b = sum(len(detected(s, None)) for s in {j[0] for j in judged}); tot_m = sum(len(detected(s, kk)) for s in {j[0] for j in judged})
    a, b_, c_, d = lost == 0, len(real_lost) == 0, o_gone, cm >= cb - 0.03
    print(f"K = {kk}:")
    print(f"   graded dev rallies lost: {lost} of {nb}  | pooled chance q1>q2 {cb:.3f} -> {cm:.3f}")
    print(f"   judged REAL field clips lost: {len(real_lost)} {real_lost}  (already undetected unfiltered: {len(real_base_missing)})")
    print(f"   judged NOT-a-rally clips removed: {len(not_removed)} of {not_present_base} detected  {not_removed}")
    print(f"   clip O gone: {o_gone};  detected rallies in those sessions {tot_b} -> {tot_m}")
    print(f"   PASS RULE (a){'OK' if a else 'FAIL'} (b){'OK' if b_ else 'FAIL'} (c){'OK' if c_ else 'FAIL'} (d){'OK' if d else 'FAIL'}  =>  {'PASS' if a and b_ and c_ and d else 'FAIL'}\n")
