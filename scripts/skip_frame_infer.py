"""Does skipping inference on some frame-trios trade accuracy for speed?

Not the already-answered question (EXPERIMENTS.md 2026-09-06: re-encoding a
video to 15fps by DROPPING every other frame halves recall and no threshold
recovers it -- that distorts the 3-frame window's natural 1/30s spacing,
which TrackNet was trained on). This tests a different operation: keep every
KEPT trio's three frames truly consecutive (same spacing the model expects),
just evaluate fewer trio positions along the video. A trio is "kept" when
its index is a multiple of --decimate; skipped trios get cap.grab()'d
(cheap, no decode) instead of cap.read()'d, and get a Visibility=0
placeholder row per frame so predictions.csv stays one row per source frame
-- everything downstream (crossing_times, cluster_crossings) already
tolerates Visibility=0 rows (that's a normal "no detection" frame).

--decimate 1 reproduces pod_infer.py's inference (same model, same prep3,
same per-frame blob-confidence picking) but without its double-buffered
producer/consumer thread -- written sequentially on purpose, so decimate=1
vs decimate=2/3 are timed by the exact same script and are a fair
apples-to-apples speed comparison with each other. (That decimate=1 number
will be slower than pod_infer.py's own pipelined ~58fps benchmark --
irrelevant here, only the *ratio* between decimate levels matters.)
"""
import argparse
import csv
import json
import time

import cv2
import numpy as np
import tensorflow as tf

from pod_infer import HEIGHT, WIDTH, court_mask, custom_loss, prep3  # noqa: E402


def run(video_path, model_path, output_csv, calib, margin_px, decimate):
    print(f"Loading model... (decimate={decimate})")
    model = tf.keras.models.load_model(
        model_path, custom_objects={"custom_loss": custom_loss}, compile=False,
    )

    @tf.function
    def infer(x):
        return model(x, training=False)

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    cal_res = calib.get("calibration_resolution") if calib else None
    ok, probe = cap.read()
    if not ok:
        raise SystemExit("could not read first frame")
    out_w, out_h = cal_res if cal_res else (probe.shape[1], probe.shape[0])
    x_ratio, y_ratio = out_w / WIDTH, out_h / HEIGHT
    mask = court_mask(calib, probe.shape, margin_px) if calib else None
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    print(f"Video: {n_frames} frames @ {fps:.1f} fps = {n_frames / fps:.1f}s")

    count = 0
    trio_idx = 0
    inference_calls = 0
    t0 = time.time()
    t_inference_path = 0.0  # prep3 + infer, kept trios only

    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Frame", "Visibility", "X", "Y", "W", "H", "Conf"])

        while count < n_frames:
            keep = (trio_idx % decimate == 0)
            if keep:
                frames = []
                for _ in range(3):
                    ok, img = cap.read()
                    if not ok:
                        break
                    frames.append(img)
                if not frames:
                    break
                t_pre = time.time()
                trio = frames + [frames[-1]] * (3 - len(frames))  # pad a short final trio
                if mask is not None:
                    trio = [im * mask[:, :, None] for im in trio]
                raw_pred = infer(tf.constant(prep3(trio))).numpy()
                inference_calls += 1
                t_inference_path += time.time() - t_pre
                mask_pred = (raw_pred > 0.5).astype(np.float32)
                h_pred = (mask_pred[0] * 255).astype(np.uint8)
                probs = raw_pred[0]
                for i in range(len(frames)):
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
            else:
                # Cheap advance: decode nothing, just move the stream position.
                for _ in range(3):
                    if count >= n_frames:
                        break
                    ok = cap.grab()
                    if not ok:
                        count = n_frames
                        break
                    writer.writerow([count, 0, -1, -1, -1, -1, 0.0])
                    count += 1
            trio_idx += 1

            if count % 900 == 0:
                elapsed = time.time() - t0
                print(f"  {count}/{n_frames}  {count / elapsed:.0f} frames/s wall  "
                      f"ETA {(n_frames - count) / (count / elapsed) / 60:.1f} min", flush=True)

    cap.release()
    elapsed = time.time() - t0
    print(f"\nDone: {count} frames in {elapsed / 60:.1f} min "
          f"({count / elapsed:.0f} frames/s wall, {inference_calls} model calls, "
          f"{t_inference_path:.1f}s in prep+infer)")
    print(f"Output: {output_csv}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--video", required=True)
    p.add_argument("--model", default="/workspace/TNV2_old_weights.h5")
    p.add_argument("--output", required=True)
    p.add_argument("--calib", default=None)
    p.add_argument("--court-margin", type=float, default=80.0)
    p.add_argument("--decimate", type=int, default=1,
                   help="evaluate 1 trio out of every N; N=1 evaluates every trio")
    args = p.parse_args()
    calib = json.load(open(args.calib)) if args.calib else None
    run(args.video, args.model, args.output, calib, args.court_margin, args.decimate)


if __name__ == "__main__":
    main()
