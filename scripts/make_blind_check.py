"""Cut a blind playback check for the 'pace share' measurement (PIC-209).

Question for the human watching: do the clips with the HIGHEST pace share look
like fast exchanges, and do the LOWEST look slow? Judged on playback, not
numbers (CLAUDE.md verification rule).

Designed against the two things that would fool the check:
  * cameras differ in absolute pace, so rank WITHIN each video, never across;
  * fast rallies tend to be shorter, so candidates are limited to one length
    band and the two groups' lengths are reported, so length can't pose as speed.
Clips are shuffled, named A..J, silent (no audio hints), and the answer key is
written outside the repo (cache/) and not printed. IMG_7743 (eval set) is not
in the feature table and is never used.

Run: .venv/bin/python scripts/make_blind_check.py   (needs cache/ball_tempo_features.csv)
"""
import csv
import os
import random
import statistics
import subprocess
import string

SEED = 20261012
BAND = (5.0, 25.0)         # seconds; one length band for every candidate
PAD = 1.0                  # lead-in / tail, as the labelling rules keep a lead-in
OUT_DIR = "clips/blind_check"
KEY = "cache/blind_check_key.csv"
VIDEOS = {
    "brickwall_30fps": "videos/brickwall_30fps.mp4",
    "brickwall-SEMI": "videos/brickwall_semi_30fps.mp4",
    "pb_draft_cup": "videos/pb_draft_cup_30fps.mp4",
    "IMG_7744": "videos/IMG_7744_fixed.mp4",
}
QUOTA = {"brickwall_30fps": 2, "brickwall-SEMI": 1, "pb_draft_cup": 1, "IMG_7744": 1}  # per group


def main():
    rows = [r for r in csv.DictReader(open("cache/ball_tempo_features.csv")) if r["pace_share"] != ""]
    picks = []
    for video, k in QUOTA.items():
        cand = [r for r in rows if r["video"] == video and BAND[0] <= float(r["end"]) - float(r["start"]) <= BAND[1]]
        cand.sort(key=lambda r: (float(r["pace_share"]), float(r["start"])))
        if len(cand) < 2 * k:
            raise SystemExit(f"{video}: only {len(cand)} candidates in the length band")
        for r in cand[-k:]:
            picks.append((video, "high", r))
        for r in cand[:k]:
            picks.append((video, "low", r))
    random.Random(SEED).shuffle(picks)

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs("cache", exist_ok=True)
    with open(KEY, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["clip", "video", "group", "start", "end", "duration", "pace_share", "grade"])
        for letter, (video, group, r) in zip(string.ascii_uppercase, picks):
            start, end = float(r["start"]), float(r["end"])
            ss = max(0.0, start - PAD)
            out = f"{OUT_DIR}/{letter}.mp4"
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", f"{ss:.3f}", "-i", VIDEOS[video],
                 "-t", f"{end - ss + PAD:.3f}", "-an", "-c:v", "libx264", "-crf", "20",
                 "-preset", "veryfast", "-pix_fmt", "yuv420p", out],
                check=True)
            w.writerow([letter, video, group, f"{start:.2f}", f"{end:.2f}", f"{end - start:.2f}",
                        r["pace_share"], r["grade"]])

    # Group-level disclosure only: nothing here maps a letter to a group.
    for g in ("high", "low"):
        d = [float(r["end"]) - float(r["start"]) for _, grp, r in picks if grp == g]
        print(f"{g:4s} pace share group: n={len(d)}  clip length mean {statistics.mean(d):.1f}s "
              f"(range {min(d):.1f}-{max(d):.1f}s)")
    by = {}
    for v, g, _ in picks:
        by.setdefault(v, []).append(g)
    print("from each video: " + ", ".join(f"{v} {len(g)}" for v, g in by.items()))
    print(f"cut {len(picks)} clips -> {OUT_DIR}/  (answer key: {KEY}, not shown)")


if __name__ == "__main__":
    main()
