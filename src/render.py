"""Cut detected rally segments into highlight clips (TECH_SPEC §8).

Turns a list of segments (from segment.py / the crossing pipeline) into actual
watchable H.264 clips plus a manifest keyed by court + session + time — the
browse-ready output the venue console / player app read. H.264 (not OpenCV's
mp4v) so the clips play inline everywhere."""

import json
import logging
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)


PROBE_WINDOW_SEC = 60


def probe_fps(video, default=30.0):
    """The video's real frame rate, measured from packet timestamps.

    Everything downstream turns frame numbers into timestamps and judges how
    far a ball can travel between frames, and both were hardcoded to 30 --
    correct only because the CFR conversion forces 30, which in turn only
    became true by duplicating frames on a camera streaming slower.

    Deliberately NOT read from the stream's declared `r_frame_rate` or
    `avg_frame_rate`. capture.js records with `-c copy`, so the container
    inherits whatever rate the *camera declares* rather than what it sent:
    a real recording here declares 30/1 in both fields while containing
    exactly 9,000 frames in 600s (15.00 fps). Trusting either field would
    silently return 30 for a 15fps camera, which is precisely the case this
    exists to catch.

    Counting packets rather than frames keeps it cheap -- no decoding -- and
    bounding it to the first minute keeps it O(1) on a two-hour session.
    Falls back to `default` on any probe failure or implausible result, so a
    bad probe degrades to today's behaviour instead of producing an absurd
    threshold."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-read_intervals", f"%+{PROBE_WINDOW_SEC}",
             "-show_entries", "packet=pts_time", "-of", "csv=p=0", video],
            capture_output=True, text=True, check=True).stdout
        times = sorted(float(t) for t in out.split() if t and t != "N/A")
        span = times[-1] - times[0]
        fps = (len(times) - 1) / span
    except Exception as e:  # noqa: BLE001 - a probe failure must not fail a job
        log.warning("could not probe frame rate of %s (%s); assuming %.1f", video, e, default)
        return default
    if not 1.0 <= fps <= 240.0:
        log.warning("implausible frame rate %.3f from %s; assuming %.1f", fps, video, default)
        return default
    log.info("%s: measured %.2f fps over %.1fs", os.path.basename(video), fps, span)
    return fps


# Venue logo in the lower-right corner, sized against the video so a 720p
# camera gets the same look as a 1080p one: 8% of the frame's width, inset
# 1/60th of it (32px at 1920), corners rounded at 12% of the logo's width.
# Chosen by eye on a real PGC clip, 2026-09-23.
LOGO_WIDTH_FRAC = 0.08
LOGO_MARGIN_FRAC = 1 / 60
LOGO_RADIUS_FRAC = 0.12


def logo_filter(video_width):
    """filter_complex placing input 1 (the logo image) over input 0.

    Trims a 1px edge off the logo first: uploads often carry a stray
    border line (PGC's did) that reads as a hairline on one side once the
    corners are rounded. The alpha mask is antialiased by a half-pixel so
    the rounded edge isn't stair-stepped. The logo is a still image, so
    this all runs once per clip, not per frame -- overlay just repeats it."""
    w = max(2, round(video_width * LOGO_WIDTH_FRAC / 2) * 2)
    m = round(video_width * LOGO_MARGIN_FRAC)
    r = round(w * LOGO_RADIUS_FRAC)
    corner = (f"hypot(max(0,{r}-min(X+0.5,W-X-0.5)),"
              f"max(0,{r}-min(Y+0.5,H-Y-0.5)))")
    return (f"[1]crop=iw-2:ih-2:1:1,scale={w}:-2:flags=lanczos,format=rgba,"
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='255*clip({r}+0.5-{corner},0,1)'[logo];"
            f"[0][logo]overlay=W-w-{m}:H-h-{m}")


# Clip encoders (2026-10-27: cutting took up to 2.5 min of a part on the pod,
# every clip encoded one after another on its CPU). NVENC where the GPU and
# ffmpeg build allow it -- the same settings pod_driver's convert step has
# used since 2026-09-21 -- and libx264 otherwise; both yuv420p H.264, so
# clips concatenate with -c copy either way.
ENCODERS = {
    "nvenc": ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23", "-pix_fmt", "yuv420p"],
    "cpu": ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"],
}
# Clips encoded at once. Short clips spend much of their time starting ffmpeg
# and seeking, which overlaps well; 4 stays inside consumer cards' NVENC
# session limit.
CUT_WORKERS = 4
_encoder = None
# Clips already cut in this process, by (video, start, end, logo): the full
# reel and the per-rally clips cut the same padded stretches, so with every
# rally clipped (badges on) the full reel's ~10 clips were encoded twice.
# A repeat is hard-linked (or copied) instead of re-encoded.
_cut_cache = {}


def clip_encoder():
    """"nvenc" or "cpu": PIC_VISION_ENCODER if set, else whether a one-frame
    NVENC encode works here. Decided once per process."""
    global _encoder
    if _encoder is None:
        forced = os.environ.get("PIC_VISION_ENCODER")
        if forced in ENCODERS:
            _encoder = forced
        else:
            probe = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=256x144:d=0.1:r=30",
                                    *ENCODERS["nvenc"], "-f", "null", "-"], capture_output=True)
            _encoder = "nvenc" if probe.returncode == 0 else "cpu"
        log.info("clip encoder: %s", _encoder)
    return _encoder


def clip_command(video, start, end, out_path, logo_path=None, video_width=None, encoder="cpu"):
    """ffmpeg command to cut [start, end] (seconds) of video into an H.264 clip.
    Re-encodes for frame-accurate boundaries; drops audio for now.

    With logo_path (and the source's video_width), the logo is burnt in
    during that same encode -- no second pass. encoder: a key of ENCODERS."""
    duration = end - start
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start}", "-i", video]
    if logo_path:
        # Before -t: an -i after it would make -t apply to the logo input.
        cmd += ["-i", logo_path, "-filter_complex", logo_filter(video_width)]
    return cmd + [
        "-t", f"{duration}",
        *ENCODERS[encoder],
        "-movflags", "+faststart", "-an", out_path,
    ]


def _encode_clip(video, start, end, out_path, logo_path, video_width):
    """One clip on the chosen encoder; an NVENC failure falls back to the CPU
    for this clip and every later one (a host that can't open an encode
    session mid-run won't recover)."""
    global _encoder
    enc = clip_encoder()
    r = subprocess.run(clip_command(video, start, end, out_path, logo_path, video_width, enc), capture_output=True, text=True)
    if r.returncode != 0 and enc == "nvenc" and "nvenc" in (r.stderr or "").lower():
        log.warning("NVENC failed mid-run, cutting on the CPU from here: %s", r.stderr.strip()[-200:])
        _encoder = "cpu"
        r = subprocess.run(clip_command(video, start, end, out_path, logo_path, video_width, "cpu"), capture_output=True, text=True)
    if r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, r.args, r.stdout, r.stderr)


def probe_width(video):
    """The video stream's width in pixels."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width", "-of", "csv=p=0", video],
        capture_output=True, text=True, check=True).stdout
    return int(out.strip())


def probe_duration(video):
    """A file's real duration in seconds, read back rather than assumed."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video],
        capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def manifest_entry(seg, rally_id, file, court_id=None, session_id=None):
    """One browse-ready record for a cut clip: court + session + time + score."""
    return {
        "rally_id": rally_id,
        "court_id": court_id,
        "session_id": session_id,
        "start": seg["start"],
        "end": seg["end"],
        "duration": seg["end"] - seg["start"],
        "score": seg.get("score"),
        "file": file,
        **({"rally_start": seg["rally_start"], "rally_end": seg["rally_end"]} if "rally_start" in seg else {}),
    }


def concat_clips(manifest, out_dir):
    """Concatenate all rally clips in manifest into highlight.mp4 in out_dir.
    Returns the output path, or None if manifest is empty."""
    if not manifest:
        return None
    filelist = os.path.join(out_dir, "_filelist.txt")
    with open(filelist, "w") as f:
        for entry in manifest:
            f.write(f"file '{entry['file']}'\n")
    out_path = os.path.join(out_dir, "highlight.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "concat", "-safe", "0",
        "-i", filelist, "-c", "copy", out_path,
    ], check=True)
    os.remove(filelist)
    return out_path


def cut_clips(video, segments, out_dir, court_id=None, session_id=None,
              pad_sec=3.0, logo_path=None):
    """Cut each segment into an H.264 clip in out_dir and write manifest.json.
    pad_sec adds context before/after each crossing burst so clips are watchable.
    logo_path, if given, is burnt into every clip's lower-right corner -- and
    so into every reel concatenated from them, since those are `-c copy`.
    Returns the manifest (list of manifest_entry dicts, sorted by start)."""
    os.makedirs(out_dir, exist_ok=True)
    video_width = probe_width(video) if logo_path and segments else None
    sorted_segs = sorted(segments, key=lambda s: s["start"])
    n = len(sorted_segs)
    jobs = []
    for i, seg in enumerate(sorted_segs, 1):
        fname = f"rally_{i:03d}.mp4"
        start = max(0.0, seg["start"] - pad_sec)
        end = seg["end"] + pad_sec
        log.info("[%d/%d] %.1f–%.1fs  (%.1fs, %d crossings)",
                 i, n, start, end, end - start, seg.get("crossings", 0))
        jobs.append((i, seg, fname, start, end, os.path.join(out_dir, fname)))
    key = lambda j: (os.path.abspath(video), round(j[3], 3), round(j[4], 3), logo_path)
    fresh = []
    for j in jobs:
        done = _cut_cache.get(key(j))
        if done and os.path.exists(done):
            if os.path.exists(j[5]):
                os.remove(j[5])
            try:
                os.link(done, j[5])
            except OSError:
                shutil.copyfile(done, j[5])
        else:
            fresh.append(j)
    if len(fresh) < len(jobs):
        log.info("reused %d already-cut clips", len(jobs) - len(fresh))
    with ThreadPoolExecutor(max_workers=CUT_WORKERS) as pool:
        list(pool.map(lambda j: _encode_clip(video, j[3], j[4], j[5], logo_path, video_width), fresh))
    for j in fresh:
        _cut_cache[key(j)] = j[5]
    manifest = []
    for i, seg, fname, start, end, out_path in jobs:
        # The padded start/end actually requested, EXCEPT end is corrected
        # to the file's own real duration rather than trusted as cut --
        # a rally within pad_sec of the source video's own end asks ffmpeg
        # to cut past where the video actually stops, and ffmpeg just ends
        # the file early there rather than failing. Reading the real
        # duration back (same idea as probe_width above) catches that and
        # any other reason the real file might be shorter than requested,
        # instead of assuming the request is what landed. Needed because
        # manifest_entry's own docstring calls this "a browse-ready record
        # ... for a cut clip" -- it must describe the file, not the ask.
        # Nothing read this distinction closely before Stage 3 (pic-vision's
        # pod_driver.py) started persisting it as a rally's
        # part_start_sec/part_end_sec, which a desktop now trims its own
        # local high-res recording to.
        real_end = start + probe_duration(out_path)
        manifest.append(manifest_entry({**seg, "start": start, "end": real_end}, i, fname, court_id, session_id))
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump({"video": video, "court_id": court_id, "session_id": session_id,
                   "clips": manifest}, f, indent=2)
    log.info("wrote %d clips + manifest.json -> %s", n, out_dir)
    return manifest
