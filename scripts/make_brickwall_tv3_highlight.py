"""Build a ~2-minute highlight reel from the TrackNetV3 brickwall result
(2026-08-21, PIC-47: 0.694 precision / 0.971 recall) so it can be sanity-
checked by playback, not just precision/recall numbers.

No ranking/selection logic is built yet (PROGRESS.md: "Not built ... Phase 1,
still gated on precision") -- this picks the top-scoring detected segments by
crossing count (the only proxy score cut.py already uses) until the padded
total hits ~2 minutes, then cuts+concats those, in chronological order.
"""
import json

from src.calib import court_wedge
from src.ball import net_line_y
from src.tracknet import rally_segments_from_predictions
from src.render import cut_clips, concat_clips

VIDEO = "videos/brickwall_30fps.mp4"
CSV = "/mnt/fast_scratch/tv3_work/brickwall_pred/brickwall_30fps_ball.csv"
CALIB = "calib/brickwall_30fps_calib.json"
OUT_DIR = "clips/brickwall_tv3_2min"
FPS = 30.0
GAP_SEC = 3.0
MIN_CROSSINGS = 6
PAD_SEC = 3.0
TARGET_SEC = 120.0

with open(CALIB) as f:
    calib = json.load(f)
net_y = net_line_y(calib)
in_court = court_wedge(calib)

segments = rally_segments_from_predictions(
    CSV, FPS, net_y,
    gap_sec=GAP_SEC, min_crossings=MIN_CROSSINGS,
    in_court=in_court,
)
print(f"{len(segments)} candidate rally segments detected")

# Rank by crossing count (proxy score already used in src/cut.py), pick a
# top set whose padded duration sums to ~TARGET_SEC.
ranked = sorted(segments, key=lambda s: -s["crossings"])
chosen = []
total = 0.0
for s in ranked:
    dur = (s["end"] - s["start"]) + 2 * PAD_SEC
    if total + dur > TARGET_SEC and chosen:
        continue
    chosen.append(s)
    total += dur
    if total >= TARGET_SEC:
        break

print(f"chose {len(chosen)} clips, ~{total:.1f}s padded total")

scored = [{**s, "score": s["crossings"]} for s in chosen]
manifest = cut_clips(VIDEO, scored, OUT_DIR, court_id="brickwall", session_id="tv3_2min", pad_sec=PAD_SEC)
out = concat_clips(manifest, OUT_DIR)
print(f"highlight -> {out}")
