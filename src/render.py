"""Cut detected rally segments into highlight clips (TECH_SPEC §8).

Turns a list of segments (from segment.py / the crossing pipeline) into actual
watchable H.264 clips plus a manifest keyed by court + session + time — the
browse-ready output the venue console / player app read. H.264 (not OpenCV's
mp4v) so the clips play inline everywhere."""

import json
import os
import subprocess


def clip_command(video, start, end, out_path):
    """ffmpeg command to cut [start, end] (seconds) of video into an H.264 clip.
    Re-encodes for frame-accurate boundaries; drops audio for now."""
    duration = end - start
    return [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{start}", "-i", video, "-t", f"{duration}",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-an", out_path,
    ]


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


def cut_clips(video, segments, out_dir, court_id=None, session_id=None):
    """Cut each segment into an H.264 clip in out_dir and write manifest.json.
    Returns the manifest (list of manifest_entry dicts, sorted by start)."""
    os.makedirs(out_dir, exist_ok=True)
    manifest = []
    for i, seg in enumerate(sorted(segments, key=lambda s: s["start"]), 1):
        fname = f"rally_{i:03d}.mp4"
        subprocess.run(clip_command(video, seg["start"], seg["end"],
                                    os.path.join(out_dir, fname)), check=True)
        manifest.append(manifest_entry(seg, i, fname, court_id, session_id))
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump({"video": video, "court_id": court_id, "session_id": session_id,
                   "clips": manifest}, f, indent=2)
    return manifest
