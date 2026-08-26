"""Stage-by-stage profiling of pod_infer.py's per-frame loop.

Not part of the run-a-session flow -- a one-off diagnostic to find out
whether the pod's 29.4fps vs local's 36.2fps gap (cloud_pipeline/README.md
Status) is GPU-side, CPU-side (decode/resize/contour), or I/O-side. Runs
the identical stages as scripts/pod_infer.py but times each separately
over a fixed frame budget, on both local and pod, for an apples-to-apples
comparison.
"""

import argparse
import json
import os
import time

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import cv2
import numpy as np
import tensorflow as tf
import keras.backend as K

HEIGHT, WIDTH = 288, 512


def custom_loss(y_true, y_pred):
    loss = (-1) * (K.square(1 - y_pred) * y_true * K.log(K.clip(y_pred, K.epsilon(), 1))
                   + K.square(y_pred) * (1 - y_true) * K.log(K.clip(1 - y_pred, K.epsilon(), 1)))
    return K.mean(loss)


def court_mask(calib, shape, margin_px=80.0):
    h_inv = np.linalg.inv(np.array(calib["homography"], dtype=np.float64))
    width_ft, length_ft = calib.get("court_size_ft", [20.0, 44.0])
    rows = []
    for i in range(41):
        ft = i * length_ft / 40.0
        pts = cv2.perspectiveTransform(
            np.array([[[0.0, ft], [width_ft, ft]]], dtype=np.float32), h_inv)
        (xl, yl), (xr, yr) = pts[0][0], pts[0][1]
        rows.append(((float(yl) + float(yr)) / 2.0, float(xl), float(xr)))
    rows.sort()
    h, w = shape[:2]
    left = np.empty(h)
    right = np.empty(h)
    for y in range(h):
        if y <= rows[0][0]:
            _, xl, xr = rows[0]
        elif y >= rows[-1][0]:
            _, xl, xr = rows[-1]
        else:
            for (y0, l0, r0), (y1, l1, r1) in zip(rows, rows[1:]):
                if y0 <= y <= y1:
                    t = (y - y0) / max(1e-9, y1 - y0)
                    xl, xr = l0 + t * (l1 - l0), r0 + t * (r1 - r0)
                    break
        left[y], right[y] = xl - margin_px, xr + margin_px
    xs = np.arange(w)[None, :]
    return ((xs >= left[:, None]) & (xs <= right[:, None])).astype(np.uint8)


def prep3(imgs):
    channels = []
    for img in imgs:
        r = cv2.resize(img, (WIDTH, HEIGHT))
        r = r[..., ::-1].astype(np.float32) / 255.0
        channels.extend([r[..., 0], r[..., 1], r[..., 2]])
    return np.stack(channels).reshape(1, 9, HEIGHT, WIDTH).astype(np.float32)


def run(video_path, model_path, calib_path, n_trios, margin_px=80.0):
    print("Loading model...")
    model = tf.keras.models.load_model(
        model_path, custom_objects={"custom_loss": custom_loss}, compile=False)

    @tf.function
    def infer(x):
        return model(x, training=False)

    with open(calib_path) as f:
        calib = json.load(f)

    cap = cv2.VideoCapture(video_path)
    cap.set(1, 0)
    ok, img1 = cap.read()
    ok, img2 = cap.read()
    ok, img3 = cap.read()
    mask = court_mask(calib, img1.shape, margin_px)

    warm_trio = [im * mask[:, :, None] for im in [img1, img2, img3]]
    _ = infer(tf.constant(prep3(warm_trio))).numpy()

    t_decode = t_preprocess = t_gpu = t_postprocess = 0.0
    count = 0
    t_total0 = time.time()

    while ok and count < n_trios:
        t0 = time.time()
        # decode stage already happened for this trio via cap.read() below at
        # loop end (mirrors pod_infer.py's read-ahead structure) -- for the
        # first iteration img1/2/3 are the warm-up frames re-used, matching
        # pod_infer.py exactly.
        trio = [img1, img2, img3]
        t1 = time.time()

        masked_trio = [im * mask[:, :, None] for im in trio]
        unit = prep3(masked_trio)
        t2 = time.time()

        raw_pred = infer(tf.constant(unit)).numpy()
        t3 = time.time()

        mask_pred = (raw_pred > 0.5).astype(np.float32)
        h_pred = (mask_pred[0] * 255).astype(np.uint8)
        probs = raw_pred[0]
        for i in range(3):
            if np.amax(h_pred[i]) > 0:
                cnts, _ = cv2.findContours(
                    h_pred[i].copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                def blob_confidence(c, i=i):
                    blob_mask = np.zeros_like(h_pred[i])
                    cv2.drawContours(blob_mask, [c], -1, 1, thickness=-1)
                    return float(probs[i][blob_mask.astype(bool)].max())
                best_c = max(cnts, key=blob_confidence)
                _ = cv2.boundingRect(best_c)
        t4 = time.time()

        t_preprocess += t2 - t1
        t_gpu += t3 - t2
        t_postprocess += t4 - t3

        d0 = time.time()
        ok, img1 = cap.read()
        ok, img2 = cap.read()
        ok, img3 = cap.read()
        d1 = time.time()
        t_decode += d1 - d0

        count += 1

    cap.release()
    total = time.time() - t_total0
    fps = (count * 3) / total

    print(f"\n{count} trios ({count * 3} frames) in {total:.2f}s -> {fps:.1f} fps\n")
    print(f"{'stage':<14}{'total s':>10}{'ms/trio':>10}{'% of loop':>11}")
    stages = [("decode", t_decode), ("preprocess", t_preprocess),
              ("gpu infer", t_gpu), ("postprocess", t_postprocess)]
    stage_sum = sum(s for _, s in stages)
    for name, s in stages:
        print(f"{name:<14}{s:>10.2f}{1000 * s / count:>10.2f}{100 * s / stage_sum:>10.1f}%")
    print(f"{'(unaccounted)':<14}{total - stage_sum:>10.2f}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--model", default="/mnt/fast_scratch/tracknet_weights/weights_k14_epoch19")
    p.add_argument("--calib", required=True)
    p.add_argument("--n-trios", type=int, default=300)
    args = p.parse_args()
    run(args.video, args.model, args.calib, args.n_trios)


if __name__ == "__main__":
    main()
