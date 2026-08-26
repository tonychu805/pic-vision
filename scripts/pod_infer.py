"""TrackNet inference script — runs ON the RunPod GPU pod.

Usage (on the pod):
    python3 pod_infer.py --video /workspace/game.MOV --output /workspace/predictions.csv

The script writes a CSV with columns Frame,Visibility,X,Y.
Copy it back locally and feed to `make process` (src/cut.py).

Model: TNV2_old_weights.h5 must be at /workspace/TNV2_old_weights.h5.
       Download from: https://github.com/AndrewDettor/TrackNet-Pickleball
       (rename the .h5 file; use compile=False to skip the Adadelta lr kwarg error)
"""

import argparse
import csv
import os
import queue
import threading
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
    """Binary mask of the tracked court plus the airspace above it.

    Masking *before* inference stops TrackNet hallucinating a ball on an
    adjacent court or on wall/netting clutter at all, rather than filtering
    those detections afterwards — on IMG_7743 that clutter produced most of
    the false-positive rallies (EXPERIMENTS.md 2026-08-16). The 3-frame input
    means a blacked-out region is motionless and yields no candidates.

    Mirrors src/calib.py's court_wedge geometry, inlined so this script stays
    standalone on the pod (it imports nothing from src/).
    """
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
    """Convert 3 BGR frames to (1,9,H,W) float32 numpy array."""
    channels = []
    for img in imgs:
        r = cv2.resize(img, (WIDTH, HEIGHT))
        r = r[..., ::-1].astype(np.float32) / 255.0
        channels.extend([r[..., 0], r[..., 1], r[..., 2]])
    return np.stack(channels).reshape(1, 9, HEIGHT, WIDTH).astype(np.float32)


def run(video_path, model_path, output_csv, calib=None, margin_px=80.0):
    print("Loading model...")
    model = tf.keras.models.load_model(
        model_path,
        custom_objects={"custom_loss": custom_loss},
        compile=False,
    )

    # Call the model directly via a compiled tf.function instead of Keras's
    # high-level model.predict() -- .predict() carries fixed per-call
    # framework overhead (dataset/iterator setup, retracing checks) that
    # dominated wall time here (~87% in isolated profiling) and doesn't
    # shrink with batch size. This alone recovers the project's original
    # 58fps benchmark; batching was tried and made things worse, not better
    # (see DECISIONS.md ADR-065).
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
    # prep3 resizes every frame to a fixed (WIDTH, HEIGHT) without preserving
    # aspect ratio, so scaling a prediction back to source pixels needs its
    # own ratio per axis -- a single height-derived ratio applied to both
    # silently corrupts every x-coordinate on any non-16:9 source (matches
    # HEIGHT/WIDTH's 288:512 = 16:9 only by coincidence otherwise). Found
    # 2026-08-24 on a 1280x640 (2:1) video -- every prior video happened to
    # be exactly 16:9, so this was invisible until now.
    x_ratio = img1.shape[1] / WIDTH
    y_ratio = img1.shape[0] / HEIGHT
    mask = court_mask(calib, img1.shape, margin_px) if calib else None
    if mask is not None:
        print(f"court mask: keeping {100 * mask.mean():.0f}% of the frame "
              f"(margin {margin_px:.0f}px)")
    print(f"Video: {n_frames} frames @ {fps:.1f} fps = {n_frames / fps:.1f}s, "
          f"x_ratio={x_ratio:.2f} y_ratio={y_ratio:.2f}")

    # Trace the tf.function once, outside the timed loop below -- the first
    # call to a @tf.function compiles a graph for that input shape, a
    # one-time cost a real run shouldn't pay per-frame. Uses the already-read
    # first trio (mirroring exactly what the loop's first iteration does) so
    # no frame is skipped or read twice.
    warm_trio = [img1, img2, img3]
    if mask is not None:
        warm_trio = [im * mask[:, :, None] for im in warm_trio]
    _ = infer(tf.constant(prep3(warm_trio))).numpy()

    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        # W,H,Conf are new (2026-08-16): the blob's size and peak probability
        # were computed and thrown away, discarding exactly the signals that
        # separate a real ball from background clutter (a far-court ball is
        # small; hallucinations score low). Readers must tolerate their
        # absence in older CSVs.
        writer.writerow(["Frame", "Visibility", "X", "Y", "W", "H", "Conf"])

        count = 0
        t0 = time.time()

        # Decode+preprocess (cv2.resize + numpy reshape, CPU-bound, ~53ms/trio
        # measured on a RunPod pod) and GPU inference (~38ms/trio) were
        # previously fully serial despite being independent work -- the GPU
        # sat idle during every resize, and the CPU sat idle during every GPU
        # call. A background thread decodes+preprocesses the *next* trio
        # while the main thread runs inference on the *current* one, so the
        # two costs overlap instead of stack (root-caused via
        # scripts/profile_pod_infer.py, DECISIONS.md ADR-043). This changes
        # only *when* the CPU work happens, not what it computes or the order
        # frames are read/written in -- output is unaffected.
        frame_q = queue.Queue(maxsize=3)
        producer_error = []

        def produce():
            nonlocal ok, img1, img2, img3
            try:
                while ok:
                    trio = [img1, img2, img3]
                    if mask is not None:
                        trio = [im * mask[:, :, None] for im in trio]
                    frame_q.put(prep3(trio))
                    ok, img1 = cap.read()
                    ok, img2 = cap.read()
                    ok, img3 = cap.read()
            except Exception as e:
                producer_error.append(e)
            finally:
                frame_q.put(None)

        producer = threading.Thread(target=produce, daemon=True)
        producer.start()

        while True:
            unit = frame_q.get()
            if unit is None:
                break
            raw_pred = infer(tf.constant(unit)).numpy()
            mask_pred = (raw_pred > 0.5).astype(np.float32)
            h_pred = (mask_pred[0] * 255).astype(np.uint8)
            probs = raw_pred[0]   # pre-threshold probabilities, same shape as h_pred

            for i in range(3):
                if np.amax(h_pred[i]) <= 0:
                    writer.writerow([count, 0, -1, -1, -1, -1, 0.0])
                else:
                    cnts, _ = cv2.findContours(
                        h_pred[i].copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                    )
                    # Pick by peak confidence within the blob, not bounding-box
                    # area — a larger-but-lower-confidence false positive (e.g. a
                    # background feature made more salient by preprocessing)
                    # would otherwise beat a smaller, higher-confidence real ball.
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

        producer.join()
        if producer_error:
            raise producer_error[0]

        cap.release()
        elapsed = time.time() - t0
        print(f"\nDone: {count} frames in {elapsed / 60:.1f} min ({count / elapsed:.1f} fps)")
        print(f"Output: {output_csv}")

        # A corrupt region makes cv2.VideoCapture stop reading and return cleanly,
        # so a truncated run is otherwise indistinguishable from a complete one —
        # it just writes a short CSV (2026-08-16: IMG_7743.MOV yielded 930 of
        # 121,013 frames, exit 0). Downstream only sees the CSV, so fail loudly.
        if n_frames and count < 0.98 * n_frames:
            raise SystemExit(
                f"ERROR: decoded {count} of {n_frames} frames ({100 * count / n_frames:.1f}%). "
                f"The source video is likely corrupt — re-encode it before inference:\n"
                f"  ffmpeg -err_detect ignore_err -i IN.MOV -c:v h264_nvenc -preset p4 "
                f"-cq 20 -an -fps_mode cfr -r 30 OUT.mp4\n"
                f"(-fps_mode cfr keeps output timestamps aligned with the original.)")


def main():
    p = argparse.ArgumentParser(description="TrackNet inference — run on RunPod GPU pod")
    p.add_argument("--video", required=True, help="path to input video on the pod")
    p.add_argument("--model", default="/workspace/TNV2_old_weights.h5",
                   help="path to TrackNet H5 weights (default: /workspace/TNV2_old_weights.h5)")
    p.add_argument("--output", default="/workspace/predictions.csv",
                   help="path for output CSV (default: /workspace/predictions.csv)")
    p.add_argument("--calib", default=None,
                   help="calibration JSON; masks everything outside the court "
                        "(plus its airspace) before inference, so adjacent courts "
                        "and wall clutter cannot produce detections at all")
    p.add_argument("--court-margin", type=float, default=80.0,
                   help="px padding on the court mask (default 80)")
    args = p.parse_args()
    calib = None
    if args.calib:
        import json
        with open(args.calib) as f:
            calib = json.load(f)
    run(args.video, args.model, args.output, calib=calib, margin_px=args.court_margin)


if __name__ == "__main__":
    main()
