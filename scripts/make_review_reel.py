#!/usr/bin/env python3
"""
Cut a detector-only "gap" candidate list (from scripts/review_gaps.py extract)
into a single watchable reel, one padded clip per candidate, each burned in
with its rally_id and original-video timestamp so the operator can grade it
against the *_gaps.jsonl file afterward (pass 3, see review_gaps.py).

    python scripts/make_review_reel.py \
        --gaps eval/labels/IMG_7743_prebump_0-2900s_gaps.jsonl \
        --video videos/IMG_7743_prebump_0-2900s.mp4 \
        --tag PRE \
        --out clips/IMG_7743_prebump_fp_review.mp4

Multiple --gaps/--video/--tag triples may be given (repeat all three, same
order) to concatenate several sources (e.g. prebump + postbump) into one reel.
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from label import load_rallies


def cut_clip(video, start, end, tag, rally_id, out_path, pad):
    cstart = max(0.0, start - pad)
    cend = end + pad
    duration = cend - cstart
    # Raw seconds (matching the *_gaps.jsonl start/end fields directly) rather
    # than mm:ss — a literal colon breaks drawtext's own option parsing.
    label = f"{tag} #{rally_id}  {start:.2f}s-{end:.2f}s (orig)"
    drawtext = (
        f"drawtext=text='{label}':fontcolor=white:fontsize=28:box=1:"
        f"boxcolor=black@0.6:boxborderw=8:x=20:y=20"
    )
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{cstart}", "-i", video, "-t", f"{duration}",
        "-vf", drawtext,
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-an", out_path,
    ]
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gaps", action="append", required=True)
    ap.add_argument("--video", action="append", required=True)
    ap.add_argument("--tag", action="append", required=True,
                     help="short label burned into each clip, e.g. PRE / POST")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pad", type=float, default=2.0,
                     help="seconds of context padded on each side (default 2.0)")
    args = ap.parse_args()

    if not (len(args.gaps) == len(args.video) == len(args.tag)):
        sys.exit("--gaps, --video, --tag must be given the same number of times")

    work_dir = os.path.join("clips", "_review_reel_parts")
    os.makedirs(work_dir, exist_ok=True)
    filelist_path = os.path.join(work_dir, "_filelist.txt")

    n_total = 0
    with open(filelist_path, "w") as filelist:
        for gaps_path, video, tag in zip(args.gaps, args.video, args.tag):
            candidates = load_rallies(gaps_path)
            print(f"{gaps_path}: {len(candidates)} candidates from {video}")
            for c in sorted(candidates, key=lambda c: c["start"]):
                rid = c.get("rally_id", "?")
                part = os.path.join(work_dir, f"{tag}_{rid:03d}.mp4"
                                     if isinstance(rid, int) else f"{tag}_{rid}.mp4")
                cut_clip(video, c["start"], c["end"], tag, rid, part, args.pad)
                filelist.write(f"file '{os.path.abspath(part)}'\n")
                n_total += 1

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "concat", "-safe", "0",
        "-i", filelist_path, "-c", "copy", args.out,
    ], check=True)

    print(f"wrote {n_total} clips -> {args.out}")


if __name__ == "__main__":
    main()
