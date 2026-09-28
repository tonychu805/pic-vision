"""Do the proposed 0-100 rally score's scale constants hold on PGC footage?

The formula tested 2026-09-28 (scripts/validate_absolute_ranking.py):
    35 * (1 - exp(-length / 12))
  + 35 * min(1, pace / PACE_CAP)
  + 30 * hard / (hard + HARD_HALF)
with PACE_CAP = 2.67 (90th-percentile peak crossing rate) and HARD_HALF = 12
(median count of speed readings above 1.80 court widths/s), both measured
on the four graded test videos. Those are older footage from other venues;
the product scores PGC's cameras. This measures the same quantities on a
sample of PGC field-test parts (9/25-26), re-detected locally exactly as the
pod does it (src/rallies.detect_candidates, same weights and conversion).

Inputs: cache/pgc_fieldtest/<job id>.{mp4,csv,calib.json,label}, made by
re-running the pod's convert + scripts/pod_infer.py on each part.
"""
import glob
import json
import math
import os
import statistics
import sys

sys.path.insert(0, ".")

from src.rallies import detect_candidates
from src.select import peak_rate

DIR = "cache/pgc_fieldtest"
TEST = {"duration": 8.82, "pcr": 1.67, "spikes_abs": 12.0, "pace_cap": 2.67, "cutoff_cw": 1.80}


def net_width_px(calib):
    (x0, y0), (x1, y1) = calib["net_image_points"]
    return math.hypot(x1 - x0, y1 - y0)


def pct(vals, p):
    return statistics.quantiles(vals, n=100)[p - 1]


def main():
    parts = []
    for csv in sorted(glob.glob(f"{DIR}/*.csv")):
        job = os.path.basename(csv)[:-4]
        calib_path = f"{DIR}/{job}.calib.json"
        calib = json.load(open(calib_path))
        cand = detect_candidates(f"{DIR}/{job}.mp4", csv, calib_path)
        scale = net_width_px(calib)
        parts.append({"job": job, "label": open(f"{DIR}/{job}.label").read(), "cand": cand,
                      "speeds_cw": [(t, v / scale) for t, v in cand["speeds"]]})

    pgc_cutoff = pct([v for p in parts for _, v in p["speeds_cw"]], 90)
    rallies = []
    for p in parts:
        crossed = p["cand"]["times_crossed"]
        for s in p["cand"]["segments"]:
            a, b = s["start"], s["end"]
            spd = [v for t, v in p["speeds_cw"] if a <= t <= b]
            rallies.append({
                "camera": p["label"], "duration": b - a,
                "pcr": peak_rate([t for t in crossed if a <= t <= b], a, b),
                "hard_test_cutoff": sum(v >= TEST["cutoff_cw"] for v in spd),
                "hard_pgc_cutoff": sum(v >= pgc_cutoff for v in spd),
            })

    print(f"{len(parts)} PGC parts, {len(rallies)} candidate rallies\n")
    print(f"{'':34s}{'test videos':>12s}{'PGC':>10s}")
    print(f"{'speed cut-off (court widths/s, p90)':34s}{TEST['cutoff_cw']:12.2f}{pgc_cutoff:10.2f}")
    print(f"{'typical length (median s)':34s}{TEST['duration']:12.2f}{statistics.median(r['duration'] for r in rallies):10.2f}")
    print(f"{'typical pace (median)':34s}{TEST['pcr']:12.2f}{statistics.median(r['pcr'] for r in rallies):10.2f}")
    print(f"{'pace cap (p90)':34s}{TEST['pace_cap']:12.2f}{pct([r['pcr'] for r in rallies], 90):10.2f}")
    print(f"{'hard shots, median (test cut-off)':34s}{TEST['spikes_abs']:12.0f}{statistics.median(r['hard_test_cutoff'] for r in rallies):10.0f}")
    print(f"{'hard shots, median (PGC cut-off)':34s}{'':12s}{statistics.median(r['hard_pgc_cutoff'] for r in rallies):10.0f}")

    print("\nPer camera (median length / pace / hard shots at test cut-off, n):")
    for cam in sorted({r["camera"] for r in rallies}):
        rs = [r for r in rallies if r["camera"] == cam]
        print(f"  {cam:16s} {statistics.median(r['duration'] for r in rs):6.1f} s  "
              f"{statistics.median(r['pcr'] for r in rs):5.2f}  {statistics.median(r['hard_test_cutoff'] for r in rs):4.0f}   n={len(rs)}")

    def score(r):
        return (35 * (1 - math.exp(-r["duration"] / 12)) + 35 * min(1.0, r["pcr"] / TEST["pace_cap"])
                + 30 * r["hard_test_cutoff"] / (r["hard_test_cutoff"] + TEST["spikes_abs"]))
    scores = [score(r) for r in rallies]
    print(f"\nScores with the test-video constants on PGC: min {min(scores):.0f}, p10 {pct(scores, 10):.0f}, "
          f"median {statistics.median(scores):.0f}, p90 {pct(scores, 90):.0f}, max {max(scores):.0f}; "
          f"pace at cap for {sum(r['pcr'] >= TEST['pace_cap'] for r in rallies)}/{len(rallies)}")


if __name__ == "__main__":
    main()
