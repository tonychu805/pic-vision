---
type: Quickstart
title: pic-vision — OpenWiki Quickstart
description: Entrypoint for the pic-vision (Pickleball Rally Cutter) code wiki. What the project is, current build status, the single blocking gate, and links to architecture, workflows, domain concepts, operations, testing, and the source map.
tags: [quickstart, pickleball, computer-vision, rally-detection]
resource: README.md
---

# pic-vision — Pickleball Rally Cutter

**One-line:** a prototype CLI pipeline that turns a two-hour fixed-camera pickleball session into a watchable highlight reel (≤ 10 min) plus a full rally cut, by detecting rallies and cutting the dead time. Source of truth for scope: [`PRD.md`](/PRD.md); how it's built: [`TECH_SPEC.md`](/TECH_SPEC.md); why: [`DECISIONS.md`](/DECISIONS.md) (39 ADRs).

**Status:** late-Phase-1 wiring. The v1 detection chain is fully wired end-to-end — `src/pipeline.py` chains detect → track → crossing → cluster, and `src/cut.py` orchestrates footage → H.264 clips + `highlight.mp4` in one pass (61 tests). Still missing: the ranker (`src/select.py`) and any measured number on clean footage. See [Operations & Status](operations/runbook.md) for the phase checklist.

## The single gate right now

Everything is blocked on **one clean, fixed clip** (rigid mount, no zoom/pan, whole court visible, well-lit). The current footage (IMG_7652/7655) is zoom-compromised, so detection parameters can't be tuned and metrics are meaningless until a clean capture exists. Full context: [PROGRESS.md](/PROGRESS.md) "NEXT SESSION" block and [Key Workflows](workflows/pipeline.md).

## Current architecture in one paragraph

The rally signal pivoted (ADR-039) from **v0 — player dead-time inversion** (detect when play *stops* via player geometry; frozen baseline in `src/players.py` + `src/events.py`) to **v1 — ball net-crossings** (YOLOv8x `sports ball` detection → single-ball tracker → count net-line crossings → cluster bursts into rally segments), wired by `src/pipeline.py` and cut by `src/cut.py`. v1 is the primary effort because player-activity markers measured *inverted* on real casual-play footage (dead time was more active than dink rallies). Both paths share `src/segment.py`, `src/render.py`, and the [eval harness](testing/evaluation.md). Details: [Architecture](architecture/overview.md) and [Rally Detection Concepts](concepts/rally-detection.md).

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

- **Root docs are the product**: `PRD.md`, `TECH_SPEC.md`, `DECISIONS.md` (ADRs), `EXPERIMENTS.md` (append-only run log), `PROGRESS.md` (newest-first narrative), `CHECKLIST.md` (phase gates), `LABELING.md`, `STRATEGY.md` (post-prototype business direction — exploratory, uncommitted: B2B2C "highlights-as-a-service" wedge).
- **Entry points today**: `calibrate.py` (click 12 court points + 2 net-tape points per camera mount), `label.py` (rally interval labeler with `--review` mode), and `src/cut.py` (end-to-end orchestrator: `python -m src.cut --video ... --calib ... --out ...`).
- **`src/`**: detection modules — `ball.py`, `track.py`, `players.py`, `events.py`, `segment.py`, `render.py` — plus the wiring: `pipeline.py` (v1 chain) and `cut.py` (orchestrator + CLI). No stubs; files appear as phases land.
- **`eval/`**: `harness.py` (temporal-IoU matching → PRD §5 metric tables) and `labels/` (JSONL ground truth per clip).
- **`tests/`**: 61 pytest unit tests, all dependency-light (no torch/YOLO needed to run them).
- **`Makefile`**: `make test`, `make eval` (scores `rallies.json` against `eval/labels/IMG_7652.jsonl`; `eval` is the default target).
- Video files, YOLO weights (`yolov8n.pt`, `yolov8x.pt`), `cache/`, and `tallies/` are local working artifacts, mostly gitignored.

## Invariants worth knowing before touching code

1. **Timestamps come from PTS, never `frame_index / fps`** (TECH_SPEC §1.1); temporal params are configured in seconds (`config.yaml`), converted to frames at runtime.
2. **Detection is measured before selection, never on the 10-min reel** (PRD §5); `eval-set-A` is locked — tune only on `dev-set-B`.
3. **Every quality claim must be measurable against labeled holdout** — honest measurement is the non-negotiable point of the prototype.
4. The pipeline **degrades rather than fails** (ADR-003): audio is optional, ball trajectory is gated, video-only is the floor.

## Task routing

Where to start for the recurring change categories this repo supports today. Validation is deliberately narrow — the suite runs in seconds without torch, weights, or video, so `make test` (or a single `tests/test_x.py` file) is the default check; a real-footage run is only for detection-parameter changes and requires the footage, weights, and a marked-net calibration.

| Change area / intent | Wiki page | Source entry points | Important symbols | Focused tests | Minimal validation |
|---|---|---|---|---|---|
| Change the v1 detection recipe (thresholds, model, filters) | [Concepts](concepts/rally-detection.md) | `src/ball.py`, `src/track.py` | `detect_candidates`, `ball_box_ok`, `track_ball`, `crossing_times`, `cluster_crossings` | `tests/test_ball.py`, `tests/test_track.py` | `python3 -m pytest tests/test_ball.py tests/test_track.py -q` |
| Change the detect→track→crossing→cluster wiring | [Architecture](architecture/overview.md) | `src/pipeline.py` | `rally_segments_from_candidates`, `detect_rallies` | `tests/test_pipeline.py` | `python3 -m pytest tests/test_pipeline.py -q` |
| Change clip cutting, manifest, or `highlight.mp4` concat | [Source Map](source-map.md) | `src/render.py` | `clip_command`, `cut_clips`, `concat_clips`, `manifest_entry` | `tests/test_render.py` | `python3 -m pytest tests/test_render.py -q` |
| Change the end-to-end orchestrator or its CLI | [Workflows](workflows/pipeline.md) | `src/cut.py` | `cut_rallies`, `main` | `tests/test_cut.py` | `python3 -m pytest tests/test_cut.py -q` |
| Score or change how predictions are judged | [Testing](testing/evaluation.md) | `eval/harness.py` | `match_intervals` | `tests/test_harness.py` | `python3 -m pytest tests/test_harness.py -q` |
| Add rally labels / recalibrate a mount | [Workflows](workflows/pipeline.md) | `label.py`, `calibrate.py` | `compute_calibration` | `tests/test_label.py`, `tests/test_calibrate.py` | `python3 -m pytest tests/test_label.py tests/test_calibrate.py -q` |

Conditional, expensive checks (run only when the condition holds): a real-footage detection run (`python -m src.cut ...`) after changing detection parameters — requires local `*.mp4`, `yolov8x.pt`, and a per-mount calibration; and `make eval` once a real `rallies.json` exists on the locked eval set. Neither is part of routine unit work.

## Backlog

Areas identified but not yet documented in depth (mostly because the code doesn't exist yet):

- **Selection & ranking** (`src/select.py`, TECH_SPEC §7) — not built; will deserve a page when the ranker lands. `src/cut.py` currently surfaces raw crossing count as each clip's `score`, which is the interim stand-in.
- **First measured harness numbers** — `rallies.json` from `src/cut.py` on clean footage, scored by `make eval`; blocked on the capture gate, not on code.
- **Audio path** (`src/audio.py`, TECH_SPEC §5.1b, Phase 2.5) — not started; conditional on a usability gate.
- **Capture preflight** (`src/capture.py`, TECH_SPEC §1.1) — documented procedurally in [Operations](operations/runbook.md); module not written.
- **STRATEGY.md business model** (B2B2C HaaS, venue deployment, ADR-024/033/034) — summarized above only; exploratory and gated on prototype success.
