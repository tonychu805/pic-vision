"""Vertical (9:16) framing, ball-only vs ball + players, on already-cut rally clips.

Takes a finished run's clips (manifest.json with each clip's padded start/end
in the source video), the source's ball predictions and calibration, and the
pose cache that run produced, then for each clip:
  - computes both framing paths (src/framing.py),
  - scores them: ball inside the window, and swings shown (each swing peak
    from src/badges.swing_peaks: is the swinging wrist inside the window?),
  - renders <out>/<clip>_vertical.mp4 (ball + players) by cropping the CLIP
    itself, not the source -- the path travels with the clip -- plus a
    side-by-side <clip>_compare.mp4: the wide shot with ball-only (red) and
    ball + players + serve start (green) windows drawn, to watch.

Usage:
  python3 scripts/vertical_framing_eval.py --clips DIR --video V --csv C --calib J --poses P --out OUT [--files a.mp4 b.mp4]
"""
import argparse
import json
import os
import subprocess
import sys

import cv2
import numpy as np

sys.path.insert(0, ".")

from src import badges, framing
from src.render import probe_fps


def score(path, xs, swings, people, f0, n, fps, W, H):
    cw = framing.crop_width(W, H)
    left = [framing.window_left(path, i / fps, W, H) for i in range(n)]
    posed = [(i, ps) for i, ps in enumerate(people) if ps]
    on = sum(len(ps) for _, ps in posed)
    full = sum(1 for i, ps in posed for p in ps if left[i] <= p["box"][0] and p["box"][2] <= left[i] + cw)
    seen = [(i, x) for i, x in enumerate(xs) if x is not None]
    inside = sum(1 for i, x in seen if left[i] <= x <= left[i] + cw)
    shown = sum(1 for s in swings if left[int(round(s[1] * fps)) - f0] <= s[2][0] <= left[int(round(s[1] * fps)) - f0] + cw)
    return {"ball_seen": len(seen), "ball_inside": inside, "swings": len(swings), "swings_shown": shown,
            "players": on, "players_shown": full}


def writer(path, w, h, fps):
    return subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                             "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
                             "-pix_fmt", "yuv420p", "-movflags", "+faststart", path], stdin=subprocess.PIPE)


def render(clip, paths, out_v, out_c, fps):
    cap = cv2.VideoCapture(clip)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cw = framing.crop_width(W, H)
    vh = 1920 if H >= 1080 else H // 2 * 2            # no upscaling past the source's own height
    vw = int(round(vh * 9 / 16)) // 2 * 2
    dw, dh = 960, int(960 * H / W) // 2 * 2
    v, c = writer(out_v, vw, vh, fps), writer(out_c, dw + int(dh * 9 / 16) // 2 * 2, dh, fps)
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        lb = framing.window_left(paths["ball"], i / fps, W, H)
        lp = framing.window_left(paths["serve"], i / fps, W, H)
        v.stdin.write(cv2.resize(frame[:, lp:lp + cw], (vw, vh), interpolation=cv2.INTER_LANCZOS4).tobytes())
        d = frame.copy()
        cv2.rectangle(d, (lb, 2), (lb + cw - 1, H - 3), (0, 0, 255), 4)
        cv2.rectangle(d, (lp, 8), (lp + cw - 1, H - 9), (0, 220, 0), 4)
        side = cv2.resize(frame[:, lp:lp + cw], (int(dh * 9 / 16) // 2 * 2, dh))
        c.stdin.write(np.hstack([cv2.resize(d, (dw, dh)), side]).tobytes())
        i += 1
    for p in (v, c):
        p.stdin.close()
        p.wait()


def main():
    ap = argparse.ArgumentParser()
    for k in ("clips", "video", "csv", "calib", "poses", "out"):
        ap.add_argument(f"--{k}", required=True)
    ap.add_argument("--files", nargs="*", help="only these clips (default: every clip in the manifest)")
    ap.add_argument("--no-render", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    fps = probe_fps(a.video)
    cap = cv2.VideoCapture(a.video)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    xs_all = framing.tracked_ball_xs(a.csv, json.load(open(a.calib)), fps)
    P = framing.on_court(json.load(open(a.poses)))
    peaks = badges.swing_peaks(P, W, H)
    manifest = json.load(open(os.path.join(a.clips, "manifest.json")))
    manifest = manifest["clips"] if isinstance(manifest, dict) else manifest

    rows = []
    for m in manifest:
        if a.files and m["file"] not in a.files:
            continue
        f0 = int(round(m["start"] * fps))
        xs, people = framing.clip_window(xs_all, P, m["start"], m["end"], fps)
        n = len(xs)
        # Older manifests lack rally_start: the clip was padded PAD_SEC before it.
        clip = {**m, "rally_start": m.get("rally_start", m["start"] + 3.0 if m["start"] > 0 else None)}
        paths = {"ball": framing.clip_framing(xs_all, P, clip, W, H, fps, use_players=False),
                 "players": framing.clip_framing(xs_all, P, clip, W, H, fps, use_serve=False),
                 "serve": framing.clip_framing(xs_all, P, clip, W, H, fps)}
        swings = [s for s in peaks if f0 <= int(round(s[1] * fps)) < f0 + n]
        row = {"file": m["file"], "start": m["start"], "badge": m.get("badge"),
               **{k: score(p, xs, swings, people, f0, n, fps, W, H) for k, p in paths.items()}}
        rows.append(row)
        b, p = row["ball"], row["serve"]
        print(f"{m['file']:14} {m.get('badge') or '':12} swings shown: ball-only {b['swings_shown']}/{b['swings']}, "
              f"+players {p['swings_shown']}/{p['swings']}  |  ball inside: {b['ball_inside']}/{b['ball_seen']} vs "
              f"{p['ball_inside']}/{p['ball_seen']}  |  players fully shown {b['players_shown']}/{b['players']} vs {p['players_shown']}", flush=True)
        json.dump(paths, open(os.path.join(a.out, m["file"].replace(".mp4", "_framing.json")), "w"))
        if not a.no_render:
            stem = os.path.join(a.out, m["file"].replace(".mp4", ""))
            render(os.path.join(a.clips, m["file"]), paths, stem + "_vertical.mp4", stem + "_compare.mp4", fps)

    tot = {k: {q: sum(r[k][q] for r in rows) for q in ("ball_seen", "ball_inside", "swings", "swings_shown", "players", "players_shown")} for k in ("ball", "players", "serve")}
    for k, t in tot.items():
        print(f"TOTAL {k:8} swings shown {t['swings_shown']}/{t['swings']} ({t['swings_shown'] / max(t['swings'], 1):.0%}), "
              f"ball inside {t['ball_inside']}/{t['ball_seen']} ({t['ball_inside'] / max(t['ball_seen'], 1):.0%}), "
              f"players fully shown {t['players_shown']}/{t['players']} ({t['players_shown'] / max(t['players'], 1):.0%})")
    json.dump({"rows": rows, "total": tot}, open(os.path.join(a.out, "summary.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
