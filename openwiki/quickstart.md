---
type: Quickstart
title: pic-vision — OpenWiki Quickstart
description: Entrypoint for the pic-vision (Pickleball Rally Cutter) code wiki. What the project is, current build status, the single blocking gate, and links to architecture, workflows, domain concepts, operations, testing, and the source map.
tags: [quickstart, pickleball, computer-vision, rally-detection]
resource: README.md
openwiki:
  roles: [repository]
  change_kinds: [detection-pipeline, public-api, lifecycle]
  source_paths: [src/cut.py, src/tracknet.py, src/ball.py, src/render.py, scripts/pod_infer.py]
  symbols: [cut_rallies_from_predictions, rally_segments_from_predictions, crossing_times, cluster_crossings, cut_clips, concat_clips]
  test_paths: [tests/test_cut.py, tests/test_tracknet.py, tests/test_ball.py]
  validation_commands: [python3 -m pytest -q]
---

# pic-vision — Pickleball Rally Cutter

**One-line:** a prototype CLI pipeline that turns a two-hour fixed-camera pickleball session into a watchable highlight reel (≤ 10 min) plus a full rally cut, by detecting rallies and cutting the dead time. Source of truth for scope: [`PRD.md`](/PRD.md); how it's built: [`TECH_SPEC.md`](/TECH_SPEC.md); why: [`DECISIONS.md`](/DECISIONS.md) (39 ADRs).

**Status:** mid-Phase-1. The end-to-end path is **runnable**: TrackNet ball detection on a RunPod GPU pod → `make process` cuts H.264 rally clips + `manifest.json` + `highlight.mp4` locally (65 tests green). The remaining unbuilt piece is the ranker (`src/select.py`). See [Operations & Status](operations/runbook.md) for the phase checklist.

## The single gate right now

Everything is blocked on **one clean, fixed clip** (rigid mount, no zoom/pan, whole court visible, well-lit). The current footage (IMG_7652/7655) is zoom-compromised, so detection parameters can't be tuned and metrics are meaningless until a clean capture exists. Full context: [PROGRESS.md](/PROGRESS.md) "NEXT SESSION" block and [Key Workflows](workflows/pipeline.md).

## Current architecture in one paragraph

The rally signal is **ball net-crossings**: count the times the ball's image-y crosses the net line, cluster dense crossing bursts into rally segments. The detector behind that signal has moved twice on measured evidence: v0 player-geometry markers measured *inverted* on casual play and are frozen (ADR-039; `src/players.py` + `src/events.py`); the YOLOv8x `sports ball` detector found only 5 crossings where TrackNet's 3-frame heatmap finds 25, so it was retired to `archive/` (ADR-046) and **TrackNet on a RunPod GPU pod is now the primary, ball-first path** (ADR-047). The spine is backend-agnostic: `src/tracknet.py` parses the pod's `predictions.csv`, `src/ball.py` computes crossings/clusters, `src/cut.py` orchestrates, `src/render.py` cuts clips, and the [eval harness](testing/evaluation.md) scores output. Details: [Architecture](architecture/overview.md) and [Rally Detection Concepts](concepts/rally-detection.md).

## Where to go next

| You want to… | Read |
|---|---|
| Run the tools or understand the operator workflow | [Key Workflows](workflows/pipeline.md) |
| Understand the pipeline shape and why it looks this way | [Architecture Overview](architecture/overview.md) |
| Learn the domain vocabulary (rally, net-crossing, tracker, calibration) | [Rally Detection Concepts](concepts/rally-detection.md) |
| Find a file or see what exists vs. what's stubbed | [Source Map](source-map.md) |
| Capture footage, avoid camera pitfalls, check phase status | [Operations & Runbook](operations/runbook.md) |
| Run tests, score predictions against labels, use benchmark windows | [Testing & Evaluation](testing/evaluation.md) |

## Repo orientation (30 seconds)

- **Root docs are the product**: `PRD.md`, `TECH_SPEC.md`, `DECISIONS.md` (47 ADRs), `EXPERIMENTS.md` (append-only run log), `PROGRESS.md` (newest-first narrative), `CHECKLIST.md` (phase gates), `LABELING.md`, `STRATEGY.md` (post-prototype business direction — exploratory; near-term player-first framing superseded by ADR-047).
- **Entry points today**: `scripts/pod_infer.py` (TrackNet inference, runs *on* the RunPod pod), `make process` → `src/cut.py` (predictions.csv + video → clips + manifest + highlight.mp4), `calibrate.py` (12 court + 2 net-tape clicks per mount), `label.py` (rally labeler with `--review`). The spec's one-command root `cut.py` (NFR7, with ranking/budget) is not built yet.
- **`src/`**: `tracknet.py` (CSV → segments), `ball.py` (backend-agnostic crossing/cluster/net-line math), `cut.py` (orchestrator), `calib.py` (net-line picker + Hough fallback), `render.py`, `segment.py`, plus frozen v0 (`players.py`, `events.py`) and the YOLO-era `track.py`. Retired YOLO pipeline: `archive/`.
- **`eval/`**: `harness.py` (temporal-IoU matching → PRD §5 metric tables) and `labels/` (JSONL ground truth per clip).
- **`tests/`**: 65 pytest unit tests, all dependency-light (no torch/TF/weights/video needed).
- **`Makefile`**: `make test`, `make eval` (scores `rallies.json` against `eval/labels/IMG_7652.jsonl`), `make process VIDEO=… CSV=… [NET_Y=…] OUT=…`.
- Video files, YOLO weights (`yolov8x.pt`, `yolov8x.mlpackage`), `cache/`, and `tallies/` are local working artifacts, mostly gitignored.

## Invariants worth knowing before touching code

1. **Timestamps come from PTS, never `frame_index / fps`** (TECH_SPEC §1.1); temporal params are configured in seconds (`config.yaml`), converted to frames at runtime.
2. **Detection is measured before selection, never on the 10-min reel** (PRD §5); `eval-set-A` is locked — tune only on `dev-set-B`.
3. **Every quality claim must be measurable against labeled holdout** — honest measurement is the non-negotiable point of the prototype.
4. The pipeline **degrades rather than fails** (ADR-003): audio is optional, ball trajectory is gated, video-only is the floor.
5. **The detector is swappable; the signal is not.** `crossing_times`/`cluster_crossings` in `src/ball.py` accept any ball track — YOLO, TrackNet, or synthetic (backend-agnostic by design, proven when TrackNet replaced YOLO without touching the spine).

## Task routing

| Change area / intent | Wiki page | Source entry points | Key symbols | Focused tests | Minimal validation |
|---|---|---|---|---|---|
| Crossing/cluster logic, net-line resolution | [Concepts](concepts/rally-detection.md) | `src/ball.py` | `crossing_times`, `cluster_crossings`, `net_line_y`, `count_crossings` | `tests/test_ball.py` (14) | `python3 -m pytest tests/test_ball.py -q` |
| TrackNet CSV parsing, segments from predictions | [Concepts](concepts/rally-detection.md#tracknet--the-active-detector-adr-046) | `src/tracknet.py` | `load_predictions`, `rally_segments_from_predictions` | `tests/test_tracknet.py` (4) | `python3 -m pytest tests/test_tracknet.py -q` |
| End-to-end orchestration / CLI flags | [Workflows](workflows/pipeline.md#5-run-detection-tracknet--runpod--the-active-path) | `src/cut.py` | `cut_rallies_from_predictions`, `main` | `tests/test_cut.py` (2) | `python3 -m pytest tests/test_cut.py -q` |
| Net-line picker / Hough auto-detect | [Workflows](workflows/pipeline.md#3-resolve-the-net-line-adr-041) | `src/calib.py` | `pick_net_y`, `detect_net_y` | `tests/test_calib.py` (2) | `python3 -m pytest tests/test_calib.py -q` |
| Clip cutting, padding, manifest, highlight concat | [Architecture](architecture/overview.md#selection-and-rendering-partially-wired) | `src/render.py` | `clip_command`, `cut_clips`, `concat_clips`, `manifest_entry` | `tests/test_render.py` (5) | `python3 -m pytest tests/test_render.py -q` |
| RunPod inference script | [Workflows](workflows/pipeline.md#5-run-detection-tracknet--runpod--the-active-path) | `scripts/pod_infer.py` | `prep3`, `run` | none (runs on pod; GPU + TF) | manual: run on pod, inspect CSV |
| Eval metrics / matching | [Testing](testing/evaluation.md#eval-harness-evalharnesspy) | `eval/harness.py` | `match_intervals` + table builders | `tests/test_harness.py` (12) | `python3 -m pytest tests/test_harness.py -q && make eval` |
| Frozen v0 player markers | [Concepts](concepts/rally-detection.md#v0-player-markers-frozen-baseline) | `src/players.py`, `src/events.py` | `foot_point`, `to_court`, `mean_motion`, `n_at_kitchen` | `tests/test_players.py`, `tests/test_events.py` | `python3 -m pytest tests/test_players.py tests/test_events.py -q` |
| Archived YOLO path (reference only) | [Concepts](concepts/rally-detection.md#the-retired-yolo-detector-archive-adr-046) | `archive/yolo_detect.py`, `archive/yolo_pipeline.py` | `detect_ball`, `detect_candidates`, `track_ball` (in `src/track.py`) | `archive/tests/test_yolo_pipeline.py`, `tests/test_track.py` | `python3 -m pytest tests/test_track.py -q` |

## Backlog

Areas identified but not yet documented in depth (mostly because the code doesn't exist yet):

- **Selection & ranking** (`src/select.py`, TECH_SPEC §7) — not built; will deserve a page when the ranker lands. Today's `src/cut.py` scores by raw crossing count with no budget enforcement.
- **Root `cut.py` single-command entry (NFR7)** — the spec shape (`python cut.py session.mp4 --budget 600`, capture→detect→select→render). The TrackNet-era orchestrator lives at `src/cut.py` behind `make process`.
- **Audio path** (`src/audio.py`, TECH_SPEC §5.1b, Phase 2.5) — not started; conditional on a usability gate.
- **Capture preflight** (`src/capture.py`, TECH_SPEC §1.1) — documented procedurally in [Operations](operations/runbook.md); module not written.
- **Cloud-hybrid deployment** (ADR-043: N100 edge + RunPod serverless + LINE delivery) — decided, not built; documented as direction in [Architecture](architecture/overview.md) and [Operations](operations/runbook.md).
- **STRATEGY.md business model** (B2B2C HaaS, venue deployment, ADR-024/033/034) — summarized above only; exploratory and gated on prototype success.
