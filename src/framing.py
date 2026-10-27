"""Where a 9:16 window sits over a wide rally clip, frame by frame (vertical reels, 2026-10-27).

The 09-28 prototype (scripts/follow_crop_prototype.py) followed the ball
alone, and in doubles that cut out the player about to hit. The pod now also
has every player's box through each rally (src/pose.py, for badges), so the
window keeps the ball in view and, within that, shows as many players as it
can -- the one nearest the ball (hitting, or about to) counting double. Where a badge names a moment
(Hardest Swing, Killer Shot, First Strike carry the shot's time and the
hitter's court position), the window holds on that hitter around it.

The path is resolution-independent: window centres as a fraction of the
frame width, sampled at PATH_FPS. It is computed on the pod (which has the
ball track and poses) and travels with the clip, so whoever holds the final
clip -- the 720p cut, or the desktop's high-res swap later -- can crop it
without re-running detection.
"""
import numpy as np

PATH_FPS = 5.0          # the path is smooth (SMOOTH_SEC), so 5 points a second
                        # interpolate it to within a pixel or two
SMOOTH_SEC = 0.5        # Gaussian sigma: the window glides, not chases bounces
MAX_PAN = 0.6           # frame widths per second
BALL_MARGIN = 0.1       # the ball stays at least this far (in window widths) inside the edge
FOCUS_SEC = 0.6         # hold on a badge's hitter this long either side of the shot
SERVE_HOLD_SEC = 0.3    # stay on the server this long past the serve's net crossing:
                        # smoothing starts the glide early, and without it the
                        # server left the window before contact (2026-10-27)


def crop_width(W, H):
    """Width in pixels of a full-height 9:16 window (even)."""
    return min(W, int(round(H * 9 / 16)) // 2 * 2)


def _centre_x(box):
    return (box[0] + box[2]) / 2


def _fill(vals, default):
    """None gaps joined by straight lines, held at both ends; all None -> default."""
    seen = [i for i, v in enumerate(vals) if v is not None]
    if not seen:
        return np.full(len(vals), float(default))
    return np.interp(np.arange(len(vals)), seen, [vals[i] for i in seen])


def _gap(box, x):
    return 0.0 if box[0] <= x <= box[2] else min(abs(box[0] - x), abs(box[2] - x))


def _most_players(ball, boxes, W, crop_w, ball_margin=BALL_MARGIN, steps=41):
    """Window centre that keeps the ball in view (ball_margin in from the edge)
    and shows the most of the players: each counts by the share of its width
    inside the window, the one nearest the ball (hitting, or about to) double.
    Ties go to the centre nearest the ball."""
    lo = max(crop_w / 2, ball - crop_w / 2 + ball_margin * crop_w)
    hi = min(W - crop_w / 2, ball + crop_w / 2 - ball_margin * crop_w)
    if lo >= hi:
        return ball
    near = min(range(len(boxes)), key=lambda k: _gap(boxes[k], ball))
    best = None
    for c in np.linspace(lo, hi, steps):
        a, b = c - crop_w / 2, c + crop_w / 2
        s = sum((2.0 if k == near else 1.0) * max(0.0, min(b, bx[2]) - max(a, bx[0])) / max(bx[2] - bx[0], 1.0)
                for k, bx in enumerate(boxes))
        key = (round(s, 3), -abs(c - ball))
        if best is None or key > best[0]:
            best = (key, c)
    return best[1]


def _server_box(boxes_or_people, court):
    """The player nearest the server's court position (feet), or None."""
    ps = [p for p in boxes_or_people if isinstance(p, dict) and p.get("court")]
    if not ps:
        return None
    return min(ps, key=lambda p: (p["court"][0] - court[0]) ** 2 + (p["court"][1] - court[1]) ** 2)["box"]


def targets(ball_xs, people, W, crop_w, use_players=True, focus=None, fps=30.0, serve=None):
    """Desired window centre per frame, in pixels (before smoothing).

    ball_xs: tracked ball x per frame, None when not seen. people: per frame a
    list of on-court players (dicts with "box", or plain boxes), or None when
    that frame wasn't posed. focus: [(t_sec, court_y)] -- moments to hold on
    the player whose feet are nearest court_y, t relative to the first frame;
    needs dicts with "court". serve: {"until": frame, "court": [x_ft, y_ft]}
    -- until that frame (the serve's net crossing) the window frames the
    server, the player nearest that court position, instead of the ball:
    before the serve the ball is rarely tracked yet, and the window would
    otherwise wait where the ball is first seen, often the receiver's side.
    """
    n = len(ball_xs)
    # Where the ball isn't seen (most frames on some cameras: it is small
    # and fast), its position is filled in first, so the players still
    # steer the window there.
    want = list(_fill(ball_xs, W / 2))
    if use_players:
        for i in range(n):
            boxes = [p["box"] if isinstance(p, dict) else p for p in (people[i] or [])]
            if boxes:
                want[i] = _most_players(want[i], boxes, W, crop_w)
    if serve:
        for i in range(min(n, serve["until"])):
            box = _server_box(people[i] or [], serve["court"])
            if box is None:
                continue
            anchor = _centre_x(box)
            boxes = [p["box"] if isinstance(p, dict) else p for p in people[i]]
            want[i] = _most_players(anchor, boxes, W, crop_w) if use_players else anchor
    for t, court_y in focus or []:
        a, b = max(0, int((t - FOCUS_SEC) * fps)), min(n, int((t + FOCUS_SEC) * fps) + 1)
        for i in range(a, b):
            ps = [p for p in (people[i] or []) if isinstance(p, dict) and p.get("court")]
            if ps:
                want[i] = _centre_x(min(ps, key=lambda p: abs(p["court"][1] - court_y))["box"])
    return _fill(want, W / 2)


def smooth(centres, fps, W, crop_w, smooth_sec=SMOOTH_SEC, max_pan=MAX_PAN):
    """Gaussian-smoothed (looks ahead: offline), pan-speed-capped, kept inside the frame."""
    centres = np.asarray(centres, dtype=float)
    if not len(centres):
        return centres
    sigma = max(1.0, smooth_sec * fps)
    k = np.arange(-int(3 * sigma), int(3 * sigma) + 1)
    kernel = np.exp(-0.5 * (k / sigma) ** 2)
    kernel /= kernel.sum()
    s = np.convolve(np.pad(centres, len(k) // 2, mode="edge"), kernel, mode="valid")
    step = max_pan * W / fps
    out = np.empty_like(s)
    out[0] = s[0]
    for i in range(1, len(s)):
        out[i] = out[i - 1] + max(-step, min(step, s[i] - out[i - 1]))
    return np.clip(out, crop_w / 2, W - crop_w / 2)


def framing_path(ball_xs, people, W, H, fps=30.0, use_players=True, focus=None, serve=None):
    """Window centres for one clip as fractions of the frame width, at PATH_FPS.

    Returns {"fps": PATH_FPS, "x": [...]}: what a clip's manifest entry carries."""
    cw = crop_width(W, H)
    c = smooth(targets(ball_xs, people, W, cw, use_players, focus, fps, serve), fps, W, cw)
    step = fps / PATH_FPS
    idx = [int(round(i * step)) for i in range(int(len(c) / step) + 1) if int(round(i * step)) < len(c)]
    return {"fps": PATH_FPS, "x": [round(float(c[i]) / W, 4) for i in idx]}


def tracked_ball_xs(csv, calib, fps=30.0):
    """Tracked ball x per frame of the whole video (None when not seen): the
    same court-gated, teleport-rejected track rally detection uses."""
    from src.calib import court_wedge
    from src.track import max_jump_for_fps, reset_after_for_fps, track_ball
    from src.tracknet import load_predictions
    in_court = court_wedge(calib)
    frames = [[(x, y, c if c is not None else 1.0)] if in_court(x, y) else []
              for _, x, y, w, h, c in load_predictions(csv, fps)]
    _, xs = track_ball(frames, max_jump=max_jump_for_fps(fps), reset_after=reset_after_for_fps(fps), return_x=True)
    return xs


def on_court(poses):
    """A pose cache (src/pose.py) cut to players on court -- the badges' own filter."""
    from src.badges import _player
    return {f: [p for p in ps if _player(p)] for f, ps in (poses or {}).items()}


def clip_window(ball_xs, players, start, end, fps=30.0):
    """(ball xs, people) for one clip, [start, end) seconds into the video:
    what targets()/framing_path() take. players: on_court(poses), or {}."""
    f0, n = int(round(start * fps)), int(round((end - start) * fps))
    xs = (list(ball_xs[f0:f0 + n]) + [None] * n)[:n]
    return xs, [players.get(str(f0 + i)) for i in range(n)]


def centre_at(path, t):
    """Window centre (fraction of width) at clip time t, interpolated."""
    xs = path["x"]
    if not xs:
        return 0.5
    f = t * path["fps"]
    i = int(f)
    if i >= len(xs) - 1:
        return xs[-1]
    return xs[i] + (xs[i + 1] - xs[i]) * (f - i)


def window_left(path, t, W, H):
    """Left edge in pixels of the window at clip time t, for a frame W x H of any resolution."""
    cw = crop_width(W, H)
    return int(round(min(max(centre_at(path, t) * W - cw / 2, 0), W - cw)))


def find_serve(players, clip_start, rally_start, W, H, fps=30.0):
    """The serve for framing: {"until": frame in the clip, "court": server's
    feet}, or None if no baseline swing was seen in the 1.5 s before the
    rally's first net crossing -- the same serve the badges measure
    (src/badges.serve_peak). players: on_court(poses)."""
    from src.badges import serve_peak
    frames = range(int((rally_start - 1.5) * fps), int(rally_start * fps) + 1)
    peak = serve_peak(players, frames, W, H)
    if not peak:
        return None
    return {"until": int(round((rally_start + SERVE_HOLD_SEC - clip_start) * fps)), "court": [peak[4], peak[5]]}


def clip_framing(ball_xs, players, clip, W, H, fps=30.0, use_players=True, use_serve=True):
    """One clip's framing path. clip: {"start", "end"} padded seconds in the
    video, plus "rally_start" (its first net crossing) to frame the serve."""
    xs, people = clip_window(ball_xs, players, clip["start"], clip["end"], fps)
    serve = None
    if use_serve and use_players and clip.get("rally_start") is not None:
        serve = find_serve(players, clip["start"], clip["rally_start"], W, H, fps)
    return framing_path(xs, people, W, H, fps, use_players, serve=serve)
