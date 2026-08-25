# Archive — retired code and process

Retired code and process kept for reference, not maintained. Four groups so
far: the YOLO ball-detection pipeline, one superseded calibration tool, one
abandoned workflow template, and one rejected performance experiment.

## YOLO ball-detection pipeline

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

## Superseded calibration tool

- `calibrate_headless.py` — moved here 2026-08-21 (repo-hygiene review). A
  no-display calibration path: save a still frame, type each point's pixel
  coordinates back in by hand after reading them off in an external image
  viewer. `calibrate_web.py` solves the identical no-display problem with a
  browser-click UI instead of hand-typed coordinates and has had real bugs
  found and fixed against it since; this file was untouched and unreferenced
  from the commit that added it onward. If `calibrate_web.py` is ever
  unavailable (no HTTP access to the machine), this is the fallback to revive.

## Abandoned workflow template

- `TALLY.md` — moved here 2026-08-21 (documentation-maintenance review). A
  per-session watch-through template; its own instructions said to copy it to
  `tallies/session-NNN.md` before labeling new footage. Never once done —
  `tallies/` held nothing but a `.gitkeep` after 3+ weeks of near-daily
  footage work, so the directory is gone too. Revive if this project starts
  onboarding new camera setups or operators who'd benefit from a structured
  first-look pass; for this project's own footage, direct playback review has
  been the actual method used throughout (see `CLAUDE.md`'s "Verifying a
  root-cause claim" section).

## Rejected performance experiment

- `pod_infer_batched.py` — moved here 2026-08-25 (`DECISIONS.md` ADR-065).
  Investigating a real inference-throughput regression (23fps vs. a
  documented 58fps benchmark on the same GPU), a live probe suggested the
  GPU was idle waiting on CPU-bound per-frame preprocessing. This script
  tested the fix that theory implied — batch multiple frame-trios into one
  `model.predict()` call — and made things *slower*, not faster, which
  correctly disproved the theory rather than confirming it. The real cause
  (Keras's `.predict()` API itself carries fixed per-call overhead
  independent of batch size) was found afterward and fixed directly in
  `scripts/pod_infer.py` (a `tf.function`-wrapped direct model call). Kept
  as a documented negative result — re-batching this call has already been
  tried and shown not to help, twice (once with `.predict()`, once with
  `tf.function` — see `EXPERIMENTS.md` 2026-08-25).
