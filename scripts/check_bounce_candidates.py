"""Label-free check of the bounce finder on the 38 pilot clips (2026-10-14).

No ground truth here, so this CANNOT give recall or precision. It reports proxies, to show
whether bounces are plausibly visible before anyone spends an hour labelling:
  tracked share   share of the rally's frames with a tracker-accepted ball
  longest blind   longest run of frames with no ball (a bounce hides inside a gap this long)
  candidates      bounce candidates the finder (serve_bounce_probe.candidates, rules unchanged)
                  produces inside the rally
  on-court        share of those candidates whose floor position, through the homography, is
                  inside the court +-3 ft (an off-court "bounce" is certainly wrong)
  per crossing    candidates / net crossings in the rally. A ball that crosses the net N times
                  has roughly N flights, most ending in a bounce, so a ratio far below ~0.5
                  says many bounces are being missed; a ratio far above ~1.5 says noise.
Run: .venv/bin/python scripts/check_bounce_candidates.py
"""
import json, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import numpy as np
import eval_bounce_recovery as ebr
from src.bounce_eval import project
import serve_bounce_probe as sbp
from src.ball import crossing_times, net_line_y
from src.track import track_ball
from src.tracknet import load_predictions
from src.calib import court_wedge

FPS = 30.0


def main():
    sample = json.load(open(ebr.SAMPLE))["clips"]
    rows = []
    for clip in sample:
        calib = json.load(open(clip["calib"]))
        H, raw, tracked, cands = ebr.clip_points(clip)
        a, b = int(clip["start"] * FPS), int(clip["end"] * FPS)
        n = b - a + 1
        inside = [f for f in tracked if a <= f <= b]
        run = longest = 0
        for f in range(a, b + 1):
            run = 0 if f in tracked else run + 1
            longest = max(longest, run)
        cs = [f for f in cands if a <= f <= b]
        on = 0
        for f in cs:
            x, y = project(H, *cands[f])
            on += (-3 <= x <= 23 and -3 <= y <= 47)
        tr = load_predictions(clip["csv"], FPS)
        wedge = court_wedge(calib, margin_px=160.0)
        frames = [[(x, y, c if c is not None else 1.0)] if (x is not None and wedge(x, y)) else []
                  for _, x, y, _w, _h, c in tr]
        ys = track_ball(frames, max_jump=150, reset_after=15)
        cr = [t for t in crossing_times(list(zip([i / FPS for i in range(len(ys))], ys)),
                                        net_y=net_line_y(calib), band=0) if clip["start"] <= t <= clip["end"]]
        rows.append(dict(set=clip["set"], id=clip["id"], dur=clip["end"] - clip["start"],
                         share=len(inside) / n, blind=longest / FPS, cands=len(cs),
                         on=on, cross=len(cr)))
    print(f"{'clip':22s} {'set':6s} {'dur s':>6s} {'tracked':>8s} {'longest blind s':>16s} {'cands':>6s} {'on-court':>9s} {'crossings':>10s}")
    for r in rows:
        print(f"{r['id']:22s} {r['set']:6s} {r['dur']:6.1f} {r['share']:8.0%} {r['blind']:16.1f} {r['cands']:6d} "
              f"{r['on']:9d} {r['cross']:10d}")
    print()
    for s in ("pgc", "public"):
        g = [r for r in rows if r["set"] == s]
        cands, cross = sum(r["cands"] for r in g), sum(r["cross"] for r in g)
        print(f"{s:7s} clips {len(g):2d}  mean tracked share {np.mean([r['share'] for r in g]):.0%}  "
              f"mean longest blind {np.mean([r['blind'] for r in g]):.1f}s  candidates {cands} "
              f"(on-court {sum(r['on'] for r in g)})  crossings {cross}  candidates per crossing {cands / max(cross, 1):.2f}")


if __name__ == "__main__":
    main()
