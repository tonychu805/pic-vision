"""Cut detected rally segments into highlight clips (TECH_SPEC §8).

Turns a list of segments (from segment.py / the crossing pipeline) into actual
watchable H.264 clips plus a manifest keyed by court + session + time — the
browse-ready output the venue console / player app read. H.264 (not OpenCV's
mp4v) so the clips play inline everywhere."""

import json
import logging
import os
import subprocess

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


def clip_command(video, start, end, out_path, logo_path=None, video_width=None):
    """ffmpeg command to cut [start, end] (seconds) of video into an H.264 clip.
    Re-encodes for frame-accurate boundaries; drops audio for now.

    With logo_path (and the source's video_width), the logo is burnt in
    during that same encode -- no second pass."""
    duration = end - start
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start}", "-i", video]
    if logo_path:
        # Before -t: an -i after it would make -t apply to the logo input.
        cmd += ["-i", logo_path, "-filter_complex", logo_filter(video_width)]
    return cmd + [
        "-t", f"{duration}",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-an", out_path,
    ]


def probe_width(video):
    """The video stream's width in pixels."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width", "-of", "csv=p=0", video],
        capture_output=True, text=True, check=True).stdout
    return int(out.strip())


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
    manifest = []
    for i, seg in enumerate(sorted_segs, 1):
        fname = f"rally_{i:03d}.mp4"
        start = max(0.0, seg["start"] - pad_sec)
        end = seg["end"] + pad_sec
        log.info("[%d/%d] %.1f–%.1fs  (%.1fs, %d crossings)",
                 i, n, start, end, end - start, seg.get("crossings", 0))
        subprocess.run(clip_command(video, start, end, os.path.join(out_dir, fname),
                                    logo_path=logo_path, video_width=video_width), check=True)
        manifest.append(manifest_entry(seg, i, fname, court_id, session_id))
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump({"video": video, "court_id": court_id, "session_id": session_id,
                   "clips": manifest}, f, indent=2)
    log.info("wrote %d clips + manifest.json -> %s", n, out_dir)
    return manifest
