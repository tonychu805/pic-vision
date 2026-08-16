---
type: Source Map
title: Source Map — file-by-file orientation
description: File-level map of the pic-vision repository — every source module, entry point, script, test, label file, and root document, with what exists versus what is planned but unbuilt, and what was retired to archive/ (ADR-046).
tags: [source-map, navigation, files]
resource: TECH_SPEC.md
openwiki:
  roles: [repository]
  change_kinds: [navigation]
  source_paths: [src, scripts, eval, tests, archive]
---

# Source Map

Files appear as phases land — nothing is stubbed ahead of time (README §Pipeline). This map shows what exists at HEAD versus the TECH_SPEC §12 target layout.

## Executable entry points (exist)

| File | Role |
|---|---|
| `make process` → `src/cut.py` | **The active pipeline**: predictions.csv + video → rally clips + `manifest.json` + `highlight.mp4`. CLI: `--video --predictions --out [--net-y | --calib | --auto-detect | interactive picker] [--gap-sec --min-crossings --band --pad-sec --court-id --session-id --fps --max-jump --reset-after --court-x-min --court-x-max --court-margin]`. |
| `scripts/pod_infer.py` | TrackNet inference — runs **on the RunPod pod** (TensorFlow/Keras, CUDA-only). Video → `predictions.csv` (`Frame,Visibility,X,Y`). Needs `TNV2_old_weights.h5` at `/workspace/` (see script docstring for source). Not unit-tested; no TF locally. |
| `calibrate.py` | Click 12 court points (any order) + 2 net-tape points → `court_calibration.json` (homography, RMSE ft, `net_image_points`). OpenCV GUI; core math in `compute_calibration` / order-independent assignment helpers. |
| `label.py` | Rally interval labeler → JSONL. `--review` mode replays segments for keep/drop curation. Timestamps from PTS (`CAP_PROP_POS_MSEC`). |
| `scripts/scan_crossings.py` | Diagnostic: fast YOLO-era scan printing crossing clusters for given params, no cutting (`detect_candidates → track_ball → crossing_times → cluster_crossings`). |
| `scripts/debug_detections.py` | Diagnostic: dump annotated JPEGs of a time window with YOLO boxes + net line (red = near, blue = far). |

**Planned, not built:** root `cut.py` (NFR7 single command with capture→select→render; the `src/cut.py` module above is the TrackNet-era orchestrator) and `src/capture.py` (preflight + RTSP recording — the procedure lives in [Operations](operations/runbook.md#capture-pitfalls)). ADR-046 mentions `scripts/process_footage.py`; at HEAD that role is folded into `src/cut.py` + `make process` (the script does not exist as a separate file).

## `src/` — detection library

| File | Path | Contents |
|---|---|---|
| `tracknet.py` | active | `load_predictions` (predictions.csv → timed track, `Visibility=0` → `None`), `rally_segments_from_predictions` (court X-gate via `court_x_min/max` → `track_ball` → `crossing_times` → `cluster_crossings`; validated defaults `gap_sec=3.0, min_crossings=3`). |
| `cut.py` | active | `cut_rallies_from_predictions` (segments → `score=crossings` → `cut_clips` → `concat_clips`) + CLI. Net-line resolution order: `--net-y` > `--calib` > `pick_net_y` > `--auto-detect` (ADR-041); `--calib` also auto-derives the court X-gate via `court_x_range`. |
| `ball.py` | active spine | Backend-agnostic: `crossing_times` / `count_crossings` (hysteresis side-flip), `cluster_crossings` (bursts → segments, courtesy-return suppression), `net_line_y` (marked-net preferred) / `net_image_y` (homography fallback), `ball_box_ok` size/aspect filter. |
| `calib.py` | active | `pick_net_y` (interactive one-click net picker with guide line), `detect_net_y` (headless Hough fallback, ~50 px error; rejects non-horizontal/right-side-only lines), `court_x_range` (image-x bounds of the tracked court from calibration points + margin — the multi-court gate). |
| `render.py` | active | `clip_command` (ffmpeg → libx264/faststart, audio dropped), `cut_clips` (segments → padded `rally_NNN.mp4` + `manifest.json` keyed by court/session/time), `concat_clips` (→ `highlight.mp4`), `manifest_entry`. |
| `segment.py` | shared | `segment(series, threshold, gap_sec, min_dur_sec)` — signal-agnostic gap-tolerant min-duration segmenter (v0 path; TrackNet path clusters crossings directly). |
| `players.py` | v0 frozen | `detect_players` (YOLOv8n person, sampled), `foot_point`, `to_court` (homography → court feet), `on_court` (asymmetric margin filter), `court_positions`, `load_calibration`. |
| `events.py` | v0 frozen | `mean_motion` / `motion_series` (tracking-free displacement), `n_at_kitchen` / `kitchen_series` (NVZ-formation marker; `KITCHEN_LINES = (15, 29)` ft). |
| `track.py` | active (TrackNet path) + YOLO-era | `track_ball` — single-ball nearest-neighbour tracker, teleport rejection (`max_jump`), re-acquire after `reset_after` gaps. Runs inside `rally_segments_from_predictions` behind the court X-gate (within-court teleports only; it cannot catch an adjacent-court ball after a `reset_after` gap — that is the gate's job); also used by `scripts/scan_crossings.py`. |

**Retired (`archive/`, ADR-046):** `yolo_detect.py` (`detect_ball`/`detect_candidates`), `yolo_pipeline.py` (`detect_rallies`/`rally_segments_from_candidates`), `archive/tests/test_yolo_pipeline.py`. Recoverable reference; not collected by pytest.

**Planned, not built:** `motion.py` (T0′ CPU pre-filter), `select.py` (rank + 600 s budget selection, TECH_SPEC §7 — the missing back half), `audio.py` (gated spectral-flux onsets, §5.1b). The three-era meaning of each module: [Architecture](architecture/overview.md#three-detection-eras-adr-039--046--047--the-most-important-structural-fact).

## `eval/`

- `eval/harness.py` — IoU, greedy one-to-one matching, detection + selection metric tables, CLI (`make eval`). Details: [Testing & Evaluation](testing/evaluation.md).
- `eval/labels/` — `IMG_7652.jsonl` (9 curated competitive rallies), `IMG_7655.jsonl`, `austin_rally2.jsonl`.

## `tests/` (67 tests, `make test`)

One file per module: `test_harness.py`, `test_calibrate.py`, `test_calib.py`, `test_ball.py`, `test_track.py`, `test_tracknet.py`, `test_cut.py`, `test_players.py`, `test_events.py`, `test_segment.py`, `test_render.py`, `test_label.py`. Suite runs without torch/TF/weights/video — see [testing conventions](testing/evaluation.md#unit-test-suite-tests-67-tests-make-test).

## Root documents (the product's memory)

| File | Role |
|---|---|
| `PRD.md` | Scope, goals/non-goals, success metrics, phases, risks, open questions. Prototype, not product. |
| `TECH_SPEC.md` | Capture, prior art, tier specs, segmentation, selection, rendering, compute budget, NFRs, repo layout, build order. §12/§13 predate the TrackNet pivot — DECISIONS.md ADR-046/047 are authoritative for the current layout. |
| `DECISIONS.md` | 47 append-only ADRs. Early tier naming (T0/T1/T2) differs from current (T0′/T1′/T2′) — note at top of file. ADR-041/046/047 define the current pipeline shape. |
| `EXPERIMENTS.md` | Append-only run log; hypothesis-before-result rule. 2026-08-10 holds the v1 diagnosis; 2026-08-12 holds the TrackNet 25-vs-5 result. |
| `PROGRESS.md` | Newest-first narrative + "NEXT SESSION — start here" block. The fastest way to pick up context. |
| `CHECKLIST.md` | Phase-gate tracker with per-item status and the benchmark-window results table (YOLO vs TrackNet columns). |
| `LABELING.md` | Rally definition (v2: ball-dead) + edge cases + set discipline. |
| `STRATEGY.md` | Post-prototype direction (multi-venue, B2B2C highlights-as-a-service). Exploratory; §3's player-first near-term framing superseded by ADR-047. |
| `TALLY.md` | Per-session watch-through template (`tallies/` holds filled copies). |
| `config.yaml` | Minimal config surface (fps, resolution, 600 s budget); grows per phase. |
| `Makefile` | `make test`, `make eval`, `make process VIDEO=… CSV=… [NET_Y=…] OUT=…`. |
| `requirements.txt` | opencv-python, numpy, ultralytics, pyyaml; pytest for dev. (TensorFlow/Keras are pod-only, used by `scripts/pod_infer.py`.) |
| `docs/superpowers/` | Process/planning notes, not product code. |

## Local artifacts (not source)

Session/broadcast footage (`*.mp4`/`*.MOV`/`*.mkv`), YOLO weights (`yolov8x.pt`, `yolov8x.mlpackage` — CoreML export, ADR-044), `cache/` (stage artifacts, gitignored, NFR3), `.venv/`, `__pycache__/`. TrackNet weights (`TNV2_old_weights.h5`) live on the pod, not in the repo. Calibration JSONs (`IMG_7652_calib.json`, `austin_rally2_calib.json`) are committed reference calibrations for specific clips — note the 7652 one predates net-marking.
