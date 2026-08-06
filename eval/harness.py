"""Evaluation harness (TECH_SPEC §11). Scores predicted rallies against
hand-labeled rallies and prints the two PRD §5 tables. Reads JSON only,
never video."""

import argparse
import json
import statistics


def iou(a, b):
    """Temporal intersection-over-union of two intervals.

    Each interval is a dict with float 'start' and 'end' (seconds).
    Returns overlap / union in [0, 1]; 0.0 when they do not overlap.
    """
    overlap = min(a["end"], b["end"]) - max(a["start"], b["start"])
    if overlap <= 0.0:
        return 0.0
    union = (a["end"] - a["start"]) + (b["end"] - b["start"]) - overlap
    return overlap / union


def match_intervals(preds, gts, threshold=0.5):
    """Greedy one-to-one temporal matching (TECH_SPEC §11.2).

    Considers every prediction/label pair whose IoU meets the threshold,
    then accepts them best-overlap-first, never reusing a prediction or a
    label. Returns matches, unmatched labels (misses), and unmatched
    predictions (false positives).
    """
    candidates = []
    for pi, p in enumerate(preds):
        for gi, g in enumerate(gts):
            score = iou(p, g)
            if score >= threshold:
                candidates.append((score, pi, gi))
    candidates.sort(reverse=True)  # highest IoU first

    used_pred, used_gt, matches = set(), set(), []
    for score, pi, gi in candidates:
        if pi in used_pred or gi in used_gt:
            continue
        matches.append((pi, gi, score))
        used_pred.add(pi)
        used_gt.add(gi)

    missed = [gi for gi in range(len(gts)) if gi not in used_gt]
    false_pos = [pi for pi in range(len(preds)) if pi not in used_pred]
    return {"matches": matches, "missed": missed, "false_pos": false_pos}


def detection_metrics(preds, gts, source_duration_sec):
    """Detection table (PRD §5). Ignores the 'selected' field.

    - recall: matched labels / all labels
    - false_pos_per_10min: unmatched predictions, normalized to 10 minutes
    - boundary_error_median_sec: median of the absolute start- and end-time
      errors across matched pairs
    """
    m = match_intervals(preds, gts)
    n_labeled, n_pred, n_matched = len(gts), len(preds), len(m["matches"])

    recall = n_matched / n_labeled if n_labeled else 0.0
    fp_per_10min = (
        len(m["false_pos"]) / (source_duration_sec / 600.0)
        if source_duration_sec else 0.0
    )

    errors = []
    for pi, gi, _ in m["matches"]:
        errors.append(abs(preds[pi]["start"] - gts[gi]["start"]))
        errors.append(abs(preds[pi]["end"] - gts[gi]["end"]))
    boundary_error = statistics.median(errors) if errors else 0.0

    return {
        "recall": recall,
        "false_pos_per_10min": fp_per_10min,
        "boundary_error_median_sec": boundary_error,
        "n_labeled": n_labeled,
        "n_pred": n_pred,
        "n_matched": n_matched,
    }


def selection_metrics(preds, budget_sec=600.0):
    """Selection table (PRD §5). Reads the 'selected' flag.

    - selected_duration_sec: total length of selected rallies
    - budget_compliant: total <= budget (hard limit)
    - utilization: total / budget
    - rally_count: number of selected rallies
    - keep_rate: selected / all detected
    """
    selected = [p for p in preds if p.get("selected")]
    selected_dur = sum(p["end"] - p["start"] for p in selected)
    n_pred = len(preds)
    return {
        "selected_duration_sec": selected_dur,
        "budget_compliant": selected_dur <= budget_sec,
        "utilization": selected_dur / budget_sec if budget_sec else 0.0,
        "rally_count": len(selected),
        "keep_rate": len(selected) / n_pred if n_pred else 0.0,
    }


def load_rallies(path):
    """Read a predictions file (rallies.json). Returns (source_duration_sec, rallies)."""
    with open(path) as f:
        data = json.load(f)
    return data["source_duration_sec"], data["rallies"]


def load_labels(path):
    """Read a ground-truth label file (one JSON object per line, from label.py)."""
    labels = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                labels.append(json.loads(line))
    return labels


def format_tables(det, sel):
    """Render the two PRD §5 tables as plain text."""
    return "\n".join([
        "Detection",
        f"  rally recall            {det['recall']:.2f}  ({det['n_matched']}/{det['n_labeled']})",
        f"  false positives /10min  {det['false_pos_per_10min']:.2f}",
        f"  boundary error (median) {det['boundary_error_median_sec']:.2f} s",
        "Selection",
        f"  budget compliant        {sel['budget_compliant']}"
        f"  ({sel['selected_duration_sec']:.1f}s / 600s)",
        f"  utilization             {sel['utilization']:.2f}",
        f"  rally count             {sel['rally_count']}",
        f"  keep rate               {sel['keep_rate']:.2f}",
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Score predicted rallies against labels (PRD §5)."
    )
    ap.add_argument("--pred", required=True, help="rallies.json (predictions)")
    ap.add_argument("--labels", required=True, help="label file, JSON-per-line (ground truth)")
    args = ap.parse_args(argv)

    source_dur, preds = load_rallies(args.pred)
    gts = load_labels(args.labels)
    det = detection_metrics(preds, gts, source_dur)
    sel = selection_metrics(preds)
    print(format_tables(det, sel))


if __name__ == "__main__":
    main()
