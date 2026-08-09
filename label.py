#!/usr/bin/env python3
"""
Rally interval labeller.

Usage:
    label   python label.py session.mp4 --out eval/labels/session-001.jsonl --from 600 --to 1800
    review  python label.py session.mp4 --out eval/labels/session-001.jsonl --review

Controls (label):
    SPACE    play / pause
    s        mark rally START at current position
    e        mark rally END   (writes the interval)
    j / l    seek back / forward 2 s
    J / L    seek back / forward 10 s
    - / =    slower / faster playback
    u        undo last interval
    x        cancel a pending START
    w        save now
    q        save and quit

Controls (review) — play each labelled segment, keep or drop it:
    k        keep this segment, advance
    d        drop this segment, advance
    n / p    next / previous segment
    SPACE    replay current segment
    q        save the kept set and quit

Timestamps come from CAP_PROP_POS_MSEC, which is PTS-based - correct even if
the source is variable frame rate.
"""
import argparse
import json
import os
import sys

import cv2

HELP = ("SPACE play/pause  s start  e end  j/l seek2s  J/L seek10s  "
        "-/= speed  u undo  x cancel  w save  q quit")


def fmt(t):
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def load_rallies(path):
    """Load labelled rally intervals from a jsonl file (empty list if absent)."""
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def save_rallies(rallies, path):
    """Write rallies to jsonl, sorted by start and renumbered rally_id 1..N."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        for i, r in enumerate(sorted(rallies, key=lambda r: r["start"])):
            f.write(json.dumps(dict(r, rally_id=i + 1)) + "\n")


def review(args):
    """Play each labelled segment and keep or drop it; save the kept set.

    Use to curate auto-generated (or any) labels: drop low-quality segments,
    then re-run without --review to add rallies the detector missed."""
    rallies = sorted(load_rallies(args.out), key=lambda r: r["start"])
    if not rallies:
        sys.exit(f"no labels to review in {args.out}")
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        sys.exit(f"cannot open {args.video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    help_line = "k keep  d drop  n/p next/prev  SPACE replay  q save+quit"
    keep = [True] * len(rallies)
    i, seek = 0, True
    cv2.namedWindow("review", cv2.WINDOW_NORMAL)
    while True:
        r = rallies[i]
        if seek:
            cap.set(cv2.CAP_PROP_POS_MSEC, r["start"] * 1000)
            seek = False
        ok, frame = cap.read()
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if not ok or t >= r["end"]:
            seek = True          # loop within the segment
            continue
        img = frame.copy()
        w = img.shape[1]
        cv2.rectangle(img, (0, 0), (w, 64), (0, 0, 0), -1)
        state = "KEEP" if keep[i] else "DROP"
        colour = (0, 255, 0) if keep[i] else (0, 0, 255)
        cv2.putText(img, f"rally {i + 1}/{len(rallies)}  "
                    f"{fmt(r['start'])}-{fmt(r['end'])}  ({r['duration']:.1f}s)  [{state}]",
                    (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2)
        cv2.putText(img, help_line, (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (180, 180, 180), 1)
        cv2.imshow("review", img)
        k = cv2.waitKey(max(1, int(1000 / fps))) & 0xFF
        if k in (ord("k"), ord("d")):
            keep[i] = (k == ord("k"))
            i = min(i + 1, len(rallies) - 1)
            seek = True
        elif k == ord("n"):
            i = min(i + 1, len(rallies) - 1)
            seek = True
        elif k == ord("p"):
            i = max(i - 1, 0)
            seek = True
        elif k == ord(" "):
            seek = True
        elif k == ord("q"):
            break
    cap.release()
    cv2.destroyAllWindows()
    kept = [r for r, kp in zip(rallies, keep) if kp]
    save_rallies(kept, args.out)
    print(f"kept {len(kept)} of {len(rallies)} intervals -> {args.out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", required=True)
    ap.add_argument("--from", dest="start", type=float, default=0.0)
    ap.add_argument("--to", dest="end", type=float, default=None)
    ap.add_argument("--speed", type=float, default=2.0)
    ap.add_argument("--review", action="store_true",
                    help="review existing labels: play each segment and keep/drop")
    args = ap.parse_args()

    if args.review:
        return review(args)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        sys.exit(f"cannot open {args.video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    end_at = args.end if args.end is not None else dur
    cap.set(cv2.CAP_PROP_POS_MSEC, args.start * 1000)

    rallies = load_rallies(args.out)
    if rallies:
        print(f"resuming - {len(rallies)} intervals already labelled")

    pending = None
    playing = True
    speed = args.speed
    frame = None

    cv2.namedWindow("label", cv2.WINDOW_NORMAL)

    def save():
        save_rallies(rallies, args.out)
        print(f"saved {len(rallies)} intervals -> {args.out}")

    while True:
        if playing:
            ok, f_ = cap.read()
            if not ok:
                playing = False
            else:
                frame = f_
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if t >= end_at:
            playing = False

        if frame is not None:
            img = frame.copy()
            h, w = img.shape[:2]
            cv2.rectangle(img, (0, 0), (w, 64), (0, 0, 0), -1)
            state = f"START @ {fmt(pending)}" if pending is not None else "idle"
            cv2.putText(img, f"{fmt(t)}   x{speed:g}   {state}   n={len(rallies)}",
                        (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0)
                        if pending is None else (0, 200, 255), 2)
            cv2.putText(img, HELP, (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        (180, 180, 180), 1)
            cv2.imshow("label", img)

        delay = max(1, int(1000 / (fps * speed))) if playing else 30
        k = cv2.waitKey(delay) & 0xFF

        if k == ord(" "):
            playing = not playing
        elif k == ord("s"):
            pending = t
            print(f"  start {fmt(t)}")
        elif k == ord("e"):
            if pending is None:
                print("  ! no pending start")
            elif t <= pending:
                print("  ! end before start, ignored")
            else:
                rallies.append({"start": round(pending, 2), "end": round(t, 2),
                                "duration": round(t - pending, 2)})
                print(f"  rally {len(rallies)}: {fmt(pending)} -> {fmt(t)} "
                      f"({t - pending:.2f}s)")
                pending = None
        elif k == ord("x"):
            pending = None
            print("  cancelled")
        elif k == ord("u") and rallies:
            print(f"  undo {rallies.pop()}")
        elif k in (ord("j"), ord("l"), ord("J"), ord("L")):
            step = {ord("j"): -2, ord("l"): 2, ord("J"): -10, ord("L"): 10}[k]
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t + step) * 1000)
            ok, f_ = cap.read()
            if ok:
                frame = f_
        elif k == ord("-"):
            speed = max(0.25, speed / 2)
        elif k == ord("="):
            speed = min(16.0, speed * 2)
        elif k == ord("w"):
            save()
        elif k == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    save()

    if rallies:
        ds = sorted(r["duration"] for r in rallies)
        total = sum(ds)
        span = end_at - args.start
        print(f"\n{len(rallies)} rallies over {span / 60:.1f} min of source")
        print(f"  play time  {total / 60:.1f} min ({100 * total / span:.0f}% of source)")
        print(f"  duration   median {ds[len(ds) // 2]:.1f}s  "
              f"min {ds[0]:.1f}s  max {ds[-1]:.1f}s")


if __name__ == "__main__":
    main()
