"""Vertical (9:16, ball-following) versions of everything a session's share
page shows: its top 10 rally clips, a full reel and a quick-hits reel.

A whole-session trial of scripts/follow_crop_prototype.py (2026-09-28), which
had only been tried on single hand-picked rallies. It builds what the share
page will show once ADR-133's scores are live, not what the field test's page
showed:
  - rally clips: the session's top 10 by the 0-100 score across all parts
    (src/select.py score_segments), each rally +-3 s like
    scripts/top_rallies_reel.py (PAD_SEC);
  - full reel: those 10 clips joined in score order, i.e. a whole-session full
    reel, not the newest part's (the ADR-128 trade-off);
  - quick hits: the busiest 3 s of each top rally (src/select.py peak_window)
    +-1.5 s, like scripts/burst_moment_reel.py, top-scored first until ~30 s,
    then played in time order.

Parts are given as <video>,<csv>,<calib> triples in session order; each part's
times are its own (part-relative), as the pod sees them.

Usage:
  python3 scripts/follow_crop_session.py --out-dir clips/session_x --logo logo.png \\
      --part p1.mp4,p1.csv,p1.calib.json --part p2.mp4,p2.csv,p2.calib.json
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from follow_crop_prototype import ball_xs, render_vertical  # noqa: E402
from src.rallies import detect_candidates  # noqa: E402
from src.render import probe_fps  # noqa: E402
from src.select import net_width_px, peak_window, score_segments  # noqa: E402

TOP_N = 10
RALLY_PAD = 3.0      # scripts/top_rallies_reel.py PAD_SEC
MOMENT_WINDOW = 3.0  # scripts/burst_moment_reel.py
MOMENT_PAD = 1.5
QUICK_HITS_SEC = 30.0  # cloud_pipeline/pod_driver.py BURST_TARGET_SEC


def concat(paths, out):
    """Join clips rendered with identical settings (no re-encode)."""
    lst = out + ".txt"
    with open(lst, "w") as f:
        for p in paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", "-movflags", "+faststart", out], check=True)
    os.remove(lst)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--part", action="append", required=True, help="video,csv,calib (session order)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--logo")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    parts, rallies = [], []
    for i, spec in enumerate(a.part, 1):
        video, csv, calib_path = spec.split(",")
        calib = json.load(open(calib_path))
        fps = probe_fps(video)
        cand = detect_candidates(video, csv, calib_path)
        scored = score_segments(cand["segments"], cand["times_crossed"], cand["speeds"], net_width_px(calib))
        parts.append({"video": video, "fps": fps, "xs": ball_xs(csv, calib, fps)})
        for r in scored:
            rallies.append({**r, "part": i, "moment": peak_window(
                [t for t in cand["times_crossed"] if r["start"] <= t <= r["end"]],
                r["start"], r["end"], window=MOMENT_WINDOW)})
        print(f"part {i}: {len(scored)} rallies", file=sys.stderr)

    top = sorted(rallies, key=lambda r: -r["score"])[:TOP_N]
    report = {"n_rallies": len(rallies), "clips": []}
    rally_files = []
    for rank, r in enumerate(top, 1):
        p = parts[r["part"] - 1]
        out = os.path.join(a.out_dir, f"rally_{rank:02d}")
        st = render_vertical(p["video"], p["xs"], p["fps"], r["start"] - RALLY_PAD, r["end"] + RALLY_PAD,
                             out, logo=a.logo)
        rally_files.append(out + ".mp4")
        report["clips"].append({"rank": rank, "part": r["part"], "start": round(r["start"], 1),
                                "end": round(r["end"], 1), "score": r["score"], **st})
        print(f"rally {rank:2d}: part {r['part']} {r['start']:6.1f}-{r['end']:6.1f}s score {r['score']:5.1f} "
              f"ball seen {st['seen']}/{st['frames']}, inside window {st['inside']}/{st['seen']}", file=sys.stderr)

    concat(rally_files, os.path.join(a.out_dir, "full_reel.mp4"))

    moments, total = [], 0.0
    for r in top:
        ws, we, _ = r["moment"]
        dur = (we - ws) + 2 * MOMENT_PAD
        if moments and total + dur > QUICK_HITS_SEC:
            break
        moments.append(r)
        total += dur
    moments.sort(key=lambda r: (r["part"], r["moment"][0]))  # time order
    hit_files = []
    for j, r in enumerate(moments, 1):
        p = parts[r["part"] - 1]
        ws, we, _ = r["moment"]
        out = os.path.join(a.out_dir, f"quickhit_{j:02d}")
        render_vertical(p["video"], p["xs"], p["fps"], ws - MOMENT_PAD, we + MOMENT_PAD, out,
                        logo=a.logo, debug=False)
        hit_files.append(out + ".mp4")
    concat(hit_files, os.path.join(a.out_dir, "quick_hits.mp4"))
    for f in hit_files:
        os.remove(f)
    report["quick_hits"] = [{"part": r["part"], "moment": [round(x, 1) for x in r["moment"][:2]]} for r in moments]

    with open(os.path.join(a.out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=1)
    print(f"wrote {len(rally_files)} rally clips, full_reel.mp4 and quick_hits.mp4 "
          f"({len(moments)} moments, ~{total:.0f}s) to {a.out_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
