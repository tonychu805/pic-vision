"""Build the training set for fine-tuning the ball model against a pale wall.

Step 1 of 2 (step 2 is scripts/finetune_tracknet.py). EXPERIMENTS.md
2026-11-01 (later) has the reasoning and every number; this is how the files
were made, so the training can be repeated or changed.

What it writes into --out:
  X.npy       (N, 3, 288, 512, 3) uint8: N trios of consecutive RGB frames, shrunk to
              the model's 512x288 grid, NOT court-masked (the masks are applied at
              training time, after the wall is washed)
  vid.npy     which source video each trio came from
  masks.npy   one court mask per source video (the pod's, on the 512x288 grid)
  labels.json {"meta": [{name, far_row}], "labels": per trio, per frame: (x, y) on the
              512x288 grid, or null}

The labels are pseudo-labels, not hand labels. They are the cached k14 detections of
each source video (cache/<name>_predictions_k14.csv), kept only when Conf >= 0.5, inside
the court wedge, and confirmed by two other detections within three frames. A frame
with no kept detection is labelled "no ball", so the model is never asked to find a
ball its own earlier run missed. Half of each video's ball trios have the ball above the
far baseline (where the wall is behind it); a few trios with no ball at all are added.

The sources below are the brickwall videos: a dark wall, where the ball is found well.
Nothing from Court 3, and nothing from brickwall_mid_atlantic (held out for testing).

Run from the repo root in an environment that has TensorFlow (the pod's: 2.15):
  python3 scripts/finetune_tracknet_data.py --out /mnt/fast_scratch/ft_data
"""
import argparse
import csv
import json
import math
import os
import random
import sys

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
import cv2
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
from pod_infer import court_mask  # noqa: E402
from src.calib import court_wedge  # noqa: E402

# name, video, calibration, cached detections, trios with a ball, trios without
SOURCES = [
    ("brickwall_30fps", "videos/brickwall_30fps.mp4", "calib/brickwall_30fps_calib.json",
     "cache/brickwall_30fps_predictions_k14.csv", 1500, 500),
    ("brickwall_semi", "videos/brickwall_semi_30fps.mp4", "calib/brickwall_semi_calib.json",
     "cache/brickwall_semi_predictions_k14.csv", 1500, 500),
]
GRID_W, GRID_H = 512, 288          # the model's input grid (scripts/pod_infer.py WIDTH, HEIGHT)
CONF_MIN = 0.5


def confirmed_detections(rows, neighbours=2, window=3, max_step=12):
    """{frame: (x, y)}: detections with `neighbours` others within `window` frames, each within
    max_step px per frame (+ 8) of it, in the video's own (calibration) pixels."""
    kept = {}
    for f, r in rows.items():
        if r["Visibility"] != "1" or float(r["Conf"]) < CONF_MIN:
            continue
        x, y = float(r["X"]), float(r["Y"])
        n = 0
        for d in range(-window, window + 1):
            q = rows.get(f + d)
            if d and q and q["Visibility"] == "1" and float(q["Conf"]) >= CONF_MIN and \
                    math.hypot(float(q["X"]) - x, float(q["Y"]) - y) <= max_step * abs(d) + 8:
                n += 1
        if n >= neighbours:
            kept[f] = (x, y)
    return kept


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="directory for X.npy, vid.npy, masks.npy, labels.json")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    random.seed(args.seed)
    os.makedirs(args.out, exist_ok=True)

    X, vid, masks, labels, meta = [], [], [], [], []
    for vi, (name, video, calib_path, csv_path, n_pos, n_neg) in enumerate(SOURCES):
        with open(os.path.join(REPO, calib_path)) as f:
            calib = json.load(f)
        cap = cv2.VideoCapture(os.path.join(REPO, video))
        w, h, n_frames = int(cap.get(3)), int(cap.get(4)), int(cap.get(7))
        cal_w, cal_h = calib.get("calibration_resolution") or (w, h)
        x_ratio, y_ratio = cal_w / GRID_W, cal_h / GRID_H          # calibration pixels per grid cell
        with open(os.path.join(REPO, csv_path)) as f:
            rows = {int(r["Frame"]): r for r in csv.DictReader(f)}
        in_court = court_wedge(calib)
        kept = {f: p for f, p in confirmed_detections(rows).items() if in_court(*p)}
        far_row = int(np.mean([p[1] for p in calib["image_points"][2:4]]) / y_ratio) - 2
        mask = cv2.resize(court_mask(calib, (h, w)).astype(np.uint8), (GRID_W, GRID_H),
                          interpolation=cv2.INTER_NEAREST)
        masks.append(mask)
        meta.append({"name": name, "far_row": far_row})

        with_ball = [f for f in range(2, n_frames - 3) if any(f + d in kept for d in (0, 1, 2))]
        above_wall = [f for f in with_ball if any(f + d in kept and kept[f + d][1] / y_ratio < far_row
                                                  for d in (0, 1, 2))]
        chosen = set(random.sample(above_wall, min(len(above_wall), n_pos // 2)))
        chosen |= set(random.sample(with_ball, min(len(with_ball), n_pos // 2)))
        without_ball = [f for f in range(2, n_frames - 3) if not any(f + d in kept for d in range(-2, 5))]
        chosen |= set(random.sample(without_ball, min(len(without_ball), n_neg)))
        print(f"{name}: {n_frames} frames, {len(kept)} confirmed detections, "
              f"{len(above_wall)} trios with the ball above the far baseline, {len(chosen)} trios chosen", flush=True)

        needed = set(f + d for f in chosen for d in (0, 1, 2))      # decode the video once, keep only these
        frames, i = {}, 0
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        while i <= max(needed):
            ok, img = cap.read()
            if not ok:
                break
            if i in needed:
                frames[i] = cv2.resize(img, (GRID_W, GRID_H), interpolation=cv2.INTER_AREA)[..., ::-1]
            i += 1
        for f in sorted(chosen):
            if all(f + d in frames for d in (0, 1, 2)):
                X.append(np.stack([frames[f + d] for d in (0, 1, 2)]))
                labels.append([(kept[f + d][0] / x_ratio, kept[f + d][1] / y_ratio) if f + d in kept else None
                               for d in (0, 1, 2)])
                vid.append(vi)

    X = np.stack(X).astype(np.uint8)
    print(f"{len(X)} trios, {X.nbytes // 2 ** 20} MB", flush=True)
    np.save(os.path.join(args.out, "X.npy"), X)
    np.save(os.path.join(args.out, "vid.npy"), np.array(vid))
    np.save(os.path.join(args.out, "masks.npy"), np.stack(masks))
    with open(os.path.join(args.out, "labels.json"), "w") as f:
        json.dump({"meta": meta, "labels": labels}, f)
    print("saved", args.out)


if __name__ == "__main__":
    main()
