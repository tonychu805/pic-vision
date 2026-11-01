"""Where to crop each frame before the ball model sees it.

The ball model takes a fixed 512x288 picture, so a ball a few pixels wide in a
1080p frame shrinks to under 3 pixels when the whole frame is squeezed in.
Cropping to the court and the airspace above it first cuts that shrink from
about 3.75x to about 2.2x. On PDSC Court 3 this is what turned the far-side
ball from mostly lost into mostly found (EXPERIMENTS.md 2026-11-01: with the
fine-tuned weights, 14 of 22 court-side and 7 of 12 wall-side marked balls on
the crop against 3 and 3 on the whole frame).

The box comes from the calibration's 12 clicked court points, so it needs no
per-venue setting: the court's corners, a small margin, and `airspace` court
heights above the far baseline. It is NOT the bounding box of the court gate
(src/calib.py's court_wedge), and does not contain all of it: on Court 3 the
gate reaches y 280-1076 on a 1080p frame (down to the frame's bottom, past the
near baseline, where players serve from) and this box y 218-897. The gate's own
bounding box was tried and did worse on the marked balls (9 of 22 court-side
against 13), because the larger box shrinks the ball more (2.76x against 2.36x).
Balls behind the near baseline, below this box, were not part of that test.

Coordinates are the trap here (ADR-064/069 were coordinate-offset bugs): a
detection lands on the 512x288 grid of the CROP, and every consumer wants it
in the calibration's own pixel space. grid_to_calibration is the one place
that conversion lives, and its tests round-trip it.
"""
import numpy as np


def court_crop_box(calib, video_shape, margin=0.04, airspace=0.7, aspect=16 / 9):
    """(x0, y0, x1, y1): integer video pixels, inside the frame, `aspect` wide.

    The court's clicked corners and the airspace over it, padded by `margin`
    of the court's width, then widened or heightened to `aspect` and shifted
    back inside the frame. A frame smaller than the box gives the whole frame.
    """
    vh, vw = video_shape[:2]
    cal_res = calib.get("calibration_resolution")
    cw, ch = cal_res if cal_res else (vw, vh)
    pts = np.array(calib["image_points"], dtype=float) * [vw / cw, vh / ch]
    x0, x1 = pts[:, 0].min(), pts[:, 0].max()
    far_y, near_y = pts[:, 1].min(), pts[:, 1].max()
    pad = margin * (x1 - x0)
    x0, x1 = x0 - pad, x1 + pad
    y0, y1 = far_y - airspace * (near_y - far_y) - pad, near_y + pad
    w, h = x1 - x0, y1 - y0
    if w / h < aspect:
        grow = h * aspect - w
        x0, x1 = x0 - grow / 2, x1 + grow / 2
    else:
        grow = w / aspect - h
        y0, y1 = y0 - grow / 2, y1 + grow / 2
    w, h = x1 - x0, y1 - y0
    if w >= vw or h >= vh:
        return 0, 0, int(vw), int(vh)
    x0 = min(max(x0, 0.0), vw - w)
    y0 = min(max(y0, 0.0), vh - h)
    return int(round(x0)), int(round(y0)), int(round(x0 + w)), int(round(y0 + h))


def grid_to_calibration(gx, gy, box, grid_wh, video_shape, cal_res):
    """A point on the model's grid (of the crop) -> the calibration's pixels.

    box: court_crop_box's result, or None for the whole frame. grid_wh: the
    model's (width, height). cal_res: the calibration's (width, height), or
    None when the calibration is in this video's own pixels.
    """
    vh, vw = video_shape[:2]
    gw, gh = grid_wh
    x0, y0, x1, y1 = box if box else (0, 0, vw, vh)
    cw, ch = cal_res if cal_res else (vw, vh)
    return ((x0 + gx * (x1 - x0) / gw) * cw / vw,
            (y0 + gy * (y1 - y0) / gh) * ch / vh)
