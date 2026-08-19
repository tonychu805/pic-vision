#!/usr/bin/env python3
"""
Break down a video's remaining false positives (detector segments matching no
label at IoU>=0.5) by likely mechanism, instead of leaving them as one
undifferentiated precision number.

Two mechanisms are cheap to tell apart from timestamps alone:
  fragment  — the false positive overlaps, or sits within gap_sec of, a real
              label. Same burst as an already-labelled rally, just clustered
              into a separate piece by cluster_crossings. Fixable by making
              gap_sec track rally length (PIC-33), not a detector error.
The rest need the ball's actual trajectory, not just its timestamps -- per-frame
plotting has settled this before when aggregate stats (x/y spread) did not
(EXPERIMENTS.md 2026-08-18: the toss artefact had the *largest* horizontal
spread of the windows examined, contradicting the obvious model). This script
plots each remaining candidate's image-y (vs net_y) and image-x over time so a
human can read the shape:
  - smooth, repeated arcs crossing net_y, correlated x motion -> a real ball
    genuinely crossing the net (courtesy return / between-point practice,
    PIC-31) -- not a detector flaw at all.
  - short, erratic, high-frequency jumps inconsistent with ball physics ->
    hallucinated detections / tracking noise.
  - large vertical range confined to one area with little real net-side
    change -> phantom crossing (PIC-34), though this is the hardest of the
    three to read confidently from a plot alone.

Judgement from the plot is still a read, not a verdict -- treat anything
long/high-value the same way EXPERIMENTS.md's own caution reads: confirm by
real playback before citing as settled, especially for long segments where
being wrong is expensive (a long "real crossing" could be a missed rally).

Usage:
    python scripts/fp_anatomy.py \
        --calib calib/IMG_7743_prebump_0-2900s_calib.json \
        --predictions cache/IMG_7743_predictions_k14.csv \
        --labels eval/labels/IMG_7743_prebump_0-2900s.jsonl \
        --out clips/fp_IMG_7743_prebump.png

For a video that was split at a fixed time (e.g. a camera-bump split half),
pass --offset so label/segment times line up with the (relative-timestamped)
label file while the predictions CSV stays in absolute session time.
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.tracknet import rally_segments_from_predictions, load_predictions
from src.calib import court_wedge
from src.ball import net_line_y
from eval.harness import match_intervals, iou
from label import load_rallies

FPS = 30.0


def find_false_positives(calib_path, csv_path, labels_path, *, offset=0.0,
                          gap_sec=3.0, min_crossings=6, band=0.0):
    calib = json.load(open(calib_path))
    net_y = net_line_y(calib)
    wedge = court_wedge(calib)
    segs = rally_segments_from_predictions(
        csv_path, FPS, net_y, gap_sec=gap_sec, min_crossings=min_crossings,
        band=band, in_court=wedge,
    )
    if offset:
        preds = [{"start": s["start"] - offset, "end": s["end"] - offset,
                  "crossings": s["crossings"]} for s in segs if s["start"] >= offset]
    else:
        preds = segs
    labels = load_rallies(labels_path)
    m = match_intervals(preds, labels, threshold=0.5)
    fps = [preds[i] for i in m["false_pos"]]

    def is_fragment(fp):
        for l in labels:
            if iou(fp, l) > 0.0:
                return True
            if 0 <= l["start"] - fp["end"] <= gap_sec or 0 <= fp["start"] - l["end"] <= gap_sec:
                return True
        return False

    fragments = [fp for fp in fps if is_fragment(fp)]
    other = sorted([fp for fp in fps if not is_fragment(fp)], key=lambda f: f["start"])
    return fragments, other, net_y


def plot_grid(name, fps, csv_path, net_y, offset, out_path, ncols=5):
    if not fps:
        print(f"{name}: no non-fragment false positives, nothing to plot")
        return
    track = load_predictions(csv_path, FPS)
    n = len(fps)
    nrows = math.ceil(n / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 2.6 * nrows), squeeze=False)
    for i, fp in enumerate(fps):
        r, c = divmod(i, ncols)
        ax = axes[r][c]
        t0, t1 = fp["start"] + offset - 1.0, fp["end"] + offset + 1.0
        window = [(t, x, y) for t, x, y, w, h, conf in track if t0 <= t <= t1 and x is not None]
        ts = [t - (fp["start"] + offset) for t, x, y in window]
        ys = [y for t, x, y in window]
        xs = [x for t, x, y in window]
        ax2 = ax.twinx()
        ax.plot(ts, ys, ".-", color="tab:blue", ms=3, lw=0.8)
        ax.axhline(net_y, color="red", ls="--", lw=1)
        ax2.plot(ts, xs, ".-", color="tab:orange", ms=3, lw=0.8)
        ax.axvspan(0, fp["end"] - fp["start"], color="green", alpha=0.08)
        ax.set_title(f"{fp['start']:.1f}-{fp['end']:.1f}s  cx={fp['crossings']}", fontsize=8)
        ax.tick_params(labelsize=6)
        ax2.tick_params(labelsize=6)
        ax.invert_yaxis()
    for i in range(n, nrows * ncols):
        r, c = divmod(i, ncols)
        axes[r][c].axis("off")
    fig.suptitle(f"{name} -- blue=y(image,inverted), red=net_y, orange=x(image), green=segment", fontsize=10)
    fig.tight_layout()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig.savefig(out_path, dpi=110)
    print(f"saved {out_path} ({n} panels)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calib", required=True)
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--offset", type=float, default=0.0,
                     help="seconds to subtract from absolute prediction time to match a "
                          "relative-timestamped label file (e.g. a camera-bump split half)")
    ap.add_argument("--out", required=True, help="grid plot PNG path")
    ap.add_argument("--gap-sec", type=float, default=3.0)
    ap.add_argument("--min-crossings", type=int, default=6)
    args = ap.parse_args()

    fragments, other, net_y = find_false_positives(
        args.calib, args.predictions, args.labels, offset=args.offset,
        gap_sec=args.gap_sec, min_crossings=args.min_crossings)

    print(f"false positives: {len(fragments) + len(other)}")
    print(f"  fragments (overlap/adjacent to a label, not a detector error): {len(fragments)}")
    print(f"  non-fragment (need the trajectory plot to read): {len(other)}")
    for fp in other:
        print(f"    {fp['start']:8.2f}-{fp['end']:8.2f}  crossings={fp['crossings']}")

    plot_grid(os.path.basename(args.labels), other, args.predictions, net_y, args.offset, args.out)


if __name__ == "__main__":
    main()
