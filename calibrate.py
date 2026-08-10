#!/usr/bin/env python3
"""
Court calibration — click 12 court intersections + 2 net-tape points once per
camera mount. The net points mark the net line directly (the ball crosses over
the tape), which is more reliable than deriving it from the homography.

Usage:
    python calibrate.py session.mp4 --at 300 --out court_calibration.json

Controls:
    left click   place the next point (12 court points, then 2 net-tape points)
    u            undo last point
    r            reset all
    ENTER        save (once all 12 court + 2 net placed)
    q            quit without saving
"""
import argparse
import itertools
import json
import sys

import cv2
import numpy as np

# Pickleball court, feet. Origin = near-left corner. Net at y=22.
# Non-volley zone lines 7 ft from the net -> y=15 (near) and y=29 (far).
POINTS = [
    ("near-left corner (baseline x left sideline)", (0.0, 0.0)),
    ("near-right corner", (20.0, 0.0)),
    ("far-left corner", (0.0, 44.0)),
    ("far-right corner", (20.0, 44.0)),
    ("near NVZ line x left sideline", (0.0, 15.0)),
    ("near NVZ line x right sideline", (20.0, 15.0)),
    ("far NVZ line x left sideline", (0.0, 29.0)),
    ("far NVZ line x right sideline", (20.0, 29.0)),
    ("near centerline x baseline", (10.0, 0.0)),
    ("far centerline x baseline", (10.0, 44.0)),
    ("near centerline x NVZ line", (10.0, 15.0)),
    ("far centerline x NVZ line", (10.0, 29.0)),
]

# After the 12 court points, mark the net line directly (the ball crosses over
# the net tape, so mark the TOP of the net, not its base).
NET_PROMPTS = ["net tape - LEFT end (top of net)", "net tape - RIGHT end (top of net)"]
TOTAL = len(POINTS) + len(NET_PROMPTS)

clicked: list[tuple[int, int]] = []


def on_mouse(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN and len(clicked) < TOTAL:
        clicked.append((x, y))


def draw(frame):
    img = frame.copy()
    for i, (px, py) in enumerate(clicked):
        net = i >= len(POINTS)
        col = (0, 0, 255) if net else (0, 255, 0)          # net points in red
        label = "N%d" % (i - len(POINTS) + 1) if net else str(i + 1)
        cv2.circle(img, (px, py), 6, col, -1)
        cv2.putText(img, label, (px + 9, py - 9),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
    if len(clicked) == TOTAL:                              # draw the marked net line
        (x1, y1), (x2, y2) = clicked[len(POINTS):TOTAL]
        cv2.line(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
    n = len(clicked)
    if n < len(POINTS):
        msg = f"{n + 1}/12 court  ->  {POINTS[n][0]}"
    elif n < TOTAL:
        msg = f"NET {n - len(POINTS) + 1}/2  ->  {NET_PROMPTS[n - len(POINTS)]}"
    else:
        msg = "ALL PLACED (12 court + 2 net) - press ENTER to save"
    cv2.rectangle(img, (0, 0), (img.shape[1], 40), (0, 0, 0), -1)
    cv2.putText(img, msg, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                (255, 255, 255), 2)
    return img


def compute_calibration(image_points, point_defs=POINTS):
    """Fit the pixel->court homography for image points given IN court-point
    order (image_points[k] is the click for point_defs[k]). Returns the
    homography, reprojection RMSE (ft), and per-point errors."""
    src = np.array(image_points, dtype=np.float32)
    dst = np.array([c for _, c in point_defs], dtype=np.float32)
    H, _ = cv2.findHomography(src, dst, method=cv2.RANSAC,
                              ransacReprojThreshold=5.0)
    if H is None:
        raise ValueError("homography failed")
    proj = cv2.perspectiveTransform(src.reshape(-1, 1, 2), H).reshape(-1, 2)
    err_ft = np.linalg.norm(proj - dst, axis=1)
    rmse_ft = float(np.sqrt((err_ft ** 2).mean()))
    return {
        "image_points": [[float(x), float(y)] for x, y in image_points],
        "court_points_ft": [list(c) for _, c in point_defs],
        "point_names": [n for n, _ in point_defs],
        "homography": H.tolist(),
        "reprojection_rmse_ft": rmse_ft,
        "per_point_error_ft": [float(e) for e in err_ft],
    }


# The four court corners (NL, NR, FR, FL) in cyclic order; a click subset is
# fitted to them to seed a candidate homography.
_CORNER_CYCLE = [0, 1, 3, 2]


def _mirror_perm(reflect):
    """Index permutation of POINTS under a court reflection (reflect maps a
    court (x_ft, y_ft) to its mirrored position)."""
    coords = [c for _, c in POINTS]
    perm = []
    for x, y in coords:
        tx, ty = reflect(x, y)
        j = min(range(len(coords)),
                key=lambda i: (coords[i][0] - tx) ** 2 + (coords[i][1] - ty) ** 2)
        perm.append(j)
    return perm


_NEARFAR_PERM = _mirror_perm(lambda x, y: (x, 44.0 - y))    # reflect across the net
_LEFTRIGHT_PERM = _mirror_perm(lambda x, y: (20.0 - x, y))  # reflect across centerline


def _canonical_orientation(ordered):
    """A pickleball court is symmetric across the net and the centerline, so a
    residual-minimizing assignment can come out flipped near<->far or
    left<->right. Re-orient using the behind-baseline framing: the near baseline
    sits lower in the image (larger y) than the far baseline, and the near-left
    corner is left of the near-right corner."""
    def flip(o, perm):
        return [o[perm[k]] for k in range(len(perm))]
    if (ordered[0][1] + ordered[1][1]) < (ordered[2][1] + ordered[3][1]):
        ordered = flip(ordered, _NEARFAR_PERM)   # near baseline was above far
    if ordered[0][0] > ordered[1][0]:
        ordered = flip(ordered, _LEFTRIGHT_PERM)  # near-left was right of near-right
    return ordered


def _assign_nearest(proj, court):
    """Greedy one-to-one nearest assignment of projected clicks to court points.
    Returns (rmse_ft, {click_idx: court_idx})."""
    dist = np.linalg.norm(proj[:, None, :] - court[None, :, :], axis=2)
    pairs = np.dstack(np.unravel_index(np.argsort(dist, axis=None), dist.shape))[0]
    used_p, used_c, assign, sq = set(), set(), {}, []
    for i, j in pairs:
        i, j = int(i), int(j)
        if i in used_p or j in used_c:
            continue
        assign[i] = j
        used_p.add(i)
        used_c.add(j)
        sq.append(dist[i, j] ** 2)
        if len(assign) == len(court):
            break
    return float(np.sqrt(np.mean(sq))), assign


def solve_assignment(image_points, point_defs=POINTS):
    """Figure out which court landmark each clicked point is, regardless of the
    order they were clicked. The four court corners are the outermost points, so
    the true corners sit on the convex hull of the clicks; every choice of 4 hull
    points, in every ordering, seeds a candidate homography. The rest are
    projected and matched one-to-one to the court points, and the assignment with
    the lowest reprojection error wins. Falls back to all points if the hull is
    thin.

    Returns (ordered_points, rmse_ft) where ordered_points[k] is the click that
    matches point_defs[k]."""
    clicks = np.array(image_points, dtype=np.float32)
    court = np.array([c for _, c in point_defs], dtype=np.float32)
    court_cyc = court[_CORNER_CYCLE]

    hull = cv2.convexHull(clicks, returnPoints=False).flatten().tolist()
    candidate_sets = ([hull] if len(hull) >= 4 else []) + [list(range(len(clicks)))]

    best_rmse, best_assign = float("inf"), None
    for cand in candidate_sets:
        for four in itertools.combinations(cand, 4):
            for order in itertools.permutations(range(4)):
                src = np.array([clicks[four[k]] for k in order], dtype=np.float32)
                H, _ = cv2.findHomography(src, court_cyc)
                if H is None:
                    continue
                proj = cv2.perspectiveTransform(clicks.reshape(-1, 1, 2), H).reshape(-1, 2)
                rmse, assign = _assign_nearest(proj, court)
                if rmse < best_rmse:
                    best_rmse, best_assign = rmse, assign
        if best_rmse <= 1.0:
            break  # hull already gave a clean fit; skip the exhaustive fallback

    click_for_court = {cj: pi for pi, cj in best_assign.items()}
    ordered = [image_points[click_for_court[k]] for k in range(len(point_defs))]
    if point_defs is POINTS:
        ordered = _canonical_orientation(ordered)
    return ordered, best_rmse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--at", type=float, default=60.0,
                    help="seconds into the video to grab the frame")
    ap.add_argument("--out", default="court_calibration.json")
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.video)
    cap.set(cv2.CAP_PROP_POS_MSEC, args.at * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        sys.exit(f"could not read a frame at {args.at}s")

    cv2.namedWindow("calibrate", cv2.WINDOW_NORMAL)
    cv2.setMouseCallback("calibrate", on_mouse)

    while True:
        cv2.imshow("calibrate", draw(frame))
        k = cv2.waitKey(20) & 0xFF
        if k == ord("q"):
            sys.exit("aborted")
        if k == ord("u") and clicked:
            clicked.pop()
        if k == ord("r"):
            clicked.clear()
        if k in (13, 10) and len(clicked) == TOTAL:
            break

    cv2.destroyAllWindows()

    # First 12 clicks are court points (order auto-detected); last 2 mark the net.
    court_clicks = clicked[:len(POINTS)]
    net_clicks = clicked[len(POINTS):TOTAL]
    ordered, _ = solve_assignment(court_clicks)
    result = compute_calibration(ordered)
    rmse_ft = result["reprojection_rmse_ft"]

    out = {
        "video": args.video,
        "frame_at_sec": args.at,
        **result,
        "net_image_points": [[float(x), float(y)] for x, y in net_clicks],
        "court_size_ft": [20.0, 44.0],
        "net_y_ft": 22.0,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)

    print(f"saved {args.out}")
    print(f"reprojection RMSE: {rmse_ft:.3f} ft  (click order auto-detected)")
    if rmse_ft > 0.5:
        print("WARNING: RMSE > 0.5 ft - re-check that all 12 court intersections were clicked")
    err_ft = result["per_point_error_ft"]
    worst = int(np.argmax(err_ft))
    print(f"worst point: #{worst + 1} {POINTS[worst][0]} ({err_ft[worst]:.3f} ft)")


if __name__ == "__main__":
    main()
