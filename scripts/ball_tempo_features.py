"""Ball-only tempo features per rally, scored against the hand quality grades.

PIC-207 (features) / PIC-208 (compare) under PIC-196. Detection mechanic M1 in
the 2026-10-12 detection-mechanics concept plan. Offline analysis only: no
pipeline change, nothing shipped.

Question: do simple ball-only features that the shipped score does NOT already
use (pace share, kitchen score, escalation, finish speed, ...) separate the
quality:1 (highlight-worthy) rallies from the quality:2 (ordinary) ones, and do
they add anything beyond the shipped absolute score (ADR-133)?

Reuses scripts/validate_absolute_ranking.py (detection, IoU>=0.5 matching to
the grades, court-width speed units) and src/select.py (frame_speeds,
peak_rate, score_segments), so nothing is forked. IMG_7743 (the locked eval
set) is not in the session list and is never read.

DECIDED BEFORE LOOKING AT ANY NUMBER (so the bar can't drift to fit results):
  * Statistic: "chance q1>q2" = probability a random quality:1 rally has a
    higher value than a random quality:2 one (0.5 = coin flip).
  * A feature "tracks the grades" only if pooled chance >= 0.65 (or <= 0.35,
    i.e. reliably LOWER in highlights) AND the same side of 0.5 in at least 3
    of the 4 videos.
  * Labelling agreement is only ~1/3 (PIC-6), so differences smaller than that
    are not read as signal. n per video is small (3-18 quality:1): per-video
    numbers are noisy; the pooled number is for direction, not proof.
  * "Adds something" is judged by correlation with the shipped score: a
    feature that tracks the grades only because it IS the shipped score
    (|rank corr| > 0.8) is redundant and is reported as such.
  * A second session is required before any go/no-go; this is one analysis
    over four dev videos from three venues/cameras, not a go/no-go.

Kitchen score components are reported separately at three net bands so the
choice of band (a free parameter) can be seen, not hidden.
"""
import csv
import json
import statistics
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import validate_absolute_ranking as base  # noqa: E402
from src.ball import net_line_y  # noqa: E402
from src.calib import court_wedge  # noqa: E402
from src.select import peak_rate, score_segments  # noqa: E402
from src.tracknet import load_predictions  # noqa: E402

FPS = base.FPS
BANDS = (0.05, 0.10, 0.20)        # fraction of net width, either side of the net line
EXCHANGE_GAP_SEC = 2.0            # crossings closer than this count as one exchange
FINISH_WINDOW_SEC = 1.0
OUT_CSV = "cache/ball_tempo_features.csv"

FEATURES = [
    # name, direction note
    "duration", "peak_crossing_rate", "hard_n",            # the shipped three, for reference
    "baseline_score",                                      # shipped absolute score (ADR-133)
    "pace_share", "speed_median", "speed_p90", "speed_spread",
    "mean_crossing_rate", "escalation",
    "near_net_05", "near_net_10", "near_net_20", "kitchen_score",
    "longest_exchange", "visibility", "finish_speed",
]


def raw_points(csv_path, calib):
    """In-court ball detections (t, x, y), sorted. Same gate as base.detect."""
    in_court = court_wedge(calib)
    track = load_predictions(csv_path, FPS)
    return sorted([(t, x, y) for t, x, y, w, h, c in track if in_court(x, y)], key=lambda p: p[0])


def rank(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    r = [0.0] * len(values)
    for pos, i in enumerate(order):
        r[i] = float(pos)
    return r


def rank_corr(a, b):
    if len(a) < 3:
        return None
    ra, rb = rank(a), rank(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else None


def longest_exchange(times):
    best = run = 1 if times else 0
    for a, b in zip(times, times[1:]):
        run = run + 1 if b - a <= EXCHANGE_GAP_SEC else 1
        best = max(best, run)
    return best


def features_for(seg, crossed, speeds_cw, raw, net_y, net_px, cutoff, baseline):
    start, end = seg["start"], seg["end"]
    dur = max(end - start, 1e-6)
    xs = [t for t in crossed if start <= t <= end]
    sp = [v for t, v in speeds_cw if start <= t <= end]
    pts = [(t, x, y) for t, x, y in raw if start <= t <= end]
    pcr = peak_rate(xs, start, end)
    mean_rate = len(xs) / dur
    med = statistics.median(sp) if sp else None
    p90 = statistics.quantiles(sp, n=10)[8] if len(sp) >= 10 else None
    hard = sum(1 for v in sp if v >= cutoff)
    near = {b: (sum(1 for _, _, y in pts if abs(y - net_y) <= b * net_px) / len(pts)) if pts else None for b in BANDS}
    fin = [v for t, v in speeds_cw if end - FINISH_WINDOW_SEC <= t <= end]
    kitchen = None
    if near[0.10] is not None and med is not None:
        kitchen = near[0.10] * (1 - min(1.0, med / cutoff))
    return {
        "start": start, "end": end,
        "duration": dur, "peak_crossing_rate": pcr, "hard_n": hard,
        "baseline_score": baseline,
        "pace_share": (hard / len(sp)) if sp else None,
        "speed_median": med, "speed_p90": p90,
        "speed_spread": (p90 / med) if (p90 is not None and med) else None,
        "mean_crossing_rate": mean_rate,
        "escalation": (pcr / mean_rate) if mean_rate else None,
        "near_net_05": near[0.05], "near_net_10": near[0.10], "near_net_20": near[0.20],
        "kitchen_score": kitchen,
        "longest_exchange": longest_exchange(xs),
        "visibility": len(pts) / (dur * FPS),
        "finish_speed": statistics.median(fin) if fin else None,
    }


def main():
    sessions = []
    for name, csv_path, calib_path, labels_path, window_end in base.SESSIONS:
        calib = json.load(open(calib_path))
        segments, crossed, speeds = base.detect(csv_path, calib)
        if window_end is not None:
            segments = [s for s in segments if s["end"] <= window_end]
        net_px = base.net_width_px(calib)
        sessions.append({
            "name": name, "segments": segments, "crossed": crossed, "net_px": net_px,
            "net_y": net_line_y(calib), "raw": raw_points(csv_path, calib),
            "speeds": speeds, "speeds_cw": [(t, v / net_px) for t, v in speeds],
            "labels": [r for r in (json.loads(l) for l in open(labels_path) if l.strip())
                       if r.get("quality") in (1, 2) and (window_end is None or r["end"] <= window_end)],
        })

    # Fixed, grade-free cut-off: pooled 90th percentile court-width speed (as base).
    cutoff = statistics.quantiles([v for s in sessions for _, v in s["speeds_cw"]], n=100)[89]
    print(f"fast-ball cut-off {cutoff:.2f} court widths/s (pooled p90 over {len(sessions)} dev videos; IMG_7743 not read)")

    rows = []
    for s in sessions:
        scored = score_segments(s["segments"], s["crossed"], s["speeds"], s["net_px"])
        score_by = {(r["start"], r["end"]): r["score"] for r in scored}
        for lab in s["labels"]:
            seg = base.best_match(lab, s["segments"])
            if seg is None:
                continue
            f = features_for(seg, s["crossed"], s["speeds_cw"], s["raw"], s["net_y"], s["net_px"],
                             cutoff, score_by[(seg["start"], seg["end"])])
            f.update({"video": s["name"], "grade": lab["quality"]})
            rows.append(f)

    n1 = sum(r["grade"] == 1 for r in rows)
    print(f"{len(rows)} graded rallies matched at IoU>={base.IOU_THRESHOLD} "
          f"(quality:1 = {n1}, quality:2 = {len(rows) - n1})\n")

    with open(OUT_CSV, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["video", "grade", "start", "end"] + FEATURES)
        w.writeheader()
        w.writerows({k: r.get(k) for k in w.fieldnames} for r in rows)
    print(f"wrote {OUT_CSV} (cache/, not committed)\n")

    videos = [s["name"] for s in sessions]
    head = "".join(f"{v[:13]:>14s}" for v in videos)
    print(f"{'feature':20s}{head}{'pooled':>9s}{'rankcorr':>10s}  verdict")
    print(f"{'':20s}" + "".join(f"{'(chance q1>q2)':>14s}" for _ in videos) + f"{'':>9s}{'w/ shipped':>10s}")
    verdicts = {}
    for feat in FEATURES:
        per = []
        for v in videos:
            q1 = [r[feat] for r in rows if r["video"] == v and r["grade"] == 1 and r[feat] is not None]
            q2 = [r[feat] for r in rows if r["video"] == v and r["grade"] == 2 and r[feat] is not None]
            per.append(base.chance_q1_beats_q2(q1, q2))
        q1 = [r[feat] for r in rows if r["grade"] == 1 and r[feat] is not None]
        q2 = [r[feat] for r in rows if r["grade"] == 2 and r[feat] is not None]
        pooled = base.chance_q1_beats_q2(q1, q2)
        pair = [(r[feat], r["baseline_score"]) for r in rows if r[feat] is not None]
        corr = rank_corr([a for a, _ in pair], [b for _, b in pair])
        higher = sum(1 for p in per if p is not None and p > 0.5)
        lower = sum(1 for p in per if p is not None and p < 0.5)
        if pooled is None:
            verdict = "n/a"
        elif pooled >= 0.65 and higher >= 3:
            verdict = "TRACKS (higher in highlights)"
        elif pooled <= 0.35 and lower >= 3:
            verdict = "TRACKS (LOWER in highlights)"
        else:
            verdict = "no signal"
        if verdict.startswith("TRACKS") and corr is not None and abs(corr) > 0.8 and feat not in ("baseline_score",):
            verdict += "; redundant with shipped score"
        verdicts[feat] = verdict
        cells = "".join(f"{('%.2f' % p) if p is not None else ' n/a':>14s}" for p in per)
        print(f"{feat:20s}{cells}{('%.2f' % pooled) if pooled is not None else 'n/a':>9s}"
              f"{('%+.2f' % corr) if corr is not None else 'n/a':>10s}  {verdict}")

    print("\nmissing values (feature not computable for a rally):")
    for feat in FEATURES:
        miss = sum(1 for r in rows if r[feat] is None)
        if miss:
            print(f"  {feat}: {miss}/{len(rows)}")


if __name__ == "__main__":
    main()
