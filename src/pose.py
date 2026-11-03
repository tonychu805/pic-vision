"""Player pose on the pod, without ultralytics (badges, 2026-10-27).

The pod image ships torch 2.1 + torchvision but not ultralytics, so the
pose model runs as a TorchScript export of yolov8x-pose (exported inside
that same image, so the TorchScript matches its torch) and this module does
the pre/post-processing ultralytics' `predict` would: letterbox to the
export size, decode boxes + 17 keypoints, class-agnostic NMS, scale back to
the frame. Output per frame matches the pose caches the badge bars were set
on: a list of {"box": [x0,y0,x1,y1], "court": [x_ft, y_ft], "kp": [[x,y,c]*17]}.

Only rally windows are posed (pose_frames), never the whole footage -- pose
is the expensive model and badges only look at rallies.
"""
import cv2
import numpy as np

EXPORT_HW = (736, 1280)        # the TorchScript's fixed input (h, w)
CONF = 0.25                    # ultralytics predict defaults, which the
IOU = 0.7                      # badge bars were measured with
PAD_VALUE = 114
# Batches decoded + letterboxed ahead of the GPU in pose_video. A batch of 8
# 736x1280 uint8 frames is ~22 MB, so this bounds memory at ~90 MB.
PREFETCH_BATCHES = 4
FPS = 30.0
# Frames posed around each rally: the serve happens up to ~1.5 s before the
# first net crossing (First Strike), and the last hit up to ~0.5 s after.
LEAD_SEC = 2.0
TAIL_SEC = 1.0


def pose_frames(segments, n_frames, fps=FPS, lead=LEAD_SEC, tail=TAIL_SEC):
    """Sorted frame indices covering every rally window (start-lead, end+tail)."""
    want = set()
    for s in segments:
        a = max(0, int((s["start"] - lead) * fps))
        b = min(n_frames - 1, int((s["end"] + tail) * fps))
        want.update(range(a, b + 1))
    return sorted(want)


def letterbox(img, hw=EXPORT_HW):
    """Resize keeping aspect ratio, pad centred to hw. Returns (img, scale, (padx, pady))."""
    h, w = img.shape[:2]
    r = min(hw[0] / h, hw[1] / w)
    nh, nw = round(h * r), round(w * r)
    if (nh, nw) != (h, w):
        img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    dh, dw = (hw[0] - nh) / 2, (hw[1] - nw) / 2
    top, bottom = round(dh - 0.1), round(dh + 0.1)
    left, right = round(dw - 0.1), round(dw + 0.1)
    img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(PAD_VALUE,) * 3)
    return img, r, (left, top)


def decode(pred, scale, pad, conf=CONF, iou=IOU):
    """One frame's raw output (56, N) tensor -> list of (box xyxy, kps 17x3), frame coordinates."""
    import torch
    import torchvision

    p = pred.transpose(0, 1)                      # (N, 56)
    p = p[p[:, 4] > conf]
    if not len(p):
        return []
    cx, cy, bw, bh = p[:, 0], p[:, 1], p[:, 2], p[:, 3]
    boxes = torch.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], 1)
    keep = torchvision.ops.nms(boxes, p[:, 4], iou)
    boxes, kps = boxes[keep], p[keep, 5:].reshape(-1, 17, 3)
    px, py = pad
    boxes[:, [0, 2]] = (boxes[:, [0, 2]] - px) / scale
    boxes[:, [1, 3]] = (boxes[:, [1, 3]] - py) / scale
    kps = kps.clone()
    kps[..., 0] = (kps[..., 0] - px) / scale
    kps[..., 1] = (kps[..., 1] - py) / scale
    return list(zip(boxes.cpu().numpy(), kps.cpu().numpy()))


class PoseModel:
    def __init__(self, path, device="cuda", half=True):
        import torch
        self.torch = torch
        self.device = device
        torch.backends.cudnn.benchmark = True          # one fixed input shape
        self.model = torch.jit.load(path, map_location=device).eval()
        # fp16 is ~1.6x faster on the pod's Ada cards; boxes/keypoints move
        # by at most a couple of pixels (measured 2026-10-27).
        self.half = half and device != "cpu"
        if self.half:
            self.model = self.model.half()

    def __call__(self, frames):
        """BGR frames (same size) -> per frame a list of (box, kps)."""
        return self.infer(self.prepare(frames))

    # The two halves of __call__, so pose_video can run them on different
    # threads: prepare is CPU only (and cv2 releases the GIL), infer is the GPU.
    def prepare(self, frames):
        """Letterboxed RGB NCHW uint8 batch + each frame's (scale, pad)."""
        boxed = [letterbox(f) for f in frames]
        x = np.ascontiguousarray(np.stack([b[0][..., ::-1] for b in boxed]).transpose(0, 3, 1, 2))
        return x, [(b[1], b[2]) for b in boxed]

    def infer(self, prepared):
        torch = self.torch
        x, meta = prepared
        x = torch.from_numpy(x).to(self.device).float() / 255.0
        with torch.no_grad():
            out = self.model(x.half() if self.half else x)
        out = (out[0] if isinstance(out, (list, tuple)) else out).float()
        return [decode(out[i], scale, pad) for i, (scale, pad) in enumerate(meta)]


def to_court(H, box):
    """Feet point (box bottom-centre) through the image->court homography."""
    v = H @ np.array([(box[0] + box[2]) / 2, box[3], 1.0])
    return [float(v[0] / v[2]), float(v[1] / v[2])]


def _batches(video, frames, batch):
    """(frame numbers, BGR images) in batches of `batch`, read sequentially.

    grab() past unwanted frames is cheap next to decoding them, so a sparse
    rally set doesn't pay for random seeks."""
    want = set(frames)
    cap = cv2.VideoCapture(video)
    last = frames[-1]
    buf, idx, f = [], [], 0
    try:
        while f <= last:
            if f in want:
                ok, img = cap.read()
                if not ok:
                    break
                buf.append(img)
                idx.append(f)
                if len(buf) == batch:
                    yield idx, buf
                    buf, idx = [], []
            elif not cap.grab():
                break
            f += 1
        if buf:
            yield idx, buf
    finally:
        cap.release()


def pose_video(video, frames, model, H, batch=8, progress=None):
    """Pose the given frame indices of `video`. Returns {str(frame): [person, ...]}.

    Decoding and letterboxing run on a background thread, a few batches ahead
    of the GPU (2026-10-29). Done in turn, as before, the GPU sat idle while
    the CPU worked and vice versa: production pods posed at 25-28 fps on
    cards that manage far more, and pose was ~2:40 of every 5-min part,
    which put one machine behind real time. Same batches in the same order,
    so the output is identical to the serial version.
    """
    out = {}
    if not frames:
        return out

    def keep(idx, people_per_frame):
        for fn, people in zip(idx, people_per_frame):
            out[str(fn)] = [{"box": [float(v) for v in b], "court": to_court(H, b),
                             "kp": [[float(k[0]), float(k[1]), float(k[2])] for k in kp]}
                            for b, kp in people]
        if progress:
            progress(len(out), len(frames))

    if not hasattr(model, "prepare"):
        # A plain callable (tests, or a model without the split): serially.
        for idx, imgs in _batches(video, frames, batch):
            keep(idx, model(imgs))
        return out

    import queue
    import threading
    q = queue.Queue(maxsize=PREFETCH_BATCHES)
    stop = threading.Event()
    DONE = object()

    def put(item):
        """Hand over, unless the consumer has stopped (it may never read again)."""
        while not stop.is_set():
            try:
                q.put(item, timeout=0.5)
                return True
            except queue.Full:
                continue
        return False

    def produce():
        try:
            for idx, imgs in _batches(video, frames, batch):
                if not put((idx, model.prepare(imgs))):
                    return
            put(DONE)
        except BaseException as e:      # handed to the consumer, re-raised there
            put(e)

    worker = threading.Thread(target=produce, name="pose-prefetch", daemon=True)
    worker.start()
    try:
        while True:
            item = q.get()
            if item is DONE:
                break
            if isinstance(item, BaseException):
                raise item
            idx, prepared = item
            keep(idx, model.infer(prepared))
    finally:
        stop.set()
        worker.join(timeout=5)
    return out
