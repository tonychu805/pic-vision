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
| `src/cut.py` | End-to-end orchestrator + CLI (`python -m src.cut --video … --calib … --out …`). `cut_rallies` runs `detect_rallies`, scores each segment by crossing count, and calls `cut_clips` + `concat_clips`. Lives under `src/`; the root-level `cut.py` of NFR7 / TECH_SPEC §12 is the intended final entry shape. |

**Planned, not built:** `src/capture.py` (preflight + RTSP recording — the procedure lives in [Operations](operations/runbook.md#capture-pitfalls)).

## `src/` — detection library

| File | Path | Contents |
|---|---|---|
| `ball.py` | v1 | `detect_candidates` / `detect_ball` (yolov8x, class 32, `imgsz=1280`, lazy ultralytics import), `ball_box_ok` size/aspect filter, `net_line_y` (marked-net preferred) / `net_image_y` (homography fallback), `crossing_times` / `count_crossings` (hysteresis side-flip), `cluster_crossings` (bursts → segments, courtesy-return suppression via `min_crossings`). |
| `track.py` | v1 | `track_ball` — single-ball nearest-neighbour tracker, teleport rejection (`max_jump`), re-acquire after `reset_after` gaps. Kills phantom dead-time crossings from other courts' balls. |
| `players.py` | v0 | `detect_players` (YOLOv8n person, sampled), `foot_point`, `to_court` (homography → court feet), `on_court` (asymmetric margin filter), `court_positions`, `load_calibration`. |
| `events.py` | v0 | `mean_motion` / `motion_series` (tracking-free displacement), `n_at_kitchen` / `kitchen_series` (NVZ-formation marker; `KITCHEN_LINES = (15, 29)` ft). |
| `segment.py` | shared | `segment(series, threshold, gap_sec, min_dur_sec)` — signal-agnostic gap-tolerant min-duration segmenter. |
| `render.py` | shared | `clip_command` (ffmpeg → libx264/faststart, audio dropped for now), `manifest_entry` (one browse record per clip), `cut_clips` (segments → `rally_NNN.mp4` + `manifest.json` keyed by court/session/time), `concat_clips` (all manifest clips → `highlight.mp4` via the ffmpeg concat demuxer; `None` on empty manifest). |
| `pipeline.py` | v1 | `rally_segments_from_candidates` (pure core: candidates → `track_ball` → `crossing_times` → `cluster_crossings`), `detect_rallies` (adds the YOLO front-end over a video). Requires dense per-frame candidates — subsampling breaks the tracker's `max_jump` motion assumption. |
| `cut.py` | wiring | `cut_rallies` (detect → score-by-crossings → `cut_clips` → `concat_clips`) + `main` CLI. Validated defaults `max_jump=150`, `gap_sec=3.0`, `min_crossings=5`. |

**Planned, not built:** `motion.py` (T0′ CPU pre-filter), `select.py` (rank + budget selection, TECH_SPEC §7), `audio.py` (gated spectral-flux onsets, §5.1b). The v0-vs-v1 meaning of each module: [Architecture](architecture/overview.md#the-v0v1-split-adr-039--the-most-important-structural-fact).

## `eval/`

- `eval/harness.py` — IoU, greedy one-to-one matching, detection + selection metric tables, CLI (`make eval`). Details: [Testing & Evaluation](testing/evaluation.md).
- `eval/labels/` — `IMG_7652.jsonl` (9 curated competitive rallies), `IMG_7655.jsonl`, `austin_rally2.jsonl`.

## `tests/` (61 tests, `make test`)

One file per module: `test_harness.py`, `test_calibrate.py`, `test_ball.py`, `test_track.py`, `test_players.py`, `test_events.py`, `test_segment.py`, `test_render.py`, `test_label.py`, plus the wiring tests `test_pipeline.py` (pure candidate→segment chain) and `test_cut.py` (orchestrator glue, heavy ends monkeypatched). Suite runs without torch/weights/video — see [testing conventions](testing/evaluation.md#unit-test-suite-tests-61-tests-make-test).

## Root documents (the product's memory)

| File | Role |
|---|---|
| `PRD.md` | Scope, goals/non-goals, success metrics, phases, risks, open questions. Prototype, not product. |
| `TECH_SPEC.md` | Capture, prior art, tier specs, segmentation, selection, rendering, compute budget, NFRs, repo layout, build order. |
| `DECISIONS.md` | 39 append-only ADRs. Early tier naming (T0/T1/T2) differs from current (T0′/T1′/T2′) — note at top of file. |
| `EXPERIMENTS.md` | Append-only run log; hypothesis-before-result rule. The 2026-08-10 entries hold the v1 diagnosis. |
| `PROGRESS.md` | Newest-first narrative + "NEXT SESSION — start here" block. The fastest way to pick up context. |
| `CHECKLIST.md` | Phase-gate tracker with per-item status and the benchmark-window results table. |
| `LABELING.md` | Rally definition (v2: ball-dead) + edge cases + set discipline. |
| `STRATEGY.md` | Post-prototype direction (multi-venue, B2B2C highlights-as-a-service). Exploratory, uncommitted. |
| `TALLY.md` | Per-session watch-through template (`tallies/` holds filled copies). |
| `config.yaml` | Minimal config surface (fps, resolution, 600 s budget); grows per phase. Note: detection parameters (`max_jump`, `gap_sec`, `min_crossings`, `max_ball_px`) are currently **CLI flags on `src/cut.py`, not in config.yaml** — the recipe values live in code defaults pending clean-footage tuning. |
| `Makefile` | `make test`, `make eval` (`eval` is the default/first target). |
| `requirements.txt` | opencv-python, numpy, ultralytics, pyyaml; pytest for dev. |

## Local artifacts (not source)

Session/broadcast footage (`*.mp4`/`*.MOV`/`*.mkv`), YOLO weights (`yolov8n.pt`, `yolov8x.pt` — ball.py defaults to `yolov8x.pt`), `cache/` (stage artifacts, gitignored, NFR3), `.venv/`, `__pycache__/`. Calibration JSONs (`IMG_7652_calib.json`, `austin_rally2_calib.json`) are committed reference calibrations for specific clips — note the 7652 one predates net-marking.
