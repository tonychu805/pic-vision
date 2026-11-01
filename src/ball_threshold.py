"""Pick the ball detector's confidence cut for one video, after the run.

pod_infer.py is run at a low threshold and writes each detection's own peak
confidence (the Conf column). A venue where the ball is easy to see (dark
walls, close camera) is better served by the strict cut: the low one adds
detections that join separate rallies into one long blob (held-out brickwall,
4 min: 15 rallies at 0.5, 9 at 0.35 with a 72 s and a 45 s blob). A venue where
the far-side ball is lost against a pale wall (PDSC Court 3) is better served
by the low cut: 3 rallies at 0.5, 10 at 0.35. The ball is found in far more
frames at the low cut there, which is the whole point.

Cutting a low-threshold run back to the strict value reproduces a run made at
the strict value (found-frame share identical, rally counts 15/15, 3/2, 3/3 on
the three videos checked), so one inference pass serves both choices.

EXPERIMENTS.md 2026-11-01.
"""
import csv

NOT_SEEN = ["-1", "-1", "-1", "-1", "0.0"]


def apply_adaptive_threshold(csv_in, csv_out, high=0.5, healthy_rate=0.25):
    """Rewrite csv_in to csv_out, keeping the strict cut when the video
    already detects the ball well and the low-threshold detections otherwise.

    The video counts as detecting well when at least `healthy_rate` of its
    frames hold a detection with Conf >= high. Returns a dict:
      cut            `high` when detections below it were dropped, else None
      rate_at_high   share of frames with a detection at Conf >= high
      rate_at_low    share of frames with any detection
    A file with no Conf column (older runs) or no frames is written unchanged.
    """
    with open(csv_in, newline="") as f:
        rows = list(csv.reader(f))
    header, body = rows[0], rows[1:]
    if "Conf" not in header or not body:
        _write(csv_out, rows)
        return {"cut": None, "rate_at_high": 0.0, "rate_at_low": 0.0}
    vis, conf = header.index("Visibility"), header.index("Conf")
    seen = [r for r in body if r[vis] == "1"]
    strong = [r for r in seen if float(r[conf]) >= high]
    rate_high, rate_low = len(strong) / len(body), len(seen) / len(body)
    if rate_high < healthy_rate:
        _write(csv_out, rows)
        return {"cut": None, "rate_at_high": rate_high, "rate_at_low": rate_low}
    kept = [r if (r[vis] == "1" and float(r[conf]) >= high) else [r[0], "0"] + NOT_SEEN for r in body]
    _write(csv_out, [header] + kept)
    return {"cut": high, "rate_at_high": rate_high, "rate_at_low": rate_low}


def _write(path, rows):
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows(rows)
