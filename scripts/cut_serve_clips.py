"""Cut watchable review clips for serve candidates (from propose_serves.py).

Reads cache/serve_candidates.csv, cuts an 8s window around each serve_t from the
source PGC mp4 (production clip_command), and writes a review manifest with a
blank `verdict` column for the human to fill: serve / not_serve / wrong_side.

Usage: PYTHONPATH=. .venv/bin/python scripts/cut_serve_clips.py --side far
"""
import sys, csv, argparse, pathlib, subprocess
ROOT = pathlib.Path("/home/tonychu/repository/pic-vision")
sys.path.insert(0, str(ROOT))
from src.render import clip_command

PGC = ROOT / "cache/pgc_fieldtest"
PRE, POST = 4.0, 9.0  # serves run late vs the proposer's estimate -> long tail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", default="far", choices=["far", "near", "all"])
    ap.add_argument("--candidates", default=str(ROOT / "cache/serve_candidates.csv"))
    args = ap.parse_args()

    outdir = ROOT / "cache/serve_review" / args.side
    outdir.mkdir(parents=True, exist_ok=True)

    rows = [r for r in csv.DictReader(open(args.candidates))
            if r["serve_t"] and (args.side == "all" or r["side"] == args.side)]
    rows.sort(key=lambda r: (r["session"], float(r["serve_t"])))

    manifest = []
    for i, r in enumerate(rows, 1):
        uuid = r["session"]; pre = uuid[:8]; t = float(r["serve_t"])
        video = PGC / f"{uuid}.mp4"
        if not video.exists():
            print(f"  SKIP {pre} @ {t}s -- no video"); continue
        start, end = max(0.0, t - PRE), t + POST
        clip = outdir / f"{i:03d}_{r['side']}_{pre}_{t:.0f}s.mp4"
        if not clip.exists() or clip.stat().st_size == 0:
            subprocess.run(clip_command(str(video), start, end, str(clip)),
                           check=True, capture_output=True)
        manifest.append({"idx": i, "clip": clip.name, "session": uuid, "name": r["name"],
                         "serve_t": r["serve_t"], "side": r["side"], "court_y": r["court_y"],
                         "swing_px_s": r["swing_px_s"], "verdict": ""})
        print(f"  [{i:02d}/{len(rows)}] {clip.name}")

    mpath = outdir / "review.csv"
    with open(mpath, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["idx", "clip", "session", "name", "serve_t",
                                          "side", "court_y", "swing_px_s", "verdict"])
        w.writeheader(); w.writerows(manifest)
    print(f"\n{len(manifest)} clips -> {outdir}")
    print(f"review manifest -> {mpath}")
    print("verdict values to fill: serve | not_serve | wrong_side")


if __name__ == "__main__":
    main()
