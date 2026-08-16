"""Calibration helpers: interactive net-line picker and auto-detect fallback.

pick_net_y   — opens a window, user clicks on the net, returns image-y.
detect_net_y — headless Hough-based estimate (~50 px error on this court)."""

import cv2
import numpy as np


def pick_net_y(video_path):
    """Interactive net-line picker: show first frame, user clicks the net.

    Opens a resized preview window. A horizontal guide line follows the mouse
    so the user can aim precisely. Click once to confirm; the pipeline then
    uses that y-coordinate (scaled back to original resolution).
    """
    cap = cv2.VideoCapture(video_path)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"Cannot read first frame from {video_path}")

    orig_h, orig_w = frame.shape[:2]
    scale = min(1.0, 1280 / orig_w, 800 / orig_h)
    disp_w, disp_h = int(orig_w * scale), int(orig_h * scale)
    base = cv2.resize(frame, (disp_w, disp_h)) if scale < 1.0 else frame.copy()

    state = {"y": disp_h // 2, "done": False}

    def draw(y):
        img = base.copy()
        cv2.line(img, (0, y), (disp_w, y), (0, 255, 0), 2)
        cv2.putText(img, "Click on the NET LINE  (press Q to cancel)",
                    (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(img, f"y = {int(y / scale)}",
                    (16, 64), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        return img

    def on_mouse(event, x, y, flags, _param):
        if event == cv2.EVENT_MOUSEMOVE:
            state["y"] = y
        elif event == cv2.EVENT_LBUTTONDOWN:
            state["done"] = True

    cv2.namedWindow("pic-vision: pick net line", cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback("pic-vision: pick net line", on_mouse)

    WIN = "pic-vision: pick net line"
    while not state["done"]:
        cv2.imshow(WIN, draw(state["y"]))
        key = cv2.waitKey(16) & 0xFF
        if key == ord("q") or key == 27:  # Q or Esc to cancel
            cv2.destroyWindow(WIN)
            cv2.waitKey(1)
            raise RuntimeError("Net line selection cancelled.")

    # Show confirmed line briefly so user sees the selection, then close
    confirmed = base.copy()
    cv2.line(confirmed, (0, state["y"]), (disp_w, state["y"]), (0, 255, 0), 2)
    cv2.putText(confirmed, f"net_y = {int(state['y'] / scale)}  — running pipeline...",
                (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.imshow(WIN, confirmed)
    cv2.waitKey(1000)          # show for 1 second
    cv2.destroyWindow(WIN)
    cv2.waitKey(1)             # flush the close event on macOS
    return float(state["y"] / scale)


def court_x_range(calib, margin_px=50.0):
    """Image-x bounds of the tracked court, from calibrate.py's 12 clicked
    court points (calib['image_points']). A ball can arc slightly outside the
    painted lines (net play, out calls, follow-through) so margin_px pads both
    sides. Used to gate TrackNet detections to the tracked court, independent
    of track_ball's teleport-rejection/reset state — see src/tracknet.py for
    why gap-independence matters (a same-frame teleport check alone doesn't
    catch a different court's ball reappearing after real dead time)."""
    xs = [p[0] for p in calib["image_points"]]
    return (min(xs) - margin_px, max(xs) + margin_px)


def court_wedge(calib, margin_px=160.0, cap_court_heights=0.7, spread=0.5):
    """Perspective-aware replacement for court_x_range: the allowed image-x
    band as a function of image-y, following the court as it narrows with
    depth. Returns a function (x, y) -> bool.

    Above the far baseline the band is a bounded trapezoid, not an unbounded
    column: it widens by `spread` (as a fraction of the far-baseline width, so
    a high ball hit from near the camera stays inside — such a ball is high in
    the image but still horizontally wide, which a straight column wrongly
    treats as "must be far away"), and it is hard-capped `cap_court_heights`
    court-heights above the far baseline. Set cap_court_heights=None for no cap
    and spread=0 for the plain column.

    The cap earns its keep twice over (EXPERIMENTS.md 2026-08-16): it removes
    ceiling/light-fixture detections that are false rallies in their own right,
    *and* it raises recall, because those high spurious detections were
    hijacking track_ball mid-rally and costing real crossings. Measured on the
    33 IMG_7743 labels at min_crossings=6: precision 0.29 at recall 0.61,
    versus 0.10 at the same recall for the shipped flat x-interval.

    court_x_range takes one flat interval from the *near* baseline corners,
    which on a behind-baseline view span nearly the whole frame — on
    IMG_7743 it derived [4, 1915] on a 1920px frame and excluded nothing,
    leaving the adjacent court unfiltered (EXPERIMENTS.md 2026-08-16). The
    court is a trapezoid in the image, not a rectangle, so gating needs the
    x-extent *at each depth*.

    Above the far baseline the far baseline's own width is held, keeping the
    airspace over the court (lobs, high clears) while still excluding
    adjacent courts and wall clutter to the sides. Below the near baseline
    the near width is held likewise.
    """
    import numpy as np

    h_inv = np.linalg.inv(np.array(calib["homography"], dtype=np.float64))
    length_ft = calib.get("court_size_ft", [20.0, 44.0])[1]
    width_ft = calib.get("court_size_ft", [20.0, 44.0])[0]

    rows = []          # (image_y, x_left, x_right) sampled along the court
    for ft in [i * length_ft / 40.0 for i in range(41)]:
        pts = cv2.perspectiveTransform(
            np.array([[[0.0, ft], [width_ft, ft]]], dtype=np.float32), h_inv)
        (xl, yl), (xr, yr) = pts[0][0], pts[0][1]
        rows.append(((float(yl) + float(yr)) / 2.0, float(xl), float(xr)))
    rows.sort()        # ascending image-y: far baseline first, near baseline last
    far_y, far_l, far_r = rows[0]
    near_y = rows[-1][0]
    cap_y = (far_y - cap_court_heights * (near_y - far_y)
             if cap_court_heights is not None else None)

    def inside(x, y):
        if x is None or y is None:
            return False
        if cap_y is not None and y < cap_y:
            return False              # above the plausible ball ceiling
        if y <= far_y:
            span = (far_y - y) / max(1.0, far_y - cap_y) if cap_y is not None else 1.0
            grow = spread * (far_r - far_l) * min(1.0, span)
            xl, xr = far_l - grow, far_r + grow
        elif y >= rows[-1][0]:
            _, xl, xr = rows[-1]
        else:
            xl = xr = None
            for (y0, l0, r0), (y1, l1, r1) in zip(rows, rows[1:]):
                if y0 <= y <= y1:
                    t = (y - y0) / max(1e-9, y1 - y0)
                    xl, xr = l0 + t * (l1 - l0), r0 + t * (r1 - r0)
                    break
        return (xl - margin_px) <= x <= (xr + margin_px)

    return inside


def detect_net_y(video_path, n_frames=20):
    """Estimate net-line image-y from raw footage with no manual calibration.

    Samples n_frames spread across the first 20% of the video, computes a
    temporal median (erases moving players/ball), then finds the longest
    near-horizontal line in the central vertical band (25–75% of frame height).
    Raises RuntimeError if detection fails — fall back to --calib in that case.
    """
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))

    limit = max(1, int(total * 0.2))
    indices = np.linspace(0, limit - 1, min(n_frames, limit), dtype=int)

    frames = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = cap.read()
        if ok:
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    cap.release()

    if len(frames) < 3:
        raise RuntimeError(f"Too few readable frames in {video_path}")

    median = np.median(np.stack(frames), axis=0).astype(np.uint8)
    blurred = cv2.GaussianBlur(median, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 100)

    # In a behind-baseline view the net sits in the upper portion of the frame
    # (roughly 15–65% of height). Don't start at 25% — that clips the net.
    y_lo, y_hi = int(h * 0.15), int(h * 0.65)
    edges[:y_lo, :] = 0
    edges[y_hi:, :] = 0

    # minLineLength = 15% of width — net tape may not span full court after median
    lines = cv2.HoughLinesP(edges, rho=1, theta=np.pi / 180, threshold=50,
                             minLineLength=w * 0.15, maxLineGap=40)
    if lines is None:
        raise RuntimeError(
            "Auto net detection failed: no lines found. Provide --calib instead.")

    # Keep near-horizontal lines (slope < 8°).
    # reshape(-1, 4) normalises (N,1,4) and (N,4) from different OpenCV builds.
    # Also require each segment to reach into the LEFT half of the frame — this
    # rejects right-side-only features (wall netting, signage) that aren't the net.
    h_lines = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        if angle > 8 and angle < 172:
            continue
        if min(x1, x2) > w * 0.5:    # both endpoints in right half — not the net
            continue
        length = float(np.hypot(x2 - x1, y2 - y1))
        h_lines.append(((y1 + y2) / 2.0, length))

    if not h_lines:
        raise RuntimeError(
            "Auto net detection failed: no spanning horizontal lines. "
            "Provide --calib instead.")

    # In a behind-baseline view the net is the topmost prominent line that spans
    # the court width. Cluster by y (within 30 px) and return the topmost cluster
    # with accumulated length >= 10% of frame width.
    h_lines.sort(key=lambda t: t[0])
    clusters, cur = [], [h_lines[0]]
    for y, ln in h_lines[1:]:
        if y - cur[-1][0] <= 30:
            cur.append((y, ln))
        else:
            clusters.append(cur)
            cur = [(y, ln)]
    clusters.append(cur)

    for cluster in clusters:
        total_len = sum(ln for _, ln in cluster)
        if total_len >= w * 0.10:
            return float(sum(y * ln for y, ln in cluster) / total_len)

    raise RuntimeError(
        "Auto net detection failed: no substantial spanning line found. "
        "Provide --calib instead.")
