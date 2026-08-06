"""Evaluation harness (TECH_SPEC §11). Scores predicted rallies against
hand-labeled rallies and prints the two PRD §5 tables. Reads JSON only,
never video."""


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
