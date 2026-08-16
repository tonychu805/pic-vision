"""Gemini Flash video verification for cut rally clips.

crossing-count heuristics (min_crossings, gap_sec) can't tell a real rally
apart from warmup/dead-time or a mid-rally lull from a point break — see
project memory project-tracknet-false-positive, "warmup vs real rally" and
"gap_sec fragmentation" notes. This asks a video-understanding model to
actually watch each cut clip and judge it directly, as a check on those
heuristics, not a replacement for them.

Requires GOOGLE_API_KEY in the environment (see .env.example).
"""

import json
import logging
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"

PROMPT = """You are reviewing a short clip auto-cut from pickleball footage by
a ball-tracking pipeline. Decide whether this clip shows ACTIVE RALLY PLAY
(players actively hitting the ball back and forth across the net) or NOT
(dead time between points, players resetting/walking/warming up, or just a
serve with no sustained return).

Respond with strict JSON only, no markdown fences, matching exactly this
shape: {"is_rally": true or false, "confidence": a number from 0.0 to 1.0,
"reason": "one sentence"}"""


def _client():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set — copy .env.example to .env and fill it in")
    return genai.Client(api_key=api_key)


def verify_clip(video_path, model=DEFAULT_MODEL):
    """Ask Gemini Flash whether video_path shows real rally play.

    Returns {"is_rally": bool, "confidence": float, "reason": str}. Raises on
    API or parse errors rather than guessing — a broken verifier should fail
    loudly, not silently pass every clip through.
    """
    with open(video_path, "rb") as f:
        video_bytes = f.read()

    client = _client()  # keep a reference alive — a temporary Client can get
                        # garbage-collected (closing its HTTP client) before
                        # the request fires
    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=video_bytes, mime_type="video/mp4"),
            PROMPT,
        ],
    )
    return json.loads(response.text.strip())


def verify_clips(video_paths, model=DEFAULT_MODEL):
    """Verify multiple clips in sequence. Returns {path: verdict}."""
    results = {}
    for path in video_paths:
        log.info("verifying %s ...", path)
        verdict = verify_clip(path, model=model)
        log.info("  -> is_rally=%s confidence=%.2f (%s)",
                 verdict["is_rally"], verdict["confidence"], verdict["reason"])
        results[path] = verdict
    return results


def main(argv=None):
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description="Verify cut clips with Gemini Flash.")
    p.add_argument("clips", nargs="+", help="Path(s) to cut rally clip mp4s.")
    p.add_argument("--model", default=DEFAULT_MODEL)
    args = p.parse_args(argv)
    verify_clips(args.clips, model=args.model)


if __name__ == "__main__":
    main()
