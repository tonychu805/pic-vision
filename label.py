#!/usr/bin/env python3
"""
Rally interval labeller.

Usage:
    python label.py session.mp4 --out labels/session-001.jsonl --from 600 --to 1800

Controls:
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", required=True)
    ap.add_argument("--from", dest="start", type=float, default=0.0)
    ap.add_argument("--to", dest="end", type=float, default=None)
    ap.add_argument("--speed", type=float, default=2.0)
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        sys.exit(f"cannot open {args.video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    end_at = args.end if args.end is not None else dur
    cap.set(cv2.CAP_PROP_POS_MSEC, args.start * 1000)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    rallies = []
    if os.path.exists(args.out):
        with open(args.out) as f:
            rallies = [json.loads(l) for l in f if l.strip()]
        print(f"resuming - {len(rallies)} intervals already labelled")

    pending = None
    playing = True
    speed = args.speed
    frame = None

    cv2.namedWindow("label", cv2.WINDOW_NORMAL)

    def save():
        with open(args.out, "w") as f:
            for i, r in enumerate(sorted(rallies, key=lambda r: r["start"])):
                r = dict(r, rally_id=i + 1)
                f.write(json.dumps(r) + "\n")
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
