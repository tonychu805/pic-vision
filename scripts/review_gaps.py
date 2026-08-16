#!/usr/bin/env python3
"""
Pass 3 (gap review): surface what the detector found where you labelled nothing.

The point of pass 3 is to keep the answer key from inheriting the detector's
blind spots. Sweeping the whole video again is the brute-force way; this is the
targeted way, and it only works because the two passes are independent — you
hand-mark without seeing the detector's segments, it runs without seeing your
labels. Every detector segment that matches no label is then either a rally you
missed or a detector false positive, and those are the only clips worth
re-watching.

Deliberately one-directional: it never adds anything to the labels on its own.
You grade the extracted clips, and only what you keep gets merged back.

    # 1. extract the disagreements
    python scripts/review_gaps.py extract \
        --labels eval/labels/IMG_7743.jsonl \
        --pred   predictions_rallies.json \
        --out    eval/labels/IMG_7743_gaps.jsonl

    # 2. judge them (1/2 = real rally I missed, 3 = detector noise)
    python label_web.py videos/IMG_7743_label.mp4 --out eval/labels/IMG_7743_gaps.jsonl

    # 3. fold the survivors into the real labels
    python scripts/review_gaps.py merge \
        --labels eval/labels/IMG_7743.jsonl \
        --gaps   eval/labels/IMG_7743_gaps.jsonl
"""
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.harness import iou, match_intervals
from label import load_rallies, save_rallies


def load_predictions_any(path):
    """Accept either a rallies.json ({'rallies': [...]}) or a plain JSONL."""
    if path.endswith(".jsonl"):
        return load_rallies(path)
    with open(path) as f:
        data = json.load(f)
    return data["rallies"] if isinstance(data, dict) else data


def extract(args):
    labels = load_rallies(args.labels)
    preds = load_predictions_any(args.pred)
    if not labels:
        sys.exit(f"no labels in {args.labels} — hand-mark first, or pass 3 is meaningless")

    m = match_intervals(preds, labels, threshold=args.iou)
    unmatched = [preds[pi] for pi in m["false_pos"]]

    # Strip any score/crossings fields so these read as plain candidate intervals
    # in the labeller, and carry no hint of how confident the detector was —
    # the judgement should come from watching, not from the detector's opinion.
    out = [{"start": round(float(p["start"]), 2),
            "end": round(float(p["end"]), 2),
            "duration": round(float(p["end"]) - float(p["start"]), 2)}
           for p in sorted(unmatched, key=lambda p: p["start"])]
    save_rallies(out, args.out)

    matched = len(m["matches"])
    print(f"labels: {len(labels)}   detector segments: {len(preds)}")
    print(f"  agreed (IoU>={args.iou}): {matched}")
    print(f"  detector-only (to review): {len(out)} -> {args.out}")
    print(f"  labelled but detector missed: {len(m['missed'])} "
          f"(nothing to review — these are its recall failures)")


def merge(args):
    labels = load_rallies(args.labels)
    gaps = load_rallies(args.gaps)
    # After grading, anything the user dropped is already gone from the file;
    # what remains is real play they had missed.
    added = 0
    for g in gaps:
        if any(iou(g, l) >= args.iou for l in labels):
            continue          # already covered; don't duplicate
        labels.append(g)
        added += 1
    save_rallies(labels, args.labels)
    print(f"merged {added} recovered rallies -> {args.labels} ({len(labels)} total)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract", help="write detector segments that match no label")
    e.add_argument("--labels", required=True)
    e.add_argument("--pred", required=True, help="rallies.json or .jsonl of detector segments")
    e.add_argument("--out", required=True)
    e.add_argument("--iou", type=float, default=0.3,
                   help="overlap at which a detector segment counts as already labelled "
                        "(default 0.3 — looser than scoring, since a partial overlap still "
                        "means you saw that rally)")
    e.set_defaults(func=extract)

    m = sub.add_parser("merge", help="fold graded gap clips back into the labels")
    m.add_argument("--labels", required=True)
    m.add_argument("--gaps", required=True)
    m.add_argument("--iou", type=float, default=0.3)
    m.set_defaults(func=merge)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
