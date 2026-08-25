"""EXPERIMENTAL: pod_infer.py with one change -- calls the model directly via
a compiled tf.function instead of Keras's high-level model.predict(). Not
wired into the pipeline (webapp/pipeline.py and the CLI docs still point at
pod_infer.py). Standalone script under scripts/ per this project's
convention for diagnostics/experiments that aren't part of the core
run-a-session flow.

Backstory (2026-08-25): a live GPU probe during a real inference run
suggested the GPU was idle waiting on CPU-bound preprocessing (~40% SM
utilization, one CPU thread pegged). Tried fixing that with batching
(pod_infer_batched.py) -- made things SLOWER, not faster, which meant the
premise was wrong. Per-stage profiling then showed model.predict() itself is
~87% of wall time in isolation, no CPU work anywhere near that. The actual
cause: pod_infer.py calls Keras's high-level .predict() API in a loop
(thousands of times, once per 3-frame group) -- .predict() carries fixed
per-call framework overhead (dataset/iterator setup, retracing checks)
regardless of how much data you hand it, which is exactly why batching
didn't help. The project's own EXPERIMENTS.md 2026-08-16 entry for the
original 58fps benchmark says it used a "batch-1 tf.function call" -- not
.predict() -- which is the direct clue this script acts on.

Verified (2026-08-25, 20s/603-frame probe clip, same GPU): 56.7fps vs the
current script's 29.2fps on the identical clip -- matches the historical
58fps benchmark almost exactly -- and the output CSV is byte-identical to
pod_infer.py's (diffed, zero differences: same model, same math, only the
call path changed).

Usage:
    python3 scripts/pod_infer_tffunc.py --video clip.mp4 --output out.csv \
        --calib calib.json

Same CSV output format and CLI args as pod_infer.py (no --batch-size, since
this needs no batching at all) -- meant to be a drop-in comparison: run it on
the same clip pod_infer.py was run on and diff the two CSVs before trusting
this path for anything real.
"""

import argparse
import csv
import os
import time

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import cv2
import numpy as np
import tensorflow as tf

from pod_infer import HEIGHT, WIDTH, custom_loss, court_mask, prep3


def run(video_path, model_path, output_csv, calib=None, margin_px=80.0):
    print("Loading model...")
    model = tf.keras.models.load_model(
        model_path,
        custom_objects={"custom_loss": custom_loss},
        compile=False,
    )

    @tf.function
    def infer(x):
        return model(x, training=False)

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(1, 0)
    ok, img1 = cap.read()
    ok, img2 = cap.read()
    ok, img3 = cap.read()
    x_ratio = img1.shape[1] / WIDTH
    y_ratio = img1.shape[0] / HEIGHT
    mask = court_mask(calib, img1.shape, margin_px) if calib else None
    if mask is not None:
        print(f"court mask: keeping {100 * mask.mean():.0f}% of the frame "
              f"(margin {margin_px:.0f}px)")
    print(f"Video: {n_frames} frames @ {fps:.1f} fps = {n_frames / fps:.1f}s, "
          f"x_ratio={x_ratio:.2f} y_ratio={y_ratio:.2f}")

    # Trace the tf.function once up front, outside the timed loop -- the
    # first call to a @tf.function compiles a graph for that input shape,
    # a one-time cost a real run should not pay per-frame.
    _ = infer(tf.constant(prep3([img1, img2, img3]))).numpy()
    cap.set(1, 0)
    ok, img1 = cap.read()
    ok, img2 = cap.read()
    ok, img3 = cap.read()

    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Frame", "Visibility", "X", "Y", "W", "H", "Conf"])

        count = 0
        t0 = time.time()

        while ok:
            trio = [img1, img2, img3]
            if mask is not None:
                trio = [im * mask[:, :, None] for im in trio]
            unit = prep3(trio)
            raw_pred = infer(tf.constant(unit)).numpy()
            mask_pred = (raw_pred > 0.5).astype(np.float32)
            h_pred = (mask_pred[0] * 255).astype(np.uint8)
            probs = raw_pred[0]

            for i in range(3):
                if np.amax(h_pred[i]) <= 0:
                    writer.writerow([count, 0, -1, -1, -1, -1, 0.0])
                else:
                    cnts, _ = cv2.findContours(
                        h_pred[i].copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                    )

                    def blob_confidence(c, i=i):
                        blob_mask = np.zeros_like(h_pred[i])
                        cv2.drawContours(blob_mask, [c], -1, 1, thickness=-1)
                        return float(probs[i][blob_mask.astype(bool)].max())
                    best_c = max(cnts, key=blob_confidence)
                    best = cv2.boundingRect(best_c)
                    cx = int(x_ratio * (best[0] + best[2] / 2))
                    cy = int(y_ratio * (best[1] + best[3] / 2))
                    writer.writerow([count, 1, cx, cy,
                                     round(x_ratio * best[2], 1),
                                     round(y_ratio * best[3], 1),
                                     round(blob_confidence(best_c), 4)])
                count += 1

            if count % 300 == 0:
                elapsed = time.time() - t0
                rate = count / elapsed
                eta = (n_frames - count) / rate
                print(f"  {count}/{n_frames}  {rate:.0f} fps  ETA {eta / 60:.1f} min", flush=True)

            ok, img1 = cap.read()
            ok, img2 = cap.read()
            ok, img3 = cap.read()

        cap.release()
        elapsed = time.time() - t0
        print(f"\nDone: {count} frames in {elapsed / 60:.1f} min ({count / elapsed:.1f} fps)")
        print(f"Output: {output_csv}")

        if n_frames and count < 0.98 * n_frames:
            raise SystemExit(
                f"ERROR: decoded {count} of {n_frames} frames ({100 * count / n_frames:.1f}%). "
                f"The source video is likely corrupt -- re-encode it before inference:\n"
                f"  ffmpeg -err_detect ignore_err -i IN.MOV -c:v h264_nvenc -preset p4 "
                f"-cq 20 -an -fps_mode cfr -r 30 OUT.mp4\n"
                f"(-fps_mode cfr keeps output timestamps aligned with the original.)")


def main():
    p = argparse.ArgumentParser(
        description="EXPERIMENTAL tf.function-direct-call TrackNet inference -- see module docstring")
    p.add_argument("--video", required=True)
    p.add_argument("--model", default="/workspace/TNV2_old_weights.h5")
    p.add_argument("--output", default="/workspace/predictions.csv")
    p.add_argument("--calib", default=None)
    p.add_argument("--court-margin", type=float, default=80.0)
    args = p.parse_args()
    calib = None
    if args.calib:
        import json
        with open(args.calib) as f:
            calib = json.load(f)
    run(args.video, args.model, args.output, calib=calib, margin_px=args.court_margin)


if __name__ == "__main__":
    main()
