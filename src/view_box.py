"""A camera's view box: the part of the frame that is the camera's picture.

The operator draws it at calibration (docs/product/2026-11-21-view-box-design.md)
when a camera sits too high or too far back. The pod crops each job's video to
it once, in the convert step, and everything downstream sees an ordinary smaller
video with a calibration that matches it, so no offset is ever threaded through
the pipeline (ADR-064/069 were offset bugs).

The box is stored in the calibration as `view_box`, in calibration_resolution
pixels like image_points. The 12 court points stay full-frame, so a redrawn box
never needs a re-click; calib_for_box derives the boxed calibration from them.

The derived calibration is a pure shift in calibration space: its
calibration_resolution becomes the box's size, so every consumer that scales
calibration pixels to the video (court_crop, hit_finder, jev_sheet) keeps doing
exactly that, now against the cropped video.
"""
import copy

import numpy as np


def view_box(calib):
    """The calibration's box as (x0, y0, x1, y1) floats, or None for the whole frame.

    Raises ValueError for a box that is empty or reaches outside the frame.
    """
    raw = (calib or {}).get("view_box")
    if not raw:
        return None
    x0, y0, x1, y1 = (float(raw[k]) for k in ("x0", "y0", "x1", "y1"))
    w, h = calib.get("calibration_resolution") or (None, None)
    if not (x1 > x0 and y1 > y0):
        raise ValueError(f"view box {raw} is empty")
    if x0 < 0 or y0 < 0 or (w is not None and (x1 > w or y1 > h)):
        raise ValueError(f"view box {raw} reaches outside the {w}x{h} frame")
    return x0, y0, x1, y1


def calib_for_box(calib):
    """The calibration for a video cropped to its view box, or the calibration itself when it has none.

    image_points and net_image_points move by the box's origin; the homography
    (image -> court feet) is composed with the inverse shift, so every pixel maps
    to the same court spot as before; calibration_resolution becomes the box's
    size; view_box is dropped, since the video it describes is already cropped.
    Points outside the box keep their (negative or too-large) coordinates: the
    homography and the court gate are maths on them, not pixels to look up.
    """
    box = view_box(calib)
    if box is None:
        return calib
    x0, y0, x1, y1 = box
    out = copy.deepcopy(calib)
    out.pop("view_box", None)
    shift = np.array([x0, y0])
    for key in ("image_points", "net_image_points"):
        if out.get(key) is not None:
            out[key] = (np.asarray(out[key], dtype=float) - shift).tolist()
    if out.get("homography") is not None:
        # new pixel = old pixel - origin, so old = T_inv @ new and H_new = H @ T_inv.
        t_inv = np.array([[1.0, 0.0, x0], [0.0, 1.0, y0], [0.0, 0.0, 1.0]])
        out["homography"] = (np.asarray(out["homography"], dtype=float) @ t_inv).tolist()
    out["calibration_resolution"] = [int(round(x1 - x0)), int(round(y1 - y0))]
    return out


def video_crop(calib, video_wh):
    """ffmpeg's crop for the view box on a video of video_wh: (w, h, x, y) in video pixels, or None.

    The box is scaled from calibration_resolution to the video (the 720p
    sub-stream of a camera calibrated at 1080p, say). Width, height and origin
    are even, which the 4:2:0 encode needs, and stay inside the frame.
    """
    box = view_box(calib)
    if box is None:
        return None
    vw, vh = video_wh
    cw, ch = calib.get("calibration_resolution") or (vw, vh)
    sx, sy = vw / cw, vh / ch
    x0, y0, x1, y1 = box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy

    def even(v):
        return int(v) // 2 * 2

    x, y = even(x0), even(y0)
    w = min(even(x1 - x), even(vw - x))
    h = min(even(y1 - y), even(vh - y))
    return w, h, x, y
