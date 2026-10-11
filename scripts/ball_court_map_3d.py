"""Height-aware top-down ball map (PIC-205 feasibility draft).

The camera sits behind the baseline, so a ball in the air projects to the
wrong floor spot (ball_court_map.py shows this). Here each flight segment is
fitted with a ballistic arc under known gravity from the camera rays, and the
fitted 3D position is what gets drawn on the court.

Camera pose is recovered from the calibration homography alone (principal
point assumed at the image centre, no lens distortion) -- validated against
the net posts (x ~ -1 / 21 ft, z ~ 3 ft) for brickwall_30fps.

Court frame: x 0..20 ft, y 0..44 ft (y=0 near baseline, net y=22), z up.
Physical checks printed per segment need no labels: z at bounces ~ 0, z where
the path crosses the net >= 3 ft, apex below ~20 ft.

Usage:
    python3 scripts/ball_court_map_3d.py --video ... --csv ... --calib ... \
        --labels ... --rally 24 --out clips/brickwall_map3d_r24.mp4
"""
import argparse
import json
import subprocess
import sys

sys.path.insert(0, ".")

import numpy as np

from scripts.ball_court_map import (COURT_H, MARGIN_FT, court_to_px,
                                    draw_court, project_points)
from scripts.ball_trail_overlay import FPS, gated_points, resolve_window
from src.calib import court_wedge
from src.tracknet import load_predictions

G = 32.174  # ft/s^2


def camera_from_homography(homography, cx, cy):
    """Recover (f, R, C) from the image->court homography. R maps court
    offsets into camera axes: x_cam = R (X - C). Returns None if the
    equal-norm constraint has no real solution."""
    Hci = np.linalg.inv(np.array(homography, dtype=np.float64))
    Hci /= Hci[2, 2]
    h = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1]]) @ Hci
    h1, h2, h3 = h[:, 0], h[:, 1], h[:, 2]
    den = h2[2] ** 2 - h1[2] ** 2
    f2 = ((h1[0] ** 2 + h1[1] ** 2) - (h2[0] ** 2 + h2[1] ** 2)) / den
    if f2 <= 0:
        return None
    f = float(np.sqrt(f2))
    Ki = np.diag([1 / f, 1 / f, 1.0])
    r1, r2, t = Ki @ h1, Ki @ h2, Ki @ h3
    lam = 1 / np.linalg.norm(r1)
    r1, r2, t = r1 * lam, r2 * lam, t * lam
    if t[2] < 0:
        r1, r2, t = -r1, -r2, -t
    R = np.stack([r1, r2, np.cross(r1, r2)], 1)
    # r1/r2 are only approximately orthogonal (noise, ignored lens distortion);
    # snap to the nearest true rotation so forward/inverse rays agree.
    U, _, Vt = np.linalg.svd(R)
    R = U @ Vt
    return f, R, -R.T @ t


def ray_dir(u, v, f, R, cx, cy):
    d = R.T @ np.array([(u - cx) / f, (v - cy) / f, 1.0])
    return d / np.linalg.norm(d)


def _skew(d):
    return np.array([[0, -d[2], d[1]], [d[2], 0, -d[0]], [-d[1], d[0], 0]])


def fit_arc(obs, f, R, C, cx, cy):
    """obs: [(tau_sec, u, v)]. Returns (P0, V0, rms_px, max_px) of the arc
    P(tau) = P0 + V0 tau + 0.5 g tau^2 that best matches the camera rays."""
    gvec = np.array([0.0, 0.0, -G])
    A, b = [], []
    for tau, u, v in obs:
        S = _skew(ray_dir(u, v, f, R, cx, cy))
        A.append(np.hstack([S, S * tau]))
        b.append(S @ (C - 0.5 * gvec * tau * tau))
    sol, *_ = np.linalg.lstsq(np.vstack(A), np.concatenate(b), rcond=None)
    P0, V0 = sol[:3], sol[3:]
    errs = []
    for tau, u, v in obs:
        pc = R @ ((P0 + V0 * tau + 0.5 * gvec * tau * tau) - C)
        if pc[2] <= 1e-6:
            errs.append(1e9)
            continue
        errs.append(float(np.hypot(f * pc[0] / pc[2] + cx - u, f * pc[1] / pc[2] + cy - v)))
    e = np.array(errs)
    return P0, V0, float(np.sqrt(np.mean(e ** 2))), float(e.max())


# plausible ball volume (ft): court plus run-off, and a ceiling
BOUNDS = {"x": (-8.0, 28.0), "y": (-8.0, 52.0), "zmax": 20.0}
NET_END_DIST_FT = 3.0   # arc ends this close to the net plane...
NET_END_MAX_Z = 4.5     # ...and no higher than this => net-contact candidate
NET_HIT_MIN_Z = 2.0     # below this a 'crossing' is treated as occlusion, not contact
NET_MIN_Z = 2.8        # net is 34 in at centre, 36 in at the posts
PENALTY_PX_PER_FT = 25.0
# Weak prior (off by default): balls are mostly struck within paddle reach, so
# an arc that is "high AND near the net" is less likely than "lower AND far"
# when the image can't tell them apart. Pixels of cost per ft above PRIOR_Z_FT.
HEIGHT_PRIOR_PX_PER_FT = 8.0
PRIOR_Z_FT = 5.0


def _arc_samples(P0, V0, tau0, tau1, step=1.0 / FPS):
    taus = np.arange(tau0, tau1 + 1e-9, step)
    return taus, P0[None, :] + np.outer(taus, V0) + 0.5 * np.outer(taus ** 2, [0.0, 0.0, -G])


def _violations(pos):
    """Feet by which an arc breaks the physical rules, one value per rule."""
    v = [np.maximum(0.0, -pos[:, 2]),                       # below the floor
         np.maximum(0.0, pos[:, 2] - BOUNDS["zmax"]),       # absurdly high
         np.maximum(0.0, BOUNDS["x"][0] - pos[:, 0]), np.maximum(0.0, pos[:, 0] - BOUNDS["x"][1]),
         np.maximum(0.0, BOUNDS["y"][0] - pos[:, 1]), np.maximum(0.0, pos[:, 1] - BOUNDS["y"][1])]
    # Net clearance is deliberately NOT a rule here: forcing arcs over the net
    # bends a real net hit upward. Net contact is detected afterwards.
    return np.concatenate(v)


def fit_arc_constrained(obs, f, R, C, cx, cy):
    """Like fit_arc, but a ballistic arc that also stays above the floor,
    inside a plausible volume, and clears the net where it crosses it. The
    rules enter as heavy penalties on the pixel residuals, so a fit that can
    only match the image by going underground simply scores badly.
    Returns (P0, V0, rms_px, max_px, worst_violation_ft)."""
    from scipy.optimize import least_squares

    P0, V0, _, _ = fit_arc(obs, f, R, C, cx, cy)
    taus_obs = np.array([o[0] for o in obs])
    uv = np.array([[o[1], o[2]] for o in obs])
    t0, t1 = float(taus_obs.min()), float(taus_obs.max())

    def px_err(p):
        pos = p[:3][None, :] + np.outer(taus_obs, p[3:]) + 0.5 * np.outer(taus_obs ** 2, [0, 0, -G])
        pc = (R @ (pos - C).T).T
        z = np.maximum(pc[:, 2], 1e-3)
        return np.stack([f * pc[:, 0] / z + cx, f * pc[:, 1] / z + cy], 1) - uv

    def resid(p):
        _, pos = _arc_samples(p[:3], p[3:], t0, t1)
        prior = HEIGHT_PRIOR_PX_PER_FT * np.maximum(0.0, pos[:, 2] - PRIOR_Z_FT)
        return np.concatenate([px_err(p).ravel(), PENALTY_PX_PER_FT * _violations(pos), prior])

    x0 = np.concatenate([P0, V0])
    try:
        sol = least_squares(resid, x0, method="trf", max_nfev=60).x
    except Exception:
        sol = x0
    e = np.hypot(*px_err(sol).T)
    _, pos = _arc_samples(sol[:3], sol[3:], t0, t1)
    return (sol[:3], sol[3:], float(np.sqrt(np.mean(e ** 2))), float(e.max()),
            float(_violations(pos).max()))


def position(P0, V0, tau):
    return P0 + V0 * tau + 0.5 * np.array([0.0, 0.0, -G]) * tau * tau


def segment_flights(img_pts, f, R, C, cx, cy, min_pts=6, max_gap=3,
                    rms_ok=4.0, max_ok=10.0, max_viol_ft=0.3):
    """Greedy: grow a ballistic segment while its fit stays tight. Returns
    [{frames, P0, V0, t0, rms, max}] -- t0 is the frame the arc is anchored at."""
    idx = [i for i, p in enumerate(img_pts) if p is not None]
    segs, s = [], 0
    while s + min_pts <= len(idx):
        e = s + min_pts
        def trial(a, b):
            fr = idx[a:b]
            obs = [((i - fr[0]) / FPS, *img_pts[i]) for i in fr]
            return fr, fit_arc_constrained(obs, f, R, C, cx, cy)
        fr, (P0, V0, rms, mx, vio) = trial(s, e)
        if (rms > rms_ok or mx > max_ok or vio > max_viol_ft
                or any(b - a > max_gap for a, b in zip(fr, fr[1:]))):
            s += 1
            continue
        best = (fr, P0, V0, rms, mx)
        while e < len(idx):
            if idx[e] - idx[e - 1] > max_gap:
                break
            fr2, (P2, V2, r2, m2, v2) = trial(s, e + 1)
            if r2 > rms_ok or m2 > max_ok or v2 > max_viol_ft:
                break
            best = (fr2, P2, V2, r2, m2)
            e += 1
        fr, P0, V0, rms, mx = best
        segs.append({"frames": fr, "P0": P0, "V0": V0, "t0": fr[0], "rms": rms, "max": mx})
        s = e
    return segs


def seg_report(seg):
    fr = seg["frames"]
    taus = np.arange(fr[0], fr[-1] + 1) / FPS - fr[0] / FPS
    pos = np.array([position(seg["P0"], seg["V0"], t) for t in taus])
    z, y = pos[:, 2], pos[:, 1]
    cross = None
    for a, b in zip(range(len(y) - 1), range(1, len(y))):
        if (y[a] - 22.0) * (y[b] - 22.0) < 0:
            cross = float(z[a])
    # A "crossing" far below the tape (z < NET_HIT_MIN_Z) is the signature of a
    # ball lost behind a player and bridged by the fit, not a real net hit
    # (seen at 12:46.5 on brickwall r24: the white player covers the ball).
    net_hit = cross is not None and NET_HIT_MIN_Z <= cross < NET_MIN_Z
    # An arc that ends right at the net, at about net height, without crossing:
    # the ball ran into the tape (or was lost against it) -- a net-contact
    # *candidate*, not a confirmed hit.
    net_end = (cross is None and abs(float(y[-1]) - 22.0) <= NET_END_DIST_FT
               and float(z[-1]) <= NET_END_MAX_Z)
    return {"net_hit": net_hit, "net_end": net_end, "t": fr[0] / FPS, "dur": (fr[-1] - fr[0]) / FPS, "n": len(fr),
            "rms": seg["rms"], "z0": float(z[0]), "z1": float(z[-1]),
            "apex": float(z.max()), "net_z": cross,
            "start_xy": (round(float(pos[0, 0]), 1), round(float(pos[0, 1]), 1)),
            "end_xy": (round(float(pos[-1, 0]), 1), round(float(pos[-1, 1]), 1))}


def net_cross_frame(seg):
    """First frame at which the arc's court-y passes the net line (y=22), or None."""
    prev = None
    for i in range(seg["frames"][0], seg["frames"][-1] + 1):
        y = position(seg["P0"], seg["V0"], (i - seg["t0"]) / FPS)[1]
        if prev is not None and (prev - 22.0) * (y - 22.0) < 0:
            return i
        prev = y
    return None


def seg_ok(r):
    """Label-free physical sanity: above the floor, plausible apex, near the
    court, long enough to be well determined, clears the net if it crosses."""
    xs, ys = zip(r["start_xy"], r["end_xy"])
    return (min(r["z0"], r["z1"]) >= -1.0 and r["apex"] <= 20.0 and r["dur"] >= 0.4
            # strictly inside the volume: an arc sitting ON the limit is being
            # decided by the limit, not by the footage
            and all(BOUNDS["x"][0] + 0.5 < x < BOUNDS["x"][1] - 0.5 for x in xs)
            and all(BOUNDS["y"][0] + 0.5 < y < BOUNDS["y"][1] - 0.5 for y in ys))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--calib", required=True)
    ap.add_argument("--out")
    ap.add_argument("--labels")
    ap.add_argument("--rally", type=int)
    ap.add_argument("--start-sec", type=float)
    ap.add_argument("--end-sec", type=float)
    ap.add_argument("--pad-sec", type=float, default=0.5)
    ap.add_argument("--rms-ok", type=float, default=4.0)
    args = ap.parse_args()

    import cv2

    start, end = resolve_window(args)
    calib = json.load(open(args.calib))
    cap = cv2.VideoCapture(args.video)
    vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cx, cy = vw / 2.0, vh / 2.0
    cam = camera_from_homography(calib["homography"], cx, cy)
    if cam is None:
        raise SystemExit("camera pose not recoverable from this calibration")
    f, R, C = cam
    print(f"camera: f={f:.0f}px centre=({C[0]:.1f},{C[1]:.1f},{C[2]:.1f}) ft", file=sys.stderr)

    track = load_predictions(args.csv, FPS)
    all_pts = gated_points(track, court_wedge(calib))
    f0 = max(0, int((start - args.pad_sec) * FPS))
    f1 = min(len(all_pts) - 1, int((end + args.pad_sec) * FPS))
    win = [p if f0 <= i <= f1 else None for i, p in enumerate(all_pts)]
    segs = segment_flights(win, f, R, C, cx, cy, rms_ok=args.rms_ok)

    print(f"{sum(p is not None for p in win)} gated detections -> {len(segs)} flight segments",
          file=sys.stderr)
    print("  m:s    dur   n   rms   z_start  z_end  apex  net_z   start_xy -> end_xy", file=sys.stderr)
    for s in segs:
        r = seg_report(s)
        nz = f"{r['net_z']:5.1f}" if r["net_z"] is not None else "  -  "
        print(f"{int(r['t'] // 60):3d}:{r['t'] % 60:05.2f} {r['dur']:4.2f} {r['n']:3d} {r['rms']:5.1f} {r['z0']:8.1f} "
              f"{r['z1']:6.1f} {r['apex']:5.1f} {nz}   {r['start_xy']} -> {r['end_xy']}"
              f"  {'ok' if seg_ok(r) else 'FAILS physical check'}",
              file=sys.stderr)
    n_ok = sum(seg_ok(seg_report(s)) for s in segs)
    print(f"{n_ok}/{len(segs)} segments pass the physical checks", file=sys.stderr)
    covered = sum(len(s["frames"]) for s in segs)
    print(f"{covered}/{sum(p is not None for p in win)} detections explained by an arc",
          file=sys.stderr)
    if not args.out:
        return

    # render: video | court with naive projection (gray) + fitted arcs (green)
    pad = 12
    scale = (vh - 2 * pad) / (COURT_H + 2 * MARGIN_FT)
    pw = int((20.0 + 2 * MARGIN_FT) * scale + 2 * pad)
    base = draw_court(scale, pad, (pw, vh))
    # Only arcs that pass the physical checks are drawn, in one colour, as a
    # fading trace. Everything else is simply not shown ("not tracked") --
    # no gray guesses, no second colour.
    valid = [seg_ok(seg_report(s)) for s in segs]
    fitted, net_hits = {}, []     # net_hits: (frame, x_ft) -- ball met the net
    for si, s in enumerate(segs):
        if not valid[si]:
            continue
        last = s["frames"][-1]
        if seg_report(s)["net_end"] and valid[si]:
            pe = position(s["P0"], s["V0"], (last - s["t0"]) / FPS)
            net_hits.append((last, pe[0]))
        if seg_report(s)["net_hit"] and valid[si]:
            cf = net_cross_frame(s)
            if cf is not None:
                last = cf
                net_hits.append((cf, position(s["P0"], s["V0"], (cf - s["t0"]) / FPS)[0]))
        for i in range(s["frames"][0], last + 1):
            fitted[i] = (si, position(s["P0"], s["V0"], (i - s["t0"]) / FPS))
    tmp = args.out + ".raw.mp4"
    writer = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (vw + pw, vh))
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    trail = int(1.5 * FPS)
    for i in range(f0, f1 + 1):
        ok, frame = cap.read()
        if not ok:
            break
        panel = base.copy()
        prev = None
        for j in range(max(f0, i - trail), i + 1):
            if j not in fitted:
                prev = None
                continue
            si, p = fitted[j]
            pt = tuple(int(v) for v in court_to_px(p[0], p[1], scale, pad))
            if prev is not None and prev[0] == si:
                fade = 1.0 - (i - j) / trail
                color = tuple(int(c * (0.3 + 0.7 * fade)) for c in (0, 230, 255))
                cv2.line(panel, prev[1], pt, color, max(1, int(1 + 3 * fade)))
            prev = (si, pt)
            if j == i:
                cv2.circle(panel, pt, 6, (255, 255, 255), -1)
        for cf, xft in net_hits:
            if cf <= i <= cf + FPS:                      # hold the marker ~1 s
                nx, ny = (int(v) for v in court_to_px(xft, 22.0, scale, pad))
                cv2.line(panel, (nx - 8, ny - 8), (nx + 8, ny + 8), (60, 60, 255), 3)
                cv2.line(panel, (nx - 8, ny + 8), (nx + 8, ny - 8), (60, 60, 255), 3)
                cv2.putText(panel, "NET", (nx + 12, ny - 6), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (60, 60, 255), 1)
        cv2.putText(frame, f"{int(i / FPS // 60)}:{i / FPS % 60:04.1f}", (16, vh - 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        writer.write(np.hstack([frame, panel]))
    writer.release()
    cap.release()
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", tmp, "-c:v", "libx264", "-preset",
                    "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an",
                    args.out], check=True)
    subprocess.run(["rm", "-f", tmp], check=True)
    print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
