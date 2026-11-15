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
import json
import os
import queue
import sys
import threading
import time

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import cv2
import numpy as np

# court_crop is the one src/ module this script needs (the pod ships src/ beside it).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.court_crop import court_crop_box, grid_to_calibration  # noqa: E402
from src.cpus import limit_threads, usable_cpus  # noqa: E402,F401 -- thread pools sized to the pod (src/cpus.py)

HEIGHT, WIDTH = 288, 512


def custom_loss(y_true, y_pred):
    import keras.backend as K
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

    calib['homography'] is an absolute-pixel-coordinate transform with no
    inherent scale -- it's only valid at the resolution the calibration
    frame was actually clicked at (calib['calibration_resolution'], written
    by calibrate.py/calibrate_web.py/webapp/app.py). If `shape` (the frame
    actually being masked) is a different resolution -- e.g. a lower-res
    proxy uploaded to save bandwidth -- building the mask directly against
    `shape` would silently misplace the court boundary. Instead, build the
    mask at the calibration's own resolution (where the homography's pixel
    coordinates are valid) and resize the finished boolean mask to `shape`
    at the end. Resizing the *result* is deliberately simpler and safer than
    hand-scaling every intermediate row/column number -- exactly that kind
    of per-axis arithmetic is what produced ADR-064's coordinate bug.
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
    cal_res = calib.get("calibration_resolution")
    h, w = (cal_res[1], cal_res[0]) if cal_res else shape[:2]
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
    mask = ((xs >= left[:, None]) & (xs <= right[:, None])).astype(np.uint8)
    if (h, w) != shape[:2]:
        mask = cv2.resize(mask, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    return mask


def prep3(imgs, crop=None):
    """Convert 3 BGR frames to (1,9,H,W) float32 numpy array.

    crop: (x0, y0, x1, y1) in frame pixels (src/court_crop.py) -- only that part
    of each frame goes to the model, so the ball shrinks less on its way down."""
    channels = []
    for img in imgs:
        if crop:
            img = img[crop[1]:crop[3], crop[0]:crop[2]]
        r = cv2.resize(img, (WIDTH, HEIGHT))
        r = r[..., ::-1].astype(np.float32) / 255.0
        channels.extend([r[..., 0], r[..., 1], r[..., 2]])
    return np.stack(channels).reshape(1, 9, HEIGHT, WIDTH).astype(np.float32)


def half_precision(model):
    """The same network computing in float16 (weights copied); the original on any failure."""
    try:
        cfg = model.get_config()
        for layer in cfg["layers"]:
            if layer["class_name"] != "InputLayer":
                layer["config"]["dtype"] = "mixed_float16"
        half = model.__class__.from_config(cfg)
        half.set_weights(model.get_weights())
        return half
    except Exception as e:  # noqa: BLE001 -- full precision still works, just slower
        print(f"WARNING: float16 model unavailable ({type(e).__name__}: {e}); using float32")
        return model


def apply_mask(img, mask3):
    """Court mask on a full-size BGR frame. cv2.bitwise_and with a 0/255 mask
    gives the same pixels as img * mask (0/1) at ~1/3 of the CPU time --
    the CPU side was what limited a pod (2026-10-27 profile)."""
    return cv2.bitwise_and(img, mask3)


def _bilinear_taps(n_in, n_out):
    """Along one axis: the two source indices and the second one's weight for
    each output pixel of a bilinear resize with half-pixel centres (cv2.resize
    INTER_LINEAR, F.interpolate(align_corners=False))."""
    src = np.maximum((np.arange(n_out) + 0.5) * (n_in / n_out) - 0.5, 0.0)
    i0 = np.floor(src).astype(np.int64)
    return i0, np.minimum(i0 + 1, n_in - 1), (src - i0).astype(np.float32)


def gpu_prep(mask, crop, frame_shape):
    """(stage, prep): the court mask, crop and resize on the GPU instead of apply_mask + prep3.

    stage(trio) runs on the decode thread and starts the upload; prep(staged)
    runs on the inference thread and returns what prep3 returns, as a
    (1, 9, HEIGHT, WIDTH) float32 CUDA tensor.

    2026-11-13: the mask and resize cost 6.5-7 ms per frame on the CPU, more
    than decoding (3-4 ms); on an 8-CPU Google machine the GPU waited ~69 s per
    10-min part for frames. Only the PyTorch model on CUDA gets this
    (PIC_VISION_INFER_GPU_PREP=0 forces the CPU path); TensorFlow keeps prep3.

    Each output pixel is a weighted sum of 4 source pixels, so only the source
    rows those touch (576 of 1080 at 1080p) are copied and uploaded: uploading
    whole frames took 3 ms per trio on an RTX 2000 Ada, longer than the resize.
    A masked-out source pixel just gets weight 0, which is masking before the
    resize, as prep3's caller does. The upload runs on its own stream so it
    overlaps the model."""
    import torch
    y0, y1, x0, x1 = (crop[1], crop[3], crop[0], crop[2]) if crop else (0, frame_shape[0], 0, frame_shape[1])
    full_w = frame_shape[1]
    r0, r1, wy = _bilinear_taps(y1 - y0, HEIGHT)
    c0, c1, wx = _bilinear_taps(x1 - x0, WIDTH)
    rows, at = np.unique(np.concatenate([r0, r1]), return_inverse=True)
    keep = np.ones((y1 - y0, x1 - x0), np.float32) if mask is None else mask[y0:y1, x0:x1].astype(np.float32)
    idx, weight = [], []
    for r, staged_r, w_r in ((r0, at[:HEIGHT], 1 - wy), (r1, at[HEIGHT:], wy)):
        for c, w_c in ((c0, 1 - wx), (c1, wx)):
            idx.append(staged_r[:, None] * full_w + (c + x0)[None, :])
            weight.append(w_r[:, None] * w_c[None, :] * keep[r][:, c])
    idx = torch.from_numpy(np.stack(idx).reshape(4, -1)).cuda()
    weight = torch.from_numpy(np.stack(weight).reshape(4, 1, -1, 1)).cuda()
    rows = torch.from_numpy(rows + y0)
    copy_stream = torch.cuda.Stream()

    def stage(trio):
        staged = torch.empty((3, len(rows), full_w, 3), dtype=torch.uint8, pin_memory=True)
        for i, img in enumerate(trio):
            torch.index_select(torch.from_numpy(img), 0, rows, out=staged[i])
        with torch.cuda.stream(copy_stream):
            x = staged.to("cuda", non_blocking=True)
            uploaded = torch.cuda.Event()
            uploaded.record()
        return x, uploaded

    def prep(staged):
        x, uploaded = staged
        stream = torch.cuda.current_stream()
        stream.wait_event(uploaded)
        x.record_stream(stream)            # allocated on copy_stream, freed after use on this one
        x = x.view(3, -1, 3)
        out = sum(x.index_select(1, idx[k]).float() * weight[k] for k in range(4))
        # cv2.resize returns uint8, so prep3 sees rounded pixels; rounding here
        # too lands within one level of it (tests/test_pod_infer_gpu_prep.py).
        out = out.round_().clamp_(0, 255).div_(255.0)
        return out.view(3, HEIGHT, WIDTH, 3).permute(0, 3, 1, 2).flip(1).reshape(1, 9, HEIGHT, WIDTH)
    return stage, prep


def wants_gpu_prep(model_path):
    if not model_path.endswith(".pt") or os.environ.get("PIC_VISION_INFER_GPU_PREP", "1") != "1":
        return False
    import torch
    return torch.cuda.is_available()


def load_infer(model_path):
    """infer(x) -> float32 heatmaps for a (n, 9, HEIGHT, WIDTH) float32 batch.

    The PyTorch model also takes that batch as a CUDA tensor (gpu_prep's output).

    A .pt file is the PyTorch TrackNet (src/tracknet_torch.py, 2026-11-12): the
    pod needs no TensorFlow, so it runs on the stock runpod/pytorch image
    instead of pulling our 9.3 GB one. Anything else is the Keras model, as
    before (PIC_VISION_INFER_FP16 applies to both)."""
    half = os.environ.get("PIC_VISION_INFER_FP16", "1") == "1"
    if model_path.endswith(".pt"):
        import torch
        from src.tracknet_torch import load
        device = "cuda" if torch.cuda.is_available() else "cpu"
        torch.backends.cudnn.benchmark = True          # one fixed input shape
        model = load(model_path, device=device, half=half)
        dtype = next(model.parameters()).dtype

        def to_numpy(y):
            if device == "cpu":
                return y.float().numpy()
            # 2026-11-13: .cpu() copies into pageable memory, and while that copy
            # waits for the model it blocks every other thread's CUDA copy too:
            # gpu_prep's upload on the decode thread stalled ~14 ms per trio,
            # so decoding stopped running ahead of the GPU. A pinned copy doesn't.
            host = torch.empty(y.shape, dtype=torch.float32, pin_memory=True)
            host.copy_(y.float(), non_blocking=True)
            torch.cuda.current_stream().synchronize()
            return host.numpy()

        def eager(x):
            x = x if torch.is_tensor(x) else torch.from_numpy(x)
            with torch.no_grad():
                return to_numpy(model(x.to(device, dtype)))

        graph = None
        if device == "cuda" and os.environ.get("PIC_VISION_INFER_CUDA_GRAPH", "1") == "1":
            graph = _cuda_graph(torch, model, (1, 9, HEIGHT, WIDTH), dtype)
        print(f"model: PyTorch TrackNet, {dtype}, {device}, CUDA graph {'on' if graph else 'off'}")
        if graph is None:
            return eager
        g, static_in, static_out = graph

        def infer(x):
            if x.shape != tuple(static_in.shape):
                return eager(x)
            static_in.copy_(x if torch.is_tensor(x) else torch.from_numpy(x))
            g.replay()
            return to_numpy(static_out)
        return infer
    return _tf_infer(model_path, half)


def _cuda_graph(torch, model, shape, dtype):
    """The model's forward pass recorded as one CUDA graph, replayed per call, or None.

    Eager PyTorch launches ~100 small kernels per call from Python; on a pod
    whose CPU is slow or contended that launching, not the GPU, is the cost.
    A graph replays them as one launch. Same kernels, same numbers."""
    try:
        static_in = torch.zeros(shape, device="cuda", dtype=dtype)
        side = torch.cuda.Stream()
        side.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(side), torch.no_grad():
            for _ in range(3):                         # warm-up: cudnn picks its kernels here
                model(static_in)
        torch.cuda.current_stream().wait_stream(side)
        g = torch.cuda.CUDAGraph()
        with torch.cuda.graph(g), torch.no_grad():
            static_out = model(static_in)
        return g, static_in, static_out
    except Exception as e:  # noqa: BLE001 -- eager still works, just slower
        print(f"WARNING: CUDA graph unavailable ({type(e).__name__}: {e}); running eagerly")
        return None


def _tf_infer(model_path, half):
    import tensorflow as tf
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
    # Half precision + XLA (2026-10-27): 40 -> 13 ms per 3 frames on an RTX
    # 2000 Ada, with every ball detection on a real 1080p part unchanged
    # (shifts <= 0.5 px at 512 wide; EXPERIMENTS.md). The saved model pins
    # each layer to float32, so the float16 copy is rebuilt from its config.
    # PIC_VISION_INFER_FP16=0 / PIC_VISION_INFER_XLA=0 restore the old path.
    if half:
        model = half_precision(model)
    xla = os.environ.get("PIC_VISION_INFER_XLA", "1") == "1"
    print(f"model: {model.layers[-1].compute_dtype}, XLA {'on' if xla else 'off'}")

    @tf.function(jit_compile=xla)
    def tf_infer(x):
        return tf.cast(model(x, training=False), tf.float32)
    return lambda x: tf_infer(tf.constant(x)).numpy()


def run(video_path, model_path, output_csv, calib=None, margin_px=80.0, heat_threshold=0.5, crop_to_court=False):
    print("Loading model...")
    infer = load_infer(model_path)
    threads = limit_threads()
    timing = {"decode_s": 0.0, "prep_s": 0.0, "wait_s": 0.0, "infer_s": 0.0, "post_s": 0.0}

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
    #
    # Output in calib['calibration_resolution'] when present, not this
    # frame's own resolution -- if this video is a lower-res proxy uploaded
    # to save bandwidth, predictions.csv still needs to land in the same
    # pixel space as calib.json's homography/net_y, since that's what every
    # downstream consumer (build_reel, track_ball, crossing_times) assumes.
    # This keeps that contract true without any of them needing to know a
    # proxy was ever involved.
    cal_res = calib.get("calibration_resolution") if calib else None
    # Taken once, before the loader thread starts: img1/img2/img3 are that thread's working
    # variables and it sets them to None when it reaches the end of the video, while this
    # thread may still be writing the last few results. Anything in the loop below that
    # needs the frame size must use frame_shape, never img1.shape.
    frame_shape = img1.shape
    out_w, out_h = cal_res if cal_res else (img1.shape[1], img1.shape[0])
    x_ratio = out_w / WIDTH
    y_ratio = out_h / HEIGHT
    mask = court_mask(calib, img1.shape, margin_px) if calib else None
    crop = court_crop_box(calib, img1.shape) if (crop_to_court and calib) else None
    if crop:
        print(f"cropping each frame to the court: x {crop[0]}-{crop[2]}, y {crop[1]}-{crop[3]} "
              f"of {img1.shape[1]}x{img1.shape[0]}")
    mask3 = cv2.merge([mask * 255] * 3) if mask is not None else None
    if mask is not None:
        print(f"court mask: keeping {100 * mask.mean():.0f}% of the frame "
              f"(margin {margin_px:.0f}px)")
    print(f"Video: {n_frames} frames @ {fps:.1f} fps = {n_frames / fps:.1f}s, "
          f"x_ratio={x_ratio:.2f} y_ratio={y_ratio:.2f}")

    on_gpu = gpu_prep(mask, crop, frame_shape) if wants_gpu_prep(model_path) else None
    print(f"mask + resize on the {'GPU' if on_gpu else 'CPU'}")
    if on_gpu:
        stage, to_input = on_gpu
    else:
        def stage(trio):
            if mask is not None:
                trio = [apply_mask(im, mask3) for im in trio]
            return prep3(trio, crop)

        def to_input(item):
            return item

    # Trace the tf.function once, outside the timed loop below -- the first
    # call to a @tf.function compiles a graph for that input shape, a
    # one-time cost a real run shouldn't pay per-frame. Uses the already-read
    # first trio (mirroring exactly what the loop's first iteration does) so
    # no frame is skipped or read twice.
    _ = infer(to_input(stage([img1, img2, img3])))

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
        # Set on any consumer-side exception so the producer (which may be
        # blocked on a full frame_q.put()) stops promptly instead of being
        # abandoned mid-block with the VideoCapture still open (found in
        # committee review, 2026-08-26 -- a crash/Ctrl-C mid-run previously
        # skipped producer.join()/cap.release() entirely).
        stop_event = threading.Event()

        def produce():
            nonlocal ok, img1, img2, img3
            try:
                while ok and not stop_event.is_set():
                    t_prep = time.perf_counter()
                    item = stage([img1, img2, img3])
                    timing["prep_s"] += time.perf_counter() - t_prep
                    while True:
                        try:
                            frame_q.put(item, timeout=0.5)
                            break
                        except queue.Full:
                            if stop_event.is_set():
                                return
                    t_decode = time.perf_counter()
                    ok, img1 = cap.read()
                    ok, img2 = cap.read()
                    ok, img3 = cap.read()
                    timing["decode_s"] += time.perf_counter() - t_decode
            except Exception as e:
                producer_error.append(e)
            finally:
                # Must retry until stop_event is set, not give up after one
                # bounded attempt -- a single try (found in committee review,
                # 2026-08-26) can drop the sentinel if the consumer is just
                # transiently slow (GPU stall, disk-flush hiccup), which
                # leaves the consumer's un-timed-out frame_q.get() blocked
                # forever with no producer left alive to unblock it. Retrying
                # until stop_event is set matches the same pattern already
                # used for regular items above, and guarantees delivery on
                # the normal (non-error, non-stop_event) completion path.
                while True:
                    try:
                        frame_q.put(None, timeout=1.0)
                        break
                    except queue.Full:
                        if stop_event.is_set():
                            break

        producer = threading.Thread(target=produce, daemon=True)
        producer.start()

        try:
            while True:
                t_wait = time.perf_counter()
                unit = frame_q.get()
                t_infer = time.perf_counter()
                timing["wait_s"] += t_infer - t_wait
                if unit is None:
                    break
                raw_pred = infer(to_input(unit))
                t_post = time.perf_counter()
                timing["infer_s"] += t_post - t_infer
                mask_pred = (raw_pred > heat_threshold).astype(np.float32)
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
                        if crop:   # the blob is on the crop's grid; the CSV is in the calibration's pixels
                            cxf, cyf = grid_to_calibration(best[0] + best[2] / 2, best[1] + best[3] / 2,
                                                           crop, (WIDTH, HEIGHT), frame_shape, cal_res)
                            cx, cy = int(cxf), int(cyf)
                            bw_ratio, bh_ratio = x_ratio * (crop[2] - crop[0]) / frame_shape[1], y_ratio * (crop[3] - crop[1]) / frame_shape[0]
                        else:
                            cx = int(x_ratio * (best[0] + best[2] / 2))
                            cy = int(y_ratio * (best[1] + best[3] / 2))
                            bw_ratio, bh_ratio = x_ratio, y_ratio
                        writer.writerow([count, 1, cx, cy,
                                         round(bw_ratio * best[2], 1),
                                         round(bh_ratio * best[3], 1),
                                         round(blob_confidence(best_c), 4)])
                    count += 1
                timing["post_s"] += time.perf_counter() - t_post

                if count % 300 == 0:
                    elapsed = time.time() - t0
                    rate = count / elapsed
                    eta = (n_frames - count) / rate
                    print(f"  {count}/{n_frames}  {rate:.0f} fps  ETA {eta / 60:.1f} min", flush=True)
        finally:
            stop_event.set()
            producer.join(timeout=5.0)
            if producer.is_alive():
                # Producer is presumably blocked inside cap.read() itself
                # (not the queue, which the timeout above already handles) --
                # e.g. a stalled network mount or a decoder hang on a corrupt
                # frame. Releasing cap here while that thread may still be
                # calling cap.read() on it is a real race (OpenCV's
                # VideoCapture isn't documented safe for that), so leave it
                # for process exit to clean up instead of racing it.
                print("WARNING: producer thread did not stop within 5s "
                      "(likely stuck in cap.read()) -- skipping cap.release() "
                      "to avoid a concurrent-access race; process exit will "
                      "clean it up.", flush=True)
            else:
                cap.release()

        if producer_error:
            raise producer_error[0]

        elapsed = time.time() - t0
        print(f"\nDone: {count} frames in {elapsed / 60:.1f} min ({count / elapsed:.1f} fps)")
        print(f"Output: {output_csv}")
        # One line for pod_driver to keep in the job's stats: where the time went.
        # wait_s is the GPU loop waiting for decoded frames (CPU-bound if large).
        # decode_s and prep_s run on the decode thread, overlapping the rest.
        # prep_s is the mask + resize when gpu_prep is false; when true it is only
        # copying the needed rows to pinned memory and starting the upload, and
        # the GPU's mask + resize is in infer_s.
        print("TIMING " + json.dumps({"frames": count, "sec": round(elapsed, 1), "fps": round(count / elapsed, 1),
                                      **{k: round(v, 1) for k, v in timing.items()}, **threads,
                                      "gpu_prep": on_gpu is not None}), flush=True)

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
    p.add_argument("--heat-threshold", type=float, default=0.5,
                   help="a pixel counts as ball above this model confidence (default 0.5). "
                        "Each detection's own peak confidence is still written to the Conf "
                        "column, so a run at a lower value can be cut back to a higher one "
                        "afterwards (src/ball_threshold.py).")
    p.add_argument("--crop-to-court", action="store_true",
                   help="send the model only the court and the airspace over it "
                        "(needs --calib; src/court_crop.py), so the far ball shrinks less")
    args = p.parse_args()
    calib = None
    if args.calib:
        import json
        with open(args.calib) as f:
            calib = json.load(f)
    run(args.video, args.model, args.output, calib=calib, margin_px=args.court_margin,
        heat_threshold=args.heat_threshold, crop_to_court=args.crop_to_court)


if __name__ == "__main__":
    main()
