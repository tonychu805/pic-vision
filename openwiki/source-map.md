---
type: Source Map
title: Source Map — file-by-file orientation
description: File-level map of the pic-vision repository — every source module, entry point, test, label file, and root document, with what exists versus what is planned but unbuilt (TECH_SPEC §12 target layout).
tags: [source-map, navigation, files]
resource: TECH_SPEC.md
---

# Source Map

Files appear as phases land — nothing is stubbed ahead of time (README §Pipeline). This map shows what exists at HEAD versus the TECH_SPEC §12 target layout.

## Executable entry points (exist)

| File | Role |
|---|---|
| `calibrate.py` | Click 12 court points (any order) + 2 net-tape points → `court_calibration.json` (homography, RMSE ft, `net_image_points`). OpenCV GUI; core math in `compute_calibration` / order-independent assignment helpers. |
| `label.py` | Rally interval labeler → JSONL. `--review` mode replays segments for keep/drop curation. Timestamps from PTS (`CAP_PROP_POS_MSEC`). |

**Planned, not built:** `cut.py` (single-command orchestrator, NFR7) and `src/capture.py` (preflight + RTSP recording — the procedure lives in [Operations](operations/runbook.md#capture-pitfalls)).

## `src/` — detection library

| File | Path | Contents |
|---|---|---|
| `ball.py` | v1 | `detect_candidates` / `detect_ball` (yolov8x, class 32, `imgsz=1280`, lazy ultralytics import), `ball_box_ok` size/aspect filter, `net_line_y` (marked-net preferred) / `net_image_y` (homography fallback), `crossing_times` / `count_crossings` (hysteresis side-flip), `cluster_crossings` (bursts → segments, courtesy-return suppression via `min_crossings`). |
| `track.py` | v1 | `track_ball` — single-ball nearest-neighbour tracker, teleport rejection (`max_jump`), re-acquire after `reset_after` gaps. Kills phantom dead-time crossings from other courts' balls. |
| `players.py` | v0 | `detect_players` (YOLOv8n person, sampled), `foot_point`, `to_court` (homography → court feet), `on_court` (asymmetric margin filter), `court_positions`, `load_calibration`. |
| `events.py` | v0 | `mean_motion` / `motion_series` (tracking-free displacement), `n_at_kitchen` / `kitchen_series` (NVZ-formation marker; `KITCHEN_LINES = (15, 29)` ft). |
| `segment.py` | shared | `segment(series, threshold, gap_sec, min_dur_sec)` — signal-agnostic gap-tolerant min-duration segmenter. |
| `render.py` | shared | `clip_command` (ffmpeg → libx264/faststart, audio dropped for now), `cut_clips` (segments → `rally_NNN.mp4` + `manifest.json` keyed by court/session/time). |

**Planned, not built:** `motion.py` (T0′ CPU pre-filter), `select.py` (rank + budget selection, TECH_SPEC §7), `audio.py` (gated spectral-flux onsets, §5.1b). The v0-vs-v1 meaning of each module: [Architecture](architecture/overview.md#the-v0v1-split-adr-039--the-most-important-structural-fact).

## `eval/`

- `eval/harness.py` — IoU, greedy one-to-one matching, detection + selection metric tables, CLI (`make eval`). Details: [Testing & Evaluation](testing/evaluation.md).
- `eval/labels/` — `IMG_7652.jsonl` (9 curated competitive rallies), `IMG_7655.jsonl`, `austin_rally2.jsonl`.

## `tests/` (53 tests, `make test`)

One file per module: `test_ball.py` (14), `test_harness.py` (12), `test_events.py` (6), `test_players.py` (5), `test_track.py` (4), `test_segment.py` (4), `test_calibrate.py` (3), `test_label.py` (3), `test_render.py` (2). Suite runs without torch/weights/video — see [testing conventions](testing/evaluation.md#unit-test-suite-tests-53-tests-make-test).

## Root documents (the product's memory)

| File | Role |
|---|---|
| `PRD.md` | Scope, goals/non-goals, success metrics, phases, risks, open questions. Prototype, not product. |
| `TECH_SPEC.md` | Capture, prior art, tier specs, segmentation, selection, rendering, compute budget, NFRs, repo layout, build order. |
| `DECISIONS.md` | 39 append-only ADRs (ADR-001…039, plus a blank `ADR-NNN` template at the tail). Early tier naming (T0/T1/T2) differs from current (T0′/T1′/T2′) — note at top of file. |
| `docs/superpowers/plans/2026-08-05-eval-harness.md` | Committed design plan behind the eval harness — the "build the measurement first" slice that started Phase 0. |
| `EXPERIMENTS.md` | Append-only run log; hypothesis-before-result rule. The 2026-08-10 entries hold the v1 diagnosis. |
| `PROGRESS.md` | Newest-first narrative + "NEXT SESSION — start here" block. The fastest way to pick up context. |
| `CHECKLIST.md` | Phase-gate tracker with per-item status and the benchmark-window results table. |
| `LABELING.md` | Rally definition (v2: ball-dead) + edge cases + set discipline. |
| `STRATEGY.md` | Post-prototype direction (multi-venue, B2B2C highlights-as-a-service). Exploratory, uncommitted. |
| `TALLY.md` | Per-session watch-through template (`tallies/` holds filled copies). |
| `config.yaml` | Minimal config surface (fps, resolution, 600 s budget); grows per phase. |
| `Makefile` | `make test`, `make eval`. |
| `requirements.txt` | opencv-python, numpy, ultralytics, pyyaml; pytest for dev. |

## Local artifacts (not source)

Session/broadcast footage (`*.mp4`/`*.MOV`/`*.mkv`), YOLO weights (`yolov8n.pt`, `yolov8x.pt` — ball.py defaults to `yolov8x.pt`), `cache/` (stage artifacts, gitignored, NFR3), `.venv/`, `__pycache__/`. Calibration JSONs (`IMG_7652_calib.json`, `austin_rally2_calib.json`) are committed reference calibrations for specific clips — note the 7652 one predates net-marking.
