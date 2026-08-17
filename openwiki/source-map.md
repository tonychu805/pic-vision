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
| `scripts/pod_infer.py` | TrackNet inference — runs **on a CUDA GPU** (RunPod pod, or the local RTX 2000 Ada under TF 2.15.1). Video → `predictions.csv` (`Frame,Visibility,X,Y`); aborts below 98% of expected frames (silent-decode guard). Needs weights alongside (`TNV2_old_weights.h5` on the pod; pickleball k14 locally — see script docstring for sources). Not unit-tested; no TF on the M2 laptop. |
| `calibrate.py` | Click 12 court points (any order) + 2 net-tape points → `court_calibration.json` (homography, RMSE ft, `net_image_points`). OpenCV GUI; core math in `compute_calibration` / order-independent assignment helpers. |
| `calibrate_web.py` / `label_web.py` | Browser-driven variants of `calibrate.py` / `label.py` for headless workstations over SSH (video streams to the browser instead of raw X11 frames; the IMG_7743 calibration + 33 labels were produced this way). |
| `label.py` | Rally interval labeler → JSONL. Two passes: MARK (`s`/`e`), then GRADE (`g`, then `1` highlight / `2` ordinary / `3` drop — grades written as a `quality` field). `--review` mode replays segments for keep/drop curation. Timestamps from PTS (`CAP_PROP_POS_MSEC`). |
| `scripts/scan_crossings.py` | Diagnostic: fast YOLO-era scan printing crossing clusters for given params, no cutting (`detect_candidates → track_ball → crossing_times → cluster_crossings`). |
| `scripts/debug_detections.py` | Diagnostic: dump annotated JPEGs of a time window with YOLO boxes + net line (red = near, blue = far). |

**Planned, not built:** root `cut.py` (NFR7 single command with capture→select→render; the `src/cut.py` module above is the TrackNet-era orchestrator) and `src/capture.py` (preflight + RTSP recording — the procedure lives in [Operations](operations/runbook.md#capture-pitfalls)). ADR-046 mentions `scripts/process_footage.py`; at HEAD that role is folded into `src/cut.py` + `make process` (the script does not exist as a separate file).

## `src/` — detection library

| File | Path | Contents |
|---|---|---|
| `tracknet.py` | active | `load_predictions` (predictions.csv → timed track, `Visibility=0` → `None`), `rally_segments_from_predictions` (court gate → `track_ball` → `crossing_times` → `cluster_crossings`; canonical defaults `gap_sec=3.0, min_crossings=6`, ADR-048). Gate shapes: flat `court_x_min/max` interval, or the perspective-aware `court_wedge` passed as `in_court=` (supersedes the interval when given; API-only — no CLI flag yet). |
| `cut.py` | active | `cut_rallies_from_predictions` (segments → `score=crossings` → `cut_clips` → `concat_clips`) + CLI. Net-line resolution order: `--net-y` > `--calib` > `pick_net_y` > `--auto-detect` (ADR-041); `--calib` also auto-derives the flat court X-gate via `court_x_range`. |
| `ball.py` | active spine | Backend-agnostic: `crossing_times` / `count_crossings` (hysteresis side-flip), `cluster_crossings` (bursts → segments, courtesy-return suppression), `net_line_y` (marked-net preferred; **warns** on homography fallback — returns the net's base, ~130 px too low) / `net_image_y`, `ball_box_ok` size/aspect filter. |
| `calib.py` | active | `pick_net_y` (interactive one-click net picker with guide line), `detect_net_y` (headless Hough fallback, ~50 px error; rejects non-horizontal/right-side-only lines), `court_x_range` (flat image-x bounds of the tracked court + margin), `court_wedge` (perspective-aware `(x, y) -> bool` gate: follows the court taper with depth, keeps airspace for lobs, hard-capped `cap_court_heights` above the far baseline — precision 0.29 vs 0.10 for the flat interval on IMG_7743; the cap also *raises* recall by stopping ceiling fixtures from hijacking `track_ball`). |
| `render.py` | active | `clip_command` (ffmpeg → libx264/faststart, audio dropped), `cut_clips` (segments → padded `rally_NNN.mp4` + `manifest.json` keyed by court/session/time), `concat_clips` (→ `highlight.mp4`), `manifest_entry`. |
| `segment.py` | shared | `segment(series, threshold, gap_sec, min_dur_sec)` — signal-agnostic gap-tolerant min-duration segmenter (v0 path; TrackNet path clusters crossings directly). |
| `verify.py` | active | Gemini Flash clip verification: `verify_clip` (one clip → strict-JSON `{"is_rally", "confidence", "reason"}`), `verify_clips` (batch), CLI `python3 -m src.verify clips...`. Needs `GOOGLE_API_KEY` (`.env`, see `.env.example`); fails loudly on API/parse errors. A check on the crossing heuristics, not wired into `make process`. |
| `players.py` | v0 frozen | `detect_players` (YOLOv8n person, sampled), `foot_point`, `to_court` (homography → court feet), `on_court` (asymmetric margin filter), `court_positions`, `load_calibration`. |
| `events.py` | v0 frozen | `mean_motion` / `motion_series` (tracking-free displacement), `n_at_kitchen` / `kitchen_series` (NVZ-formation marker; `KITCHEN_LINES = (15, 29)` ft). |
| `track.py` | active (TrackNet path) + YOLO-era | `track_ball` — single-ball nearest-neighbour tracker, teleport rejection (`max_jump`), re-acquire after `reset_after` gaps. Runs inside `rally_segments_from_predictions` behind the court gate (within-court teleports only; it cannot catch an adjacent-court ball after a `reset_after` gap — that is the gate's job); also used by `scripts/scan_crossings.py`. |

**Retired (`archive/`, ADR-046):** `yolo_detect.py` (`detect_ball`/`detect_candidates`), `yolo_pipeline.py` (`detect_rallies`/`rally_segments_from_candidates`), `archive/tests/test_yolo_pipeline.py`. Recoverable reference; not collected by pytest.

**Planned, not built:** `motion.py` (T0′ CPU pre-filter), `select.py` (rank + 600 s budget selection, TECH_SPEC §7 — the missing back half), `audio.py` (gated spectral-flux onsets, §5.1b). The three-era meaning of each module: [Architecture](architecture/overview.md#three-detection-eras-adr-039--046--047--the-most-important-structural-fact).

## `eval/`

- `eval/harness.py` — IoU, greedy one-to-one matching, detection + selection metric tables, CLI (`make eval`). Details: [Testing & Evaluation](testing/evaluation.md).
- `eval/labels/` — `IMG_7743.jsonl` (**33 labels — the primary benchmark**, clean footage), `IMG_7652.jsonl` (9 curated competitive rallies), `IMG_7655.jsonl` (36 labels; no calibration yet), `austin_rally2.jsonl`.

## `tests/` (78 tests, `make test`)

One file per module: `test_harness.py`, `test_calibrate.py`, `test_calib.py`, `test_ball.py`, `test_track.py`, `test_tracknet.py`, `test_cut.py`, `test_players.py`, `test_events.py`, `test_segment.py`, `test_render.py`, `test_label.py`, `test_verify.py`. Suite runs without torch/TF/weights/video/API keys — see [testing conventions](testing/evaluation.md#unit-test-suite-tests-78-tests-make-test).

## Root documents (the product's memory)

| File | Role |
|---|---|
| `PRD.md` | Scope, goals/non-goals, success metrics, phases, risks, open questions. Prototype, not product. |
| `TECH_SPEC.md` | Capture, prior art, tier specs, segmentation, selection, rendering, compute budget, NFRs, repo layout, build order. §12/§13 predate the TrackNet pivot — DECISIONS.md ADR-046/047/048 are authoritative for the current layout and defaults. |
| `DECISIONS.md` | 48 append-only ADRs + template. Early tier naming (T0/T1/T2) differs from current (T0′/T1′/T2′) — note at top of file. ADR-041/046/047 define the current pipeline shape; ADR-048 canonizes `min_crossings=6`. |
| `EXPERIMENTS.md` | Append-only run log; hypothesis-before-result rule. 2026-08-10 holds the v1 diagnosis; 2026-08-12 holds the TrackNet 25-vs-5 result; 2026-08-16 holds the IMG_7743 benchmark, k14-weights A/B, and the `court_wedge` sweep. |
| `PROGRESS.md` | Newest-first narrative + "NEXT SESSION — start here" block. The fastest way to pick up context. |
| `CHECKLIST.md` | Phase-gate tracker with per-item status, the PRD §5 targets-vs-measured table (IMG_7743, 2026-08-16), and "the one real gate" (cleared; PIC-1 is the current blocker). |
| `LABELING.md` | Rally definition (v2: ball-dead) + edge cases + set discipline. |
| `STRATEGY.md` | Post-prototype direction (multi-venue, B2B2C highlights-as-a-service). Exploratory; §3's player-first near-term framing superseded by ADR-047. |
| `TALLY.md` | Per-session watch-through template (`tallies/` holds filled copies). |
| `config.yaml` | Minimal config surface (fps, resolution, 600 s budget); grows per phase. |
| `Makefile` | `make test`, `make eval`, `make process VIDEO=… CSV=… [NET_Y=…] OUT=…`. |
| `requirements.txt` | opencv-python, numpy, ultralytics, pyyaml, google-genai + python-dotenv (`src/verify.py`); pytest for dev. (TensorFlow/Keras are GPU-side only, used by `scripts/pod_infer.py`.) |
| `.env.example` | `GOOGLE_API_KEY` placeholder for `src/verify.py`; copy to gitignored `.env`. |
| `docs/superpowers/` | Process/planning notes, not product code. |

## Local artifacts (not source)

Session/broadcast footage (`*.mp4`/`*.MOV`/`*.mkv`), YOLO weights (`yolov8x.pt`, `yolov8x.mlpackage` — CoreML export, ADR-044), `cache/` (stage artifacts, gitignored, NFR3), `.venv/`, `__pycache__/`. TrackNet weights (`TNV2_old_weights.h5`) live on the pod, not in the repo. Calibration JSONs (`IMG_7652_calib.json`, `austin_rally2_calib.json`) are committed reference calibrations for specific clips — note the 7652 one predates net-marking.
