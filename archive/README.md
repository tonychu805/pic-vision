# Archive — YOLO Ball-Detection Pipeline

Retired 2026-08-12. The YOLO-based ball detection path produced only 5 crossings
in the benchmark rally window where TrackNet finds 25 (EXPERIMENTS.md 2026-08-12).
TrackNet inference on RunPod GPU is now the default detection route (ADR-046).

**Kept for reference, not active:**
- `yolo_detect.py` — `detect_ball` / `detect_candidates` from `src/ball.py`
- `yolo_pipeline.py` — `detect_rallies` / `rally_segments_from_candidates` from `src/pipeline.py`
- `tests/test_yolo_pipeline.py` — unit tests for the above

The backend-agnostic signal-processing functions (`crossing_times`, `cluster_crossings`,
`count_crossings`, `net_line_y`, `ball_box_ok`) remain in `src/ball.py` — both
pipelines use them unchanged.
