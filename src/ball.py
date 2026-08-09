"""v1 rally signal: ball net-crossing counter (ADR-039, ADR-028).

The ball flies above the ground plane, so the court homography mis-locates it
(parallax). Instead we work in image space: in a behind-baseline view the ball's
vertical pixel position (image-y) tells us which side of the net it's on — near
= bottom (large y), far = top (small y). A net-crossing is the ball's image-y
crossing the net line, with a hysteresis band so jitter near the net doesn't
inflate the count. Missing/ambiguous frames are skipped.

Ball detection (YOLO 'sports ball' + false-positive filters) and the net line
from calibration are separate slices; this is the testable core."""


def count_crossings(ball_ys, net_y, band=0.0):
    """Count net-crossings from a ball's per-frame image-y positions.

    ball_ys: list of image-y (pixels) or None where the ball wasn't detected.
    A frame's side is 'near' if y > net_y + band, 'far' if y < net_y - band, and
    ambiguous (skipped) within the band. A crossing is counted each time the
    definite side flips."""
    crossings = 0
    last_side = None
    for y in ball_ys:
        if y is None:
            continue
        if y > net_y + band:
            side = "near"
        elif y < net_y - band:
            side = "far"
        else:
            continue  # inside the band: too close to the net to call a side
        if last_side is not None and side != last_side:
            crossings += 1
        last_side = side
    return crossings
