"""Does masking fixed 'scenery' squares remove false rallies without losing real
ones? (PIC-226, offline only -- nothing in the pipeline changes.)

Mask, learned per video from its own detections only (never from grades):
  1. chop the frame into 12x12 px squares;
  2. count detections per square over the whole video;
  3. a square is scenery if it holds >= RATIO x the median count of squares
     that were touched at all (RATIO = 20);
  4. variant 'ring1' also masks the 8 neighbours of each scenery square (bright
     patches straddle square borders); variant 'plain' does not.
A masked detection is dropped BEFORE tracking, crossing counting and speed.

PASS RULE, WRITTEN BEFORE RUNNING (all four must hold, for the variant used):
  (a) ZERO of the hand-graded rallies matched at IoU>=0.5 in the unmasked run
      are lost in the masked run;
  (b) field clip O (the failed serve made of sunlight) is no longer detected
      as a rally (no segment with IoU>=0.5 against its window);
  (c) field clips K, L, N, P, Q, R (watched by the operator: real rallies) are
      all still detected;
  (d) pooled chance quality:1 outscores quality:2 under the shipped score is
      not more than 0.03 below the unmasked run's.
Clip M (a real ball tossed across the net) is NOT expected to change: masking
cannot address it. Everything else is reported, not judged.

Offline analysis on cached predictions. IMG_7743 (locked eval set) is not read.
"""
import collections
import csv
import glob
import json
import statistics
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import validate_absolute_ranking as base  # noqa: E402
from eval.harness import iou  # noqa: E402
from src.ball import net_line_y, crossing_times, cluster_crossings  # noqa: E402
from src.calib import court_wedge  # noqa: E402
from src.select import frame_speeds, net_width_px, score_segments  # noqa: E402
from src.track import track_ball  # noqa: E402
from src.tracknet import load_predictions  # noqa: E402

SQ, RATIO = 12, 20.0
REAL_FIELD = ("K", "L", "N", "P", "Q", "R")
FAKE_FIELD = ("O", "M")


def scenery(track, ring):
    cnt = collections.Counter((round(x / SQ), round(y / SQ)) for _, x, y, *_ in track if x is not None)
    if not cnt:
        return set()
    med = statistics.median(cnt.values())
    hot = {s for s, n in cnt.items() if n >= RATIO * med}
    if ring:
        hot |= {(sx + dx, sy + dy) for sx, sy in hot for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    return hot


def detect(csv_path, calib, ring=None):
    """Production detection; ring=None -> unmasked, False -> plain mask, True -> ring1 mask.
    Returns segments, crossing times, per-frame speeds (from in-court, unmasked-by-mask points)."""
    in_court = court_wedge(calib)
    track = load_predictions(csv_path, base.FPS)
    hot = scenery(track, ring) if ring is not None else set()
    keep = lambda x, y: in_court(x, y) and (round(x / SQ), round(y / SQ)) not in hot
    times = [t for t, *_ in track]
    frames = [[(x, y, c if c is not None else 1.0)] if keep(x, y) else [] for _, x, y, w, h, c in track]
    ys = track_ball(frames, max_jump=150, reset_after=15)
    crossed = crossing_times(list(zip(times, ys)), net_y=net_line_y(calib), band=0.0)
    segs = cluster_crossings(crossed, gap_sec=base.GAP_SEC, min_crossings=base.MIN_CROSSINGS)
    raw = sorted([(t, x, y) for t, x, y, w, h, c in track if keep(x, y)], key=lambda p: p[0])
    removed = sum(1 for _, x, y, *_ in track if x is not None and in_court(x, y) and not keep(x, y))
    total = sum(1 for _, x, y, *_ in track if x is not None and in_court(x, y))
    return segs, crossed, frame_speeds(raw), (removed, total, len(hot))


def matched(label, segs):
    return base.best_match(label, segs)


def main():
    variants = {"plain": False, "ring1": True}
    print(f"rule: mask squares with >= {RATIO:.0f}x the median count of touched {SQ}px squares\n")
    results = {}
    for vname, ring in variants.items():
        # ---- graded dev videos
        lost = gained = 0
        n_before = n_after = segs_before = segs_after = 0
        pooled = {"base": ([], []), "mask": ([], [])}
        removed_rows = []
        for name, csv_path, calib_path, labels_path, window_end in base.SESSIONS:
            calib = json.load(open(calib_path))
            b_segs, b_cr, b_sp, _ = detect(csv_path, calib, None)
            m_segs, m_cr, m_sp, (rem, tot, nhot) = detect(csv_path, calib, ring)
            if window_end is not None:
                b_segs = [s for s in b_segs if s["end"] <= window_end]
                m_segs = [s for s in m_segs if s["end"] <= window_end]
            npx = net_width_px(calib)
            labs = [r for r in (json.loads(l) for l in open(labels_path) if l.strip())
                    if r.get("quality") in (1, 2) and (window_end is None or r["end"] <= window_end)]
            b_sc = {(r["start"], r["end"]): r["score"] for r in score_segments(b_segs, b_cr, b_sp, npx)}
            m_sc = {(r["start"], r["end"]): r["score"] for r in score_segments(m_segs, m_cr, m_sp, npx)}
            for lab in labs:
                bs, ms = matched(lab, b_segs), matched(lab, m_segs)
                if bs is not None:
                    n_before += 1
                    pooled["base"][lab["quality"] - 1].append(b_sc[(bs["start"], bs["end"])])
                if ms is not None:
                    n_after += 1
                    pooled["mask"][lab["quality"] - 1].append(m_sc[(ms["start"], ms["end"])])
                if bs is not None and ms is None:
                    lost += 1
                    removed_rows.append((name, lab["start"], lab["end"], lab["quality"]))
                if bs is None and ms is not None:
                    gained += 1
            segs_before += len(b_segs); segs_after += len(m_segs)
            print(f"  [{vname}] {name:16s} segments {len(b_segs):3d} -> {len(m_segs):3d}; "
                  f"{nhot} scenery squares remove {rem}/{tot} in-court detections ({rem / max(tot, 1):.0%})")
        cb = base.chance_q1_beats_q2(*pooled["base"])
        cm = base.chance_q1_beats_q2(*pooled["mask"])

        # ---- field test: the clips the operator watched
        key = {r["clip"]: r for r in csv.DictReader(open("cache/blind_check_key.csv"))}
        field_status = {}
        seg_before = seg_after = 0
        for clip in REAL_FIELD + FAKE_FIELD:
            k = key[clip]
            sid = [p.split("/")[-1][:-4] for p in glob.glob("cache/pgc_fieldtest/*.csv")
                   if p.split("/")[-1].startswith(k["video"].split(":")[-1])][0]
            calib = json.load(open(f"cache/pgc_fieldtest/{sid}.calib.json"))
            m_segs, *_ = detect(f"cache/pgc_fieldtest/{sid}.csv", calib, ring)
            win = {"start": float(k["start"]), "end": float(k["end"])}
            field_status[clip] = any(iou(win, s) >= 0.5 for s in m_segs)
        tot_b = tot_a = 0
        for p in sorted(glob.glob("cache/pgc_fieldtest/*.csv")):
            sid = p.split("/")[-1][:-4]
            calib = json.load(open(f"cache/pgc_fieldtest/{sid}.calib.json"))
            tot_b += len(detect(p, calib, None)[0]); tot_a += len(detect(p, calib, ring)[0])

        a = lost == 0
        b = not field_status["O"]
        c = all(field_status[x] for x in REAL_FIELD)
        d = cm >= cb - 0.03
        results[vname] = (a, b, c, d)
        print(f"\n[{vname}] graded rallies matched {n_before} -> {n_after}  (lost {lost}, gained {gained}); "
              f"segments {segs_before} -> {segs_after}")
        if removed_rows:
            print("   lost:", removed_rows[:6])
        print(f"[{vname}] field test: all detected rallies {tot_b} -> {tot_a}")
        print(f"[{vname}] field clips still detected as rallies: "
              + ", ".join(f"{c_}={'yes' if field_status[c_] else 'NO'}" for c_ in REAL_FIELD + FAKE_FIELD))
        print(f"[{vname}] shipped score, pooled chance q1>q2: {cb:.3f} -> {cm:.3f}")
        print(f"[{vname}] PASS RULE  (a) none of the graded lost: {'OK' if a else 'FAIL'};  "
              f"(b) O gone: {'OK' if b else 'FAIL'};  (c) the 6 real field clips kept: {'OK' if c else 'FAIL'};  "
              f"(d) score not >0.03 worse: {'OK' if d else 'FAIL'}  =>  {'PASS' if all(results[vname]) else 'FAIL'}\n")


if __name__ == "__main__":
    main()
