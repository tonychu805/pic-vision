"""Does scoring hard shots from the TRACKED ball only (not every in-court
detection) keep the ranking as good against the hand grades? (PIC-226)

Background (2026-10-12). src/rallies.detect_candidates measures ball speed on
every in-court detection ("raw_points"), including light reflections and other
false hits, so a failed serve full of reflections scored 87/100 (rank 1 of 17).
Tracked-only speed uses only positions that survived track_ball's confirmation.

Three variants of the shipped absolute score (ADR-133), all else identical:
  raw            as shipped: hard readings from every in-court detection,
                 half-point 12 (SCORE_HARD_HALF)
  tracked_h12    hard readings from the tracked ball only, half-point left at 12
  tracked_hmed   tracked only, half-point = median tracked hard count over all
                 candidate rallies in the four videos (grade-free), because 12
                 was fitted on raw counts which run ~4x higher

DECIDED BEFORE RUNNING (so the bar cannot move to fit the result). A tracked
variant is acceptable only if BOTH hold:
  (a) its pooled chance quality:1 outscores quality:2 is not more than 0.03
      below the raw variant's (0.03 is inside the sampling noise at n~90);
  (b) quality:1 has the higher MEAN score on every one of the four videos
      (the ADR-063 / validate_ranking criterion).
A tracked variant that is merely "no worse" is NOT shipped on this alone: a
change to the production score also needs a second session and an ADR.

IMG_7743 (the locked eval set) is not in base.SESSIONS and is never read.
"""
import json
import statistics
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import validate_absolute_ranking as base  # noqa: E402
from src.ball import net_line_y, crossing_times, cluster_crossings  # noqa: E402
from src.calib import court_wedge  # noqa: E402
from src.select import frame_speeds, peak_rate, SCORE_HARD_CUTOFF, SCORE_HARD_HALF  # noqa: E402
from src.track import track_ball  # noqa: E402
from src.tracknet import load_predictions  # noqa: E402

LEN, PACE_CAP, W = 12.0, 2.0, (35.0, 35.0, 30.0)   # mirrors src/select.py constants


def score(duration, pcr, n_hard, half):
    import math
    length = 1 - math.exp(-duration / LEN)
    pace = min(1.0, max(pcr, 0.0) / PACE_CAP)
    hard = n_hard / (n_hard + half) if n_hard > 0 else 0.0
    return W[0] * length + W[1] * pace + W[2] * hard


def analyse(csv_path, calib):
    """Same detection as src/rallies.detect_candidates (verified identical on
    two field sessions), plus the tracked ball's positions."""
    in_court = court_wedge(calib)
    track = load_predictions(csv_path, base.FPS)
    times = [t for t, *_ in track]
    frames = [[(x, y, c if c is not None else 1.0)] if in_court(x, y) else []
              for _, x, y, w, h, c in track]
    ys, xs = track_ball(frames, max_jump=150, reset_after=15, return_x=True)
    crossed = crossing_times(list(zip(times, ys)), net_y=net_line_y(calib), band=0.0)
    segments = cluster_crossings(crossed, gap_sec=base.GAP_SEC, min_crossings=base.MIN_CROSSINGS)
    raw = sorted([(t, x, y) for t, x, y, w, h, c in track if in_court(x, y)], key=lambda p: p[0])
    tracked = [(t, x, y) for t, x, y in zip(times, xs, ys) if x is not None]
    return segments, crossed, frame_speeds(raw), frame_speeds(tracked)


def main():
    videos = []
    for name, csv_path, calib_path, labels_path, window_end in base.SESSIONS:
        calib = json.load(open(calib_path))
        segs, crossed, sp_raw, sp_trk = analyse(csv_path, calib)
        if window_end is not None:
            segs = [s for s in segs if s["end"] <= window_end]
        npx = base.net_width_px(calib)
        labels = [r for r in (json.loads(l) for l in open(labels_path) if l.strip())
                  if r.get("quality") in (1, 2) and (window_end is None or r["end"] <= window_end)]
        videos.append({"name": name, "segs": segs, "crossed": crossed, "npx": npx,
                       "sp_raw": sp_raw, "sp_trk": sp_trk, "labels": labels})

    def hard(sp, s, npx):
        return sum(1 for t, v in sp if s["start"] <= t <= s["end"] and v / npx >= SCORE_HARD_CUTOFF)

    for v in videos:
        for s in v["segs"]:
            s["dur"] = s["end"] - s["start"]
            s["pcr"] = peak_rate([t for t in v["crossed"] if s["start"] <= t <= s["end"]], s["start"], s["end"])
            s["h_raw"] = hard(v["sp_raw"], s, v["npx"])
            s["h_trk"] = hard(v["sp_trk"], s, v["npx"])
    every = [s for v in videos for s in v["segs"]]
    half_med = statistics.median([s["h_trk"] for s in every]) or 1.0
    print(f"{len(every)} candidate rallies; median hard readings raw {statistics.median([s['h_raw'] for s in every]):.0f}, "
          f"tracked-only {statistics.median([s['h_trk'] for s in every]):.0f}; "
          f"half-point: shipped {SCORE_HARD_HALF:.0f}, tracked-median {half_med:.0f}\n")
    for s in every:
        s["raw"] = score(s["dur"], s["pcr"], s["h_raw"], SCORE_HARD_HALF)
        s["tracked_h12"] = score(s["dur"], s["pcr"], s["h_trk"], SCORE_HARD_HALF)
        s["tracked_hmed"] = score(s["dur"], s["pcr"], s["h_trk"], half_med)

    VARS = ("raw", "tracked_h12", "tracked_hmed")
    rows = []
    for v in videos:
        for lab in v["labels"]:
            seg = base.best_match(lab, v["segs"])
            if seg is not None:
                rows.append({"video": v["name"], "grade": lab["quality"], **{k: seg[k] for k in VARS}})
    print(f"{len(rows)} graded rallies matched at IoU>={base.IOU_THRESHOLD}\n")

    print(f"{'variant':14s}" + "".join(f"{v['name'][:13]:>15s}" for v in videos) + f"{'pooled':>9s}   q1 mean higher on all 4?")
    result = {}
    for k in VARS:
        cells, higher = [], 0
        for v in videos:
            q1 = [r[k] for r in rows if r["video"] == v["name"] and r["grade"] == 1]
            q2 = [r[k] for r in rows if r["video"] == v["name"] and r["grade"] == 2]
            c = base.chance_q1_beats_q2(q1, q2)
            ok = statistics.mean(q1) > statistics.mean(q2)
            higher += ok
            cells.append(f"{c:.2f}{'+' if ok else '-'}".rjust(15))
        q1 = [r[k] for r in rows if r["grade"] == 1]
        q2 = [r[k] for r in rows if r["grade"] == 2]
        pooled = base.chance_q1_beats_q2(q1, q2)
        result[k] = (pooled, higher)
        print(f"{k:14s}" + "".join(cells) + f"{pooled:9.3f}   {higher}/4")
    print("  (cells: chance q1>q2; + = quality:1 mean higher, - = lower)\n")

    base_pooled = result["raw"][0]
    for k in ("tracked_h12", "tracked_hmed"):
        p, h = result[k]
        a = p >= base_pooled - 0.03
        b = h == 4
        print(f"{k}: (a) pooled {p:.3f} vs raw {base_pooled:.3f} -> {'OK' if a else 'WORSE'};  "
              f"(b) q1 higher on {h}/4 -> {'OK' if b else 'FAILS'};  => {'acceptable' if a and b else 'NOT acceptable'}")


if __name__ == "__main__":
    main()
