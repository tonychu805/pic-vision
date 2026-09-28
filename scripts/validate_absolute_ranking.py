"""Would a fixed-scale ("absolute") rally score rank as well as the shipped
one, and pick a better top 10 when a session arrives in 10-minute parts?

Background (2026-09-28). src/select.py's rank_segments (ADR-063) scales each
signal min-max *within the set it is given*. A session sent in parts
(ADR-127/128) is ranked part by part, so every part's best rally scores ~1
however dull it was, and the share page can only interleave parts by rank
(part 1's #1, part 2's #1, ...). A fixed scale would let every rally be
scored once, when its part is processed, and any set of rallies be sorted.

The absolute score uses the same three signals, on fixed units:
  - duration            seconds
  - peak_crossing_rate  net crossings per second in the busiest 3 s
  - n_spikes            ball-speed samples above a FIXED cut-off, in court
                        widths per second (pixel speed / net width in pixels,
                        from each video's calibration) -- pixels alone
                        would make a closer camera look faster
Each is divided by a fixed reference (the median over every candidate rally
in all four videos -- not the grades) and the three are averaged, equal
weights as ADR-063. The spike cut-off is the pooled 90th percentile speed,
matching the shipped per-video 90th percentile on average.

Three checks against the quality:1 (highlight-worthy) / quality:2
(ordinary) hand grades on the four graded videos, same matching as
scripts/validate_ranking.py (IoU >= 0.5):
  1. per video: does quality:1 score higher, for the shipped and the
     absolute score (mean, and the chance a random quality:1 rally
     outscores a random quality:2 one -- 0.5 is a coin flip);
  2. pooled across videos: the same chance, for rallies from different
     videos -- only the absolute score is meant to be comparable there;
  3. parts: split each video into 10-minute parts, pick a top 10 the way
     the share page does today (interleave parts by within-part rank)
     and by sorting absolute scores; count graded rallies in each top 10.
"""
import json
import math
import statistics
import sys

sys.path.insert(0, ".")

from eval.harness import iou
from src.calib import court_wedge
from src.ball import net_line_y, crossing_times, cluster_crossings
from src.select import frame_speeds, spike_threshold, rank_segments, peak_rate
from src.track import track_ball
from src.tracknet import load_predictions

FPS = 30.0
GAP_SEC = 3.0
MIN_CROSSINGS = 6
IOU_THRESHOLD = 0.5
PART_SEC = 600.0
TOP_N = 10
SCORES = (("rel", "shipped       "), ("abs", "absolute      "), ("pasted", "pasted        "), ("pasted_matched", "pasted,matched"))

SESSIONS = [
    ("brickwall_30fps", "cache/brickwall_30fps_predictions_k14.csv",
     "calib/brickwall_30fps_calib.json", "eval/labels/brickwall_30fps.jsonl", None),
    ("pb_draft_cup", "cache/pb_draft_cup_predictions_k14.csv",
     "calib/pb_draft_cup_30fps_calib.json", "eval/labels/pb_draft_cup_30fps.jsonl", None),
    ("IMG_7744", "cache/IMG_7744_predictions_k14.csv",
     "calib/IMG_7744_calib.json", "eval/labels/IMG_7744.jsonl", None),
    ("brickwall-SEMI", "cache/brickwall_semi_predictions_k14.csv",
     "calib/brickwall_semi_calib.json", "eval/labels/brickwall-SEMI.jsonl", 900.0),
]


def detect(csv_path, calib):
    """Candidates, crossings and per-frame speeds, as validate_ranking.py."""
    in_court = court_wedge(calib)
    track = load_predictions(csv_path, FPS)
    times = [t for t, *_ in track]
    frames = [[(x, y, c if c is not None else 1.0)] if in_court(x, y) else []
              for _, x, y, w, h, c in track]
    ys = track_ball(frames, max_jump=150, reset_after=15)
    crossed = crossing_times(list(zip(times, ys)), net_y=net_line_y(calib), band=0.0)
    segments = cluster_crossings(crossed, gap_sec=GAP_SEC, min_crossings=MIN_CROSSINGS)
    raw = sorted([(t, x, y) for t, x, y, w, h, c in track if in_court(x, y)], key=lambda p: p[0])
    return segments, crossed, frame_speeds(raw)


def net_width_px(calib):
    (x0, y0), (x1, y1) = calib["net_image_points"]
    return ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5


def chance_q1_beats_q2(q1, q2):
    """Probability a random quality:1 value beats a random quality:2 one (ties half)."""
    if not q1 or not q2:
        return None
    wins = sum(1.0 if a > b else 0.5 if a == b else 0.0 for a in q1 for b in q2)
    return wins / (len(q1) * len(q2))


def best_match(label, segments):
    scored = sorted(((iou(label, s), s) for s in segments), key=lambda p: -p[0])
    return scored[0][1] if scored and scored[0][0] >= IOU_THRESHOLD else None


def main():
    videos = []
    for name, csv_path, calib_path, labels_path, window_end in SESSIONS:
        calib = json.load(open(calib_path))
        segments, crossed, speeds = detect(csv_path, calib)
        if window_end is not None:  # only the graded stretch
            segments = [s for s in segments if s["end"] <= window_end]
        scale = net_width_px(calib)
        videos.append({
            "name": name, "segments": segments, "crossed": crossed, "speeds": speeds,
            "speeds_cw": [(t, v / scale) for t, v in speeds],  # court widths per second
            "labels": [r for r in (json.loads(l) for l in open(labels_path) if l.strip())
                       if r.get("quality") in (1, 2) and (window_end is None or r["end"] <= window_end)],
        })

    # Fixed references, from every candidate rally (never the grades).
    cutoff = statistics.quantiles([v for vid in videos for _, v in vid["speeds_cw"]], n=100)[89]
    for vid in videos:
        for s in vid["segments"]:
            s["duration"] = s["end"] - s["start"]
            s["pcr"] = peak_rate([t for t in vid["crossed"] if s["start"] <= t <= s["end"]], s["start"], s["end"])
            s["spikes_abs"] = sum(1 for t, v in vid["speeds_cw"] if s["start"] <= t <= s["end"] and v >= cutoff)
    every = [s for vid in videos for s in vid["segments"]]
    ref = {k: statistics.median([s[k] for s in every]) or 1.0 for k in ("duration", "pcr", "spikes_abs")}
    for s in every:
        s["abs_score"] = sum(s[k] / ref[k] for k in ref) / 3
    print(f"fixed spike cut-off {cutoff:.2f} court widths/s; references (medians of {len(every)} candidates): "
          + ", ".join(f"{k}={v:.2f}" for k, v in ref.items()))

    # A 0-100 formula proposed 2026-09-28 (operator-supplied): 35 * length
    # curve + 35 * capped pace + 30 * diminishing hard-shot count. Its
    # constants assume pace ~0.6-1.2 and 0-10 hard shots; ours are a peak
    # 3 s rate (median 1.67) and a count of fast speed READINGS (median 12,
    # several per shot). So it's tested as written, and "matched" with the
    # pace cap at our 90th percentile and the hard-shot half-point at our
    # median -- scale constants from all candidates, never the grades.
    pace_cap = statistics.quantiles([s["pcr"] for s in every], n=10)[8]
    hard_half = ref["spikes_abs"]
    for s in every:
        s_len = 1 - math.exp(-s["duration"] / 12)
        s["pasted"] = 35 * s_len + 35 * min(1.0, s["pcr"] / 1.0) + 30 * s["spikes_abs"] / (s["spikes_abs"] + 3)
        s["pasted_matched"] = 35 * s_len + 35 * min(1.0, s["pcr"] / pace_cap) + 30 * s["spikes_abs"] / (s["spikes_abs"] + hard_half)
    print(f"pasted formula as written: pace at its cap for {sum(s['pcr'] >= 1.0 for s in every)}/{len(every)} candidates, "
          f"hard-shot term >= 0.75 for {sum(s['spikes_abs'] / (s['spikes_abs'] + 3) >= 0.75 for s in every)}/{len(every)}; "
          f"matched: pace cap {pace_cap:.2f}, hard-shot half-point {hard_half:.0f}")

    # Shipped relative score, per whole video (as validate_ranking.py).
    rows = []
    for vid in videos:
        thr = spike_threshold(vid["speeds"], percentile=90)
        rel = {(r["start"], r["end"]): r["score"] for r in rank_segments(vid["segments"], vid["crossed"], vid["speeds"], thr)}
        for s in vid["segments"]:
            s["rel_score"] = rel[(s["start"], s["end"])]
        for lab in vid["labels"]:
            seg = best_match(lab, vid["segments"])
            if seg is not None:
                seg["grade"] = lab["quality"]
                rows.append({"video": vid["name"], "grade": lab["quality"], "rel": seg["rel_score"], "abs": seg["abs_score"],
                             "pasted": seg["pasted"], "pasted_matched": seg["pasted_matched"]})

    print(f"\n{len(rows)} graded rallies matched\n\n1. Per video -- does quality:1 score higher?")
    for vid in videos:
        for key, label in SCORES:
            q1 = [r[key] for r in rows if r["video"] == vid["name"] and r["grade"] == 1]
            q2 = [r[key] for r in rows if r["video"] == vid["name"] and r["grade"] == 2]
            c = chance_q1_beats_q2(q1, q2)
            print(f"  {vid['name']:16s} {label}  q1 mean {statistics.mean(q1):7.3f} (n={len(q1):2d})  "
                  f"q2 mean {statistics.mean(q2):7.3f} (n={len(q2):2d})  "
                  f"{'q1 higher' if statistics.mean(q1) > statistics.mean(q2) else 'Q2 HIGHER'}  chance q1>q2 {c:.2f}")

    print("\n2. Pooled across videos -- chance a quality:1 rally outscores a quality:2 one from ANY video")
    for key, label in SCORES:
        q1 = [r[key] for r in rows if r["grade"] == 1]
        q2 = [r[key] for r in rows if r["grade"] == 2]
        print(f"  {label}  {chance_q1_beats_q2(q1, q2):.2f}")

    print(f"\n3. Top {TOP_N} of a session sent in {PART_SEC / 60:.0f}-minute parts")
    print("   (graded = matched a hand label; the rest are candidates nobody graded, incl. false detections)")
    for vid in videos:
        parts = {}
        for s in vid["segments"]:
            parts.setdefault(int(s["start"] // PART_SEC), []).append(s)
        # Today: rank within each part (shipped score), interleave by rank.
        ranked_parts = []
        for p in sorted(parts):
            thr = spike_threshold([(t, v) for t, v in vid["speeds"] if p * PART_SEC <= t < (p + 1) * PART_SEC], percentile=90)
            ranked = rank_segments(parts[p], vid["crossed"], vid["speeds"], thr)
            ranked_parts.append([next(s for s in parts[p] if s["start"] == r["start"] and s["end"] == r["end"]) for r in ranked])
        interleaved = [rp[i] for i in range(max(map(len, ranked_parts))) for rp in ranked_parts if i < len(rp)][:TOP_N]
        by = {k: sorted(vid["segments"], key=lambda s: -s[k])[:TOP_N] for k in ("abs_score", "pasted", "pasted_matched")}
        n_q1_total = sum(1 for s in vid["segments"] if s.get("grade") == 1)

        def tally(sel):
            g = [s.get("grade") for s in sel]
            return f"q1 {g.count(1):2d}  q2 {g.count(2):2d}  ungraded {g.count(None):2d}"
        print(f"  {vid['name']:16s} {len(parts)} parts, {n_q1_total:2d} q1 available\n"
              f"      today (interleave) {tally(interleaved)}\n      absolute           {tally(by['abs_score'])}\n"
              f"      pasted             {tally(by['pasted'])}\n      pasted, matched    {tally(by['pasted_matched'])}")


if __name__ == "__main__":
    main()
