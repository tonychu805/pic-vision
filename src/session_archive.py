"""The redacted copy of a part that is kept after its reels are made (operator decisions 2026-11-15,
../pic-vision-redaction/docs/redacted-archive-design.md).

Every face is blurred, players included, and nothing else (operator, 2026-11-15: faces, not zones). Two finders,
because YuNet alone misses most small or turned-away faces on court: every posed person's head (the hit finder's
poses, every 2nd frame, whole frame and far close-up; a frame between two posed frames takes both neighbours'
people) and every face YuNet finds (scanned every 6th frame, the last boxes held between scans; YuNet is most of
the time). Heads get a wider box than the Jev sheets' because
hair showed above it on near players (Run A, 2026-11-15).

All or nothing: a part is refused unless every frame was decoded, redacted and encoded. Nothing here ever falls
back to keeping unblurred footage."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from src import jev_sheet

FPS = 30
FACE_EVERY = 6
POSE_STRIDE = 2
VERSION = "archive-v2-faces"


class ArchiveRefused(Exception):
    """This part can't be archived fully redacted; nothing is kept."""


def check_pose_coverage(poses, n_frames, stride=POSE_STRIDE):
    """Raise unless every `stride`-th frame of the part was posed: the head blur depends on it."""
    missing = [f for f in range(0, n_frames, stride) if str(f) not in poses]
    if missing:
        raise ArchiveRefused(f"no poses for {len(missing)} of {len(range(0, n_frames, stride))} sampled frames "
                             f"(first {missing[0]})")


def people_at(poses, f):
    if str(f) in poses:
        return poses[str(f)]
    return poses.get(str(f - 1), []) + poses.get(str(f + 1), [])


def archive_boxes(people, faces, scale, w, h):
    """Head boxes widened and raised to cover hair, plus face boxes; all in output pixels."""
    scaled = [{"box": [v * scale for v in p["box"]], "kp": [[k[0] * scale, k[1] * scale, k[2]] for k in p["kp"]]}
              for p in people]
    out = []
    for x0, y0, x1, y1 in jev_sheet.head_boxes(scaled, w, h):
        bw, bh = x1 - x0, y1 - y0
        out.append((max(0, int(x0 - 0.5 * bw)), max(0, int(y0 - 0.8 * bh)),
                    min(w, int(x1 + 0.5 * bw)), min(h, int(y1 + 0.2 * bh))))
    return out + list(faces)


def frame_count(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                        "-show_entries", "stream=nb_read_packets,width,height", "-of", "csv=p=0", path],
                       capture_output=True, text=True, check=True)
    w, h, n = (int(v) for v in r.stdout.strip().split(",")[:3])
    return n, w, h


def blur_boxes(frame, boxes):
    out = frame.copy()
    for x0, y0, x1, y1 in boxes:
        if x1 > x0 and y1 > y0:
            out[y0:y1, x0:x1] = jev_sheet._soften(out[y0:y1, x0:x1], 8)
    return out


def _redact_range(job):
    """Redact frames [start, start+count) into its own file; returns frames written."""
    start, count, part_path = job["start"], job["count"], job["path"]
    src, poses, in_h, out_w, out_h, encoders = job["src"], job["poses"], job["in_h"], job["out_w"], job["out_h"], job["encoders"]
    cv2.setNumThreads(1)
    yunet = cv2.FaceDetectorYN.create(jev_sheet.YUNET, "", (out_w, out_h), 0.35, 0.3, 5000)
    scale = out_h / in_h
    last_err = None
    for enc in encoders:
        dec = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{start / FPS:.6f}", "-i", src, "-frames:v", str(count),
                                "-vf", f"scale={out_w}:{out_h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                               stdout=subprocess.PIPE)
        # A bitrate cap, not a quality target, for NVENC: -cq 26 gave 1.6 Mbit/s (122 MB per 10 min) on staging,
        # 3x libx264 -crf 26. 0.6 Mbit/s is about 45 MB per 10 min.
        quality = ["-b:v", "600k", "-maxrate", "800k", "-bufsize", "1600k", "-preset", "p4"] if "nvenc" in enc \
            else ["-crf", "26", "-preset", "veryfast"]
        out = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                                "-s", f"{out_w}x{out_h}", "-r", str(FPS), "-i", "-", "-an", "-c:v", enc, *quality,
                                "-pix_fmt", "yuv420p", part_path],
                               stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        size, faces, done = out_w * out_h * 3, [], 0
        try:
            while done < count:
                buf = dec.stdout.read(size)
                if len(buf) < size:
                    break
                frame = np.frombuffer(buf, np.uint8).reshape(out_h, out_w, 3)
                f = start + done
                if done % FACE_EVERY == 0:
                    _, det = yunet.detect(frame)
                    faces = jev_sheet.face_boxes(det, out_w, out_h) or faces
                boxes = archive_boxes(people_at(poses, f), faces, scale, out_w, out_h)
                out.stdin.write(np.ascontiguousarray(blur_boxes(frame, boxes)).tobytes())
                done += 1
            out.stdin.close()
        except BrokenPipeError:
            pass
        dec.stdout.close()
        dec.wait()
        err = out.stderr.read().decode(errors="replace")
        if out.wait() == 0 and done == count:
            return done
        last_err = f"{enc}: frames {start}-{start + count}: wrote {done} of {count}: {err.strip()[-300:]}"
    raise ArchiveRefused(last_err)


def _run_worker(job):
    spec = job["path"] + ".json"
    with open(spec, "w") as fh:
        json.dump({**job, "encoders": list(job["encoders"])}, fh)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, "-m", "src.session_archive", spec], cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        raise ArchiveRefused(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else f"worker exited {r.returncode}")
    return int(r.stdout.strip().splitlines()[-1])


def redact_video(src, dst, poses, out_height=720, workers=None, encoders=("h264_nvenc", "libx264")):
    """Write the fully redacted copy of `src` to `dst`. Returns {frames, seconds, bytes, version}.

    Raises ArchiveRefused, leaving no `dst`, unless every frame made it through."""
    n, in_w, in_h = frame_count(src)
    check_pose_coverage(poses, n)
    out_h = min(out_height, in_h)
    out_w = int(round(in_w * out_h / in_h / 2)) * 2
    workers = max(1, min(workers or os.cpu_count() or 1, n))
    bounds = np.linspace(0, n, workers + 1).astype(int)
    tmp = tempfile.mkdtemp(prefix="archive-", dir=os.path.dirname(os.path.abspath(dst)))
    try:
        ranges = [{"start": int(a), "count": int(b - a), "path": os.path.join(tmp, f"{i:03d}.mp4"), "src": src,
                   "in_h": in_h, "out_w": out_w, "out_h": out_h, "encoders": tuple(encoders),
                   "poses": {k: v for k, v in poses.items() if a - 1 <= int(k) <= b}}
                  for i, (a, b) in enumerate(zip(bounds, bounds[1:]))]
        # Each range runs as its own program, not a forked or spawned child: the pod's process already runs threads
        # (torch, Jev, uploads) a fork can deadlock on, and spawn re-imports pod_driver.py, which needs a job.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            written = sum(pool.map(_run_worker, ranges))
        if written != n:
            raise ArchiveRefused(f"redacted {written} of {n} frames")
        listing = os.path.join(tmp, "parts.txt")
        with open(listing, "w") as fh:
            fh.writelines(f"file '{r['path']}'\n" for r in ranges)
        joined = os.path.join(tmp, "joined.mp4")
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", listing,
                            "-c", "copy", "-movflags", "+faststart", joined], capture_output=True, text=True)
        if r.returncode != 0:
            raise ArchiveRefused(f"joining the redacted pieces failed: {r.stderr.strip()[-300:]}")
        got, _, _ = frame_count(joined)
        if got != n:
            raise ArchiveRefused(f"the joined copy has {got} of {n} frames")
        shutil.move(joined, dst)
        return {"frames": n, "seconds": round(n / FPS, 2), "bytes": os.path.getsize(dst), "version": VERSION}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    try:
        print(_redact_range(json.load(open(sys.argv[1]))))
    except ArchiveRefused as e:
        sys.exit(f"ArchiveRefused: {e}")
