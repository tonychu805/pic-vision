# Archive — YOLO Ball-Detection Pipeline

Retired 2026-08-12. The YOLO-based ball detection path produced only 5 crossings
in the benchmark rally window where TrackNet finds 25 (EXPERIMENTS.md 2026-08-12).
TrackNet inference on RunPod GPU is now the default detection route (ADR-046).

**Kept for reference, not active:**
- `yolo_detect.py` — `detect_ball` / `detect_candidates` from `src/ball.py`
- `yolo_pipeline.py` — `detect_rallies` / `rally_segments_from_candidates` from `src/pipeline.py`
- `tests/test_yolo_pipeline.py` — unit tests for the above
- `scan_crossings.py` — moved here 2026-08-20 (`EXPERIMENTS.md`, found by `/committee-review`).
  Imported `detect_candidates` from `src/ball.py`, which had already moved to
  `yolo_detect.py` above when the YOLO path was retired — the import was broken
  (`ImportError` on any invocation) and had been for some time before anyone noticed.
- `debug_detections.py` — moved here 2026-08-20, same finding. Rendered annotated
  frames using a YOLO model's ball detections + net_y overlay. Ran fine (unlike
  `scan_crossings.py`), but visualized the retired detector, not TrackNet — anyone
  using it to debug the active pipeline would have silently gotten the wrong
  detector's output. If TrackNet-based visual debugging is wanted, it should be
  rebuilt against `src/tracknet.py`'s predictions, not resurrected from here.

The backend-agnostic signal-processing functions (`crossing_times`, `cluster_crossings`,
`count_crossings`, `net_line_y`, `ball_box_ok`) remain in `src/ball.py` — both
pipelines use them unchanged.
