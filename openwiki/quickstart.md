---
type: Quickstart
title: pic-vision — OpenWiki Quickstart
description: Entrypoint for the pic-vision (Pickleball Rally Cutter) code wiki. What the project is, current build status, the single blocking gate, and links to architecture, workflows, domain concepts, operations, testing, and the source map.
tags: [quickstart, pickleball, computer-vision, rally-detection]
resource: README.md
---

# pic-vision — Pickleball Rally Cutter

**One-line:** a prototype CLI pipeline that turns a two-hour fixed-camera pickleball session into a watchable highlight reel (≤ 10 min) plus a full rally cut, by detecting rallies and cutting the dead time. Source of truth for scope: [`PRD.md`](/PRD.md); how it's built: [`TECH_SPEC.md`](/TECH_SPEC.md); why: [`DECISIONS.md`](/DECISIONS.md) (39 ADRs + template).

**Status:** mid-Phase-1. All detection primitives are built and unit-tested (53 tests), but the end-to-end orchestrator (`cut.py`) and ranker (`src/select.py`) are not wired yet. See [Operations & Status](operations/runbook.md) for the phase checklist.

## The single gate right now

Everything is blocked on **one clean, fixed clip** (rigid mount, no zoom/pan, whole court visible, well-lit). The current footage (IMG_7652/7655) is zoom-compromised, so detection parameters can't be tuned and metrics are meaningless until a clean capture exists. Full context: [PROGRESS.md](/PROGRESS.md) "NEXT SESSION" block and [Key Workflows](workflows/pipeline.md).

## Current architecture in one paragraph

The rally signal pivoted (ADR-039) from **v0 — player dead-time inversion** (detect when play *stops* via player geometry; frozen baseline in `src/players.py` + `src/events.py`) to **v1 — ball net-crossings** (YOLOv8x `sports ball` detection → single-ball tracker → count net-line crossings → cluster bursts into rally segments). v1 is the primary effort because player-activity markers measured *inverted* on real casual-play footage (dead time was more active than dink rallies). Both paths share `src/segment.py`, `src/render.py`, and the [eval harness](testing/evaluation.md). Details: [Architecture](architecture/overview.md) and [Rally Detection Concepts](concepts/rally-detection.md).

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
- **Entry points today**: `calibrate.py` (click 12 court points + 2 net-tape points per camera mount) and `label.py` (rally interval labeler with `--review` mode). `cut.py` does not exist yet.
- **`src/`**: detection modules — `ball.py`, `track.py`, `players.py`, `events.py`, `segment.py`, `render.py`. No stubs; files appear as phases land.
- **`eval/`**: `harness.py` (temporal-IoU matching → PRD §5 metric tables) and `labels/` (JSONL ground truth per clip).
- **`tests/`**: 53 pytest unit tests, all dependency-light (no torch/YOLO needed to run them).
- **`Makefile`**: `make test`, `make eval` (scores `rallies.json` against `eval/labels/IMG_7652.jsonl`).
- Video files, YOLO weights (`yolov8n.pt`, `yolov8x.pt`), `cache/`, and `tallies/` are local working artifacts, mostly gitignored.

## Invariants worth knowing before touching code

1. **Timestamps come from PTS, never `frame_index / fps`** (TECH_SPEC §1.1); temporal params are configured in seconds (`config.yaml`), converted to frames at runtime.
2. **Detection is measured before selection, never on the 10-min reel** (PRD §5); `eval-set-A` is locked — tune only on `dev-set-B`.
3. **Every quality claim must be measurable against labeled holdout** — honest measurement is the non-negotiable point of the prototype.
4. The pipeline **degrades rather than fails** (ADR-003): audio is optional, ball trajectory is gated, video-only is the floor.

## Backlog

Areas identified but not yet documented in depth (mostly because the code doesn't exist yet):

- **Selection & ranking** (`src/select.py`, TECH_SPEC §7) — not built; will deserve a page when the ranker lands.
- **`cut.py` end-to-end orchestrator** — not built; the final wiring step (`detect_candidates → track_ball → crossing_times → cluster_crossings → cut_clips`).
- **Audio path** (`src/audio.py`, TECH_SPEC §5.1b, Phase 2.5) — not started; conditional on a usability gate.
- **Capture preflight** (`src/capture.py`, TECH_SPEC §1.1) — documented procedurally in [Operations](operations/runbook.md); module not written.
- **STRATEGY.md business model** (B2B2C HaaS, venue deployment, ADR-024/033/034) — summarized above only; exploratory and gated on prototype success.
