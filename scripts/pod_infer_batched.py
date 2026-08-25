"""EXPERIMENTAL, REJECTED (2026-08-25): batched variant of pod_infer.py.
Kept only as a documented negative result -- not wired into the pipeline,
not the fix. See pod_infer_tffunc.py for the approach that actually worked.

Motivation was real: a live GPU probe during a real inference run showed SM
utilization averaging only ~40% while a single CPU thread stayed pegged at
83-99% -- looked like the GPU was idle waiting on CPU-bound per-frame work.
Thermal throttling and GPU clock/power state were ruled out first (33-46C
throughout, clocks correctly boost to ~2490MHz under load).

The fix attempted here -- batching BATCH_SIZE frame-trios into one
model.predict() call instead of one call per trio -- made things SLOWER
(25.6fps vs 29.2fps unbatched, measured on the same clip), not faster.
Per-stage profiling afterward showed why the whole premise was wrong:
model.predict() itself is ~87% of wall time in a clean, isolated measurement
-- the CPU work this script targeted (decode/preprocess/postprocess) was
never the bottleneck; the earlier GPU-probe reading was misleading. The
actual cause: pod_infer.py calls Keras's high-level .predict() API in a
loop, which carries fixed per-call framework overhead independent of batch
size (dataset/iterator setup, retracing checks) -- so batching that call
doesn't help, because the overhead isn't reduced by feeding it more data per
call. pod_infer_tffunc.py fixes this a different way (skip .predict()
entirely, call the model directly) and recovers the full historical 58fps
benchmark with byte-identical output -- see that script's docstring.
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


def run_batched(video_path, model_path, output_csv, calib=None, margin_px=80.0,
                 batch_size=16):
    print("Loading model...")
    model = tf.keras.models.load_model(
        model_path,
        custom_objects={"custom_loss": custom_loss},
        compile=False,
    )

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    def read_trio():
        """One trio = 3 raw frames, matching pod_infer.py's non-overlapping
        grouping (TrackNet's 3-in/3-heatmaps-out). Returns None once any of
        the 3 reads fails -- same trailing-partial-trio drop behavior as
        pod_infer.py (tolerated by the existing >=98%-decoded check below)."""
        imgs = []
        for _ in range(3):
            ok, img = cap.read()
            if not ok:
                return None
            imgs.append(img)
        return imgs

    first = read_trio()
    if first is None:
        raise SystemExit("could not read the first frame trio")
    x_ratio = first[0].shape[1] / WIDTH
    y_ratio = first[0].shape[0] / HEIGHT
    mask = court_mask(calib, first[0].shape, margin_px) if calib else None
    if mask is not None:
        print(f"court mask: keeping {100 * mask.mean():.0f}% of the frame "
              f"(margin {margin_px:.0f}px)")
    print(f"Video: {n_frames} frames @ {fps:.1f} fps = {n_frames / fps:.1f}s, "
          f"x_ratio={x_ratio:.2f} y_ratio={y_ratio:.2f}, batch_size={batch_size}")

    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Frame", "Visibility", "X", "Y", "W", "H", "Conf"])

        count = 0
        t0 = time.time()
        next_trio = first

        while next_trio is not None:
            batch_trios = [next_trio]
            while len(batch_trios) < batch_size:
                nxt = read_trio()
                if nxt is None:
                    break
                batch_trios.append(nxt)
            # seed the next outer iteration -- must happen every pass, not
            # just when the inner fill loop breaks early on end-of-video
            next_trio = read_trio()

            masked_trios = ([[im * mask[:, :, None] for im in trio] for trio in batch_trios]
                             if mask is not None else batch_trios)
            units = np.concatenate([prep3(trio) for trio in masked_trios], axis=0)
            raw_pred = model.predict(units, batch_size=len(batch_trios), verbose=0)
            mask_pred = (raw_pred > 0.5).astype(np.float32)

            for b in range(len(batch_trios)):
                h_pred = (mask_pred[b] * 255).astype(np.uint8)
                probs = raw_pred[b]

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

            if count % 300 < 3 * batch_size:
                elapsed = time.time() - t0
                rate = count / elapsed
                eta = (n_frames - count) / rate if rate else 0.0
                print(f"  {count}/{n_frames}  {rate:.0f} fps  ETA {eta / 60:.1f} min", flush=True)

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
        description="EXPERIMENTAL batched TrackNet inference -- see module docstring")
    p.add_argument("--video", required=True)
    p.add_argument("--model", default="/workspace/TNV2_old_weights.h5")
    p.add_argument("--output", default="/workspace/predictions.csv")
    p.add_argument("--calib", default=None)
    p.add_argument("--court-margin", type=float, default=80.0)
    p.add_argument("--batch-size", type=int, default=16,
                   help="frame-trios per model.predict() call (default 16)")
    args = p.parse_args()
    calib = None
    if args.calib:
        import json
        with open(args.calib) as f:
            calib = json.load(f)
    run_batched(args.video, args.model, args.output, calib=calib,
                margin_px=args.court_margin, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
