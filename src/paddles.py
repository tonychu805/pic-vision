"""Zero-shot paddle-detection filters (PIC-42).

Grounding DINO (EXPERIMENTS.md, 2026-08-20) reliably detects real paddles on
this project's footage, but also confuses static off-court objects for a
"tennis racket": IMG_7744's net-post roller, brickwall's balcony maintenance
pole, and an item near brickwall's front desk. None of them are inside the
court's actual play area, so the off-court gate already built and validated
for ball detections (court_wedge) filters them too, rather than needing a
bespoke per-camera exclusion.

court_wedge only solves the cases that are geometrically off to the side; it
can't touch a case like the front-desk item, which sits inside the court's
own reprojected image column. A compound prompt ("a person holding a
paddle") doesn't fix that either -- Grounding DINO grounds sub-phrases of a
query independently (documented "sub-sentence level text features"), so it
just re-detects the real bystander as "a person" rather than requiring the
two concepts jointly. The fusion has to happen in code: pair each paddle box
with the nearest player box (from src/players.py's existing detector) and
keep it only if that specific player is on-court -- a bystander holding
something, however real, is attached to a person who fails on_court."""

import math

import numpy as np

from src.calib import court_wedge
from src.players import foot_point, on_court, to_court


def filter_paddle_boxes(boxes, calib, area_max=15000.0, **wedge_kwargs):
    """boxes: iterable of (x1, y1, x2, y2) detections. Drops whole-body boxes
    (area >= area_max -- roughly an order of magnitude larger than a real
    paddle box) and any box whose center falls outside court_wedge's
    in-court gate. wedge_kwargs are passed through to court_wedge (e.g.
    margin_px). Returns the surviving boxes, in the given order."""
    in_court = court_wedge(calib, **wedge_kwargs)
    kept = []
    for box in boxes:
        x1, y1, x2, y2 = box
        if (x2 - x1) * (y2 - y1) >= area_max:
            continue
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        if not in_court(cx, cy):
            continue
        kept.append(box)
    return kept


def _point_to_box_dist(cx, cy, box):
    x1, y1, x2, y2 = box
    dx = max(x1 - cx, 0.0, cx - x2)
    dy = max(y1 - cy, 0.0, cy - y2)
    return math.hypot(dx, dy)


def filter_paddle_boxes_by_on_court_player(paddle_boxes, player_boxes, calib,
                                           max_dist_px=150.0, **on_court_kwargs):
    """Keep a paddle box only if the nearest player box is within
    max_dist_px AND that player is on-court -- src/players.py's own
    foot_point + on_court check, applied to the paired player, not the
    paddle. paddle_boxes/player_boxes: (x1, y1, x2, y2). Drops a paddle-scale
    detection with no player nearby, and a paddle attached to a real but
    off-court person (a bystander, staff at a front desk) alike. Returns the
    surviving paddle boxes, in the given order."""
    homography = np.array(calib["homography"], dtype=np.float64)
    kept = []
    for pbox in paddle_boxes:
        x1, y1, x2, y2 = pbox
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        nearest = min(player_boxes, key=lambda b: _point_to_box_dist(cx, cy, b),
                     default=None)
        if nearest is None or _point_to_box_dist(cx, cy, nearest) > max_dist_px:
            continue
        court_pt = to_court([foot_point(nearest)], homography)[0]
        if not on_court(court_pt, **on_court_kwargs):
            continue
        kept.append(pbox)
    return kept
