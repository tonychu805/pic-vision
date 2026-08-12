"""TrackNet inference script — runs ON the RunPod GPU pod.

Usage (on the pod):
    python3 pod_infer.py --video /workspace/game.MOV --output /workspace/predictions.csv

The script writes a CSV with columns Frame,Visibility,X,Y.
Copy it back locally and feed to scripts/process_footage.py.

Model: TNV2_old_weights.h5 must be at /workspace/TNV2_old_weights.h5.
       Download from: https://github.com/AndrewDettor/TrackNet-Pickleball
       (rename the .h5 file; use compile=False to skip the Adadelta lr kwarg error)
"""

import argparse
import csv
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


def prep3(imgs, ratio):
    """Convert 3 BGR frames to (1,9,H,W) float32 numpy array."""
    channels = []
    for img in imgs:
        r = cv2.resize(img, (WIDTH, HEIGHT))
        r = r[..., ::-1].astype(np.float32) / 255.0
        channels.extend([r[..., 0], r[..., 1], r[..., 2]])
    return np.stack(channels).reshape(1, 9, HEIGHT, WIDTH).astype(np.float32)


def run(video_path, model_path, output_csv):
    print("Loading model...")
    model = tf.keras.models.load_model(
        model_path,
        custom_objects={"custom_loss": custom_loss},
        compile=False,
    )

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(1, 0)
    ok, img1 = cap.read()
    ok, img2 = cap.read()
    ok, img3 = cap.read()
    ratio = img1.shape[0] / HEIGHT
    print(f"Video: {n_frames} frames @ {fps:.1f} fps = {n_frames / fps:.1f}s, ratio={ratio:.2f}")

    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Frame", "Visibility", "X", "Y"])

        count = 0
        t0 = time.time()

        while ok:
            unit = prep3([img1, img2, img3], ratio)
            y_pred = model.predict(unit, batch_size=1, verbose=0)
            y_pred = (y_pred > 0.5).astype(np.float32)
            h_pred = (y_pred[0] * 255).astype(np.uint8)

            for i in range(3):
                if np.amax(h_pred[i]) <= 0:
                    writer.writerow([count, 0, -1, -1])
                else:
                    cnts, _ = cv2.findContours(
                        h_pred[i].copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                    )
                    rects = [cv2.boundingRect(c) for c in cnts]
                    best = max(rects, key=lambda r: r[2] * r[3])
                    cx = int(ratio * (best[0] + best[2] / 2))
                    cy = int(ratio * (best[1] + best[3] / 2))
                    writer.writerow([count, 1, cx, cy])
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


def main():
    p = argparse.ArgumentParser(description="TrackNet inference — run on RunPod GPU pod")
    p.add_argument("--video", required=True, help="path to input video on the pod")
    p.add_argument("--model", default="/workspace/TNV2_old_weights.h5",
                   help="path to TrackNet H5 weights (default: /workspace/TNV2_old_weights.h5)")
    p.add_argument("--output", default="/workspace/predictions.csv",
                   help="path for output CSV (default: /workspace/predictions.csv)")
    args = p.parse_args()
    run(args.video, args.model, args.output)


if __name__ == "__main__":
    main()
