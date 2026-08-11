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
