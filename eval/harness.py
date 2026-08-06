"""Evaluation harness (TECH_SPEC §11). Scores predicted rallies against
hand-labeled rallies and prints the two PRD §5 tables. Reads JSON only,
never video."""

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
