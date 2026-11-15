"""Association tracker for Test C (PIC-226/228). Experimental; NOT imported by the pipeline.

Same structure and gates as src/track.track_ball (max_jump, reset_after, cold start on the most
confident candidate, two-point re-acquisition confirmation). The only change is how the candidate
in a frame is CHOSEN:

    proximity = max(0, 1 - min(dist to last, dist to predicted) / max_jump)
    score     = w_c * confidence + w_d * proximity
    a candidate must still be within max_jump of the last OR the predicted position (the hit-reversal
    allowance track_ball has), so a 0.9 dot that teleports is rejected, and a 0.45 candidate sitting on
    the predicted path outscores a 0.9 dot 100 px away.

kalman=True: the predicted position comes from a constant-velocity Kalman filter (state x, y, vx, vy;
measurement noise R px^2, acceleration noise Q px^2/frame^2, both fixed here, not tuned) instead of
the last-two-points velocity. coast: extrapolate the velocity for at most this many frames of gap,
then predict the last position (the ball is assumed lost, not still flying straight).
"""
import numpy as np

R_PX2 = 9.0     # measurement variance
Q_ACC2 = 4.0    # acceleration variance per frame


class _KF:
    def __init__(self, x, y):
        self.s = np.array([x, y, 0.0, 0.0])
        self.P = np.diag([R_PX2, R_PX2, 400.0, 400.0])

    def predict(self, dt):
        F = np.array([[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1.0]])
        G = np.array([[0.5 * dt * dt, 0], [0, 0.5 * dt * dt], [dt, 0], [0, dt]])
        s = F @ self.s
        P = F @ self.P @ F.T + (G * Q_ACC2) @ G.T
        return s, P

    def update(self, dt, x, y):
        s, P = self.predict(dt)
        H = np.array([[1, 0, 0, 0], [0, 1, 0, 0.0]])
        S = H @ P @ H.T + np.eye(2) * R_PX2
        K = P @ H.T @ np.linalg.inv(S)
        self.s = s + K @ (np.array([x, y]) - H @ s)
        self.P = (np.eye(4) - K @ H) @ P


def track_associate(frames, max_jump, reset_after=15, w_c=0.5, w_d=0.5, kalman=False, coast=None,
                    return_x=False):
    out, xout = [], []
    last = last_idx = last_vel = None
    kf = None
    pending = None
    has_tracked = False
    gap = 0

    def predicted(i):
        elapsed = i - last_idx
        steps = elapsed if coast is None else min(elapsed, coast)
        if kalman and kf is not None:
            s, _ = kf.predict(steps)
            return (float(s[0]), float(s[1]))
        if last_vel is None:
            return last
        return (last[0] + last_vel[0] * steps, last[1] + last_vel[1] * steps)

    for i, cands in enumerate(frames):
        if gap >= reset_after:
            last = last_idx = last_vel = kf = pending = None
            gap = 0
        if not cands:
            out.append(None); xout.append(None); gap += 1
            continue
        if last is not None:
            pred = predicted(i)
            best = None
            for (x, y, c) in cands:
                d = min(((x - last[0]) ** 2 + (y - last[1]) ** 2) ** 0.5,
                        ((x - pred[0]) ** 2 + (y - pred[1]) ** 2) ** 0.5)
                if d > max_jump:
                    continue                      # imposter / teleport: never usable
                score = w_c * c + w_d * max(0.0, 1.0 - d / max_jump)
                if best is None or score > best[0]:
                    best = (score, x, y)
            if best is None:
                out.append(None); xout.append(None); gap += 1
                continue
            _, x, y = best
            elapsed = i - last_idx
            last_vel = ((x - last[0]) / elapsed, (y - last[1]) / elapsed)
            if kalman:
                kf.update(elapsed, x, y)
            last, last_idx, gap = (x, y), i, 0
            out.append(y); xout.append(x)
            continue
        if not has_tracked:
            x, y, _ = max(cands, key=lambda d: d[2])
            last, last_idx, has_tracked, gap = (x, y), i, True, 0
            if kalman:
                kf = _KF(x, y)
            out.append(y); xout.append(x)
            continue
        if pending is None:
            x, y, _ = max(cands, key=lambda d: d[2])
            pending = (x, y, i)
            out.append(None); xout.append(None); gap = 0
            continue
        px, py, pidx = pending
        x, y, _ = min(cands, key=lambda d: (d[0] - px) ** 2 + (d[1] - py) ** 2)
        if ((x - px) ** 2 + (y - py) ** 2) ** 0.5 <= max_jump:
            out[pidx] = py; xout[pidx] = px
            last, last_idx = (x, y), i
            last_vel = ((x - px) / (i - pidx), (y - py) / (i - pidx))
            if kalman:
                kf = _KF(px, py)
                kf.update(i - pidx, x, y)
            pending, gap = None, 0
            out.append(y); xout.append(x)
        else:
            x2, y2, _ = max(cands, key=lambda d: d[2])
            pending = (x2, y2, i)
            out.append(None); xout.append(None); gap = 0
    return (out, xout) if return_x else out
