---
type: Runbook
title: Operations & Status — camera pitfalls, config, phase gates
description: Operational knowledge for pic-vision — camera/capture pitfalls with their ADRs, config surface and invariants, compute/runtime constraints on the M2, and the current phase-gate status from CHECKLIST.md with what remains unbuilt.
tags: [operations, runbook, camera, config, phase-status]
resource: CHECKLIST.md
---

# Operations & Runbook

## Phase status at a glance (CHECKLIST.md)

| Phase | Gate | Status |
|---|---|---|
| 0 — Instrument (calibrate, label, harness) | Harness reports both PRD tables on a stub | **PASSED** (eval-set-A not formally locked yet — do before any tuning run) |
| 0.5 — Benchmark prior art | Baseline number exists | NOT DONE (qualitative only; deprioritized since v1 went direct to detection) |
| 0.6 — Validate dead-time inversion | Markers near-zero during rallies | **FAILED → SKIPPED** (markers inverted on real footage → ADR-039 pivot to v1) |
| 1 — Core pipeline, v0 path | Watchable ≤ 10-min reel, measured | NOT DONE — components exist, not wired, no numbers |
| 1 — v1 path (primary) | Same, on clean footage | NOT DONE — **all primitives built + tested; blocked on one clean clip** |
| 1.5 — Boundary refinement | ≤ 1.0 s boundary error | NOT STARTED |
| 2 — Ball presence | FP improves, recall holds | PARTIAL (detector + tracker + size filter in; shoe filter missing) |
| 2.5 — Audio (conditional) | Usability gate passes, then helps | NOT STARTED |
| 3 / 3.5 / 4 — Trajectory / ranker / tidy | Gated | NOT STARTED |

**Not built:** `src/capture.py` (preflight), `src/motion.py` (T0′ pre-filter), `src/select.py` (ranker), `cut.py` (orchestrator — the final wiring step). **Built:** everything else in `src/` plus `calibrate.py`, `label.py`, `eval/harness.py`, 53 tests.

## Capture pitfalls

Camera: **Tapo C200 V3, fixed at 1080p/30 fps** (ADR-025 — fixing the frame rate also caps exposure at 1/30 s, bounding ball smear; ADR-002 — lighting, not frame rate, is the binding constraint; indoor gyms are expected to fail ball tracking). If replacing the camera, judge by **pixels-on-ball at the far baseline**, not sensor resolution, and use the ADR-029 shopping list.

Measured/observed on this rig:

- **Wifi RTSP delivers ~90–96% of frames** (n=4), with bursty 1–4 s stalls; worst observed case dropped to ~12.5%. Untested on congested venue networks or full 2-hour sessions. Prefer microSD local recording once available (ADR-032) — removes the network dependency entirely. SD sizing: ~1.26–5.4 GB per 2-hour session, buy ≥ 64 GB (verify card format; FAT32 caps at 32 GB).
- **Camera RTP timestamps are unreliable and non-monotonic** → always `-use_wallclock_as_timestamps 1` (ADR-030). Caveat: ffmpeg still logged `Timestamps are unset in a packet` on MKV writes; output probed clean, but verify before trusting a real session.
- **Hard kills corrupt the container** → stop with `-t N` or SIGINT (ADR-031).
- **`pcm_alaw` audio → MKV container required**; MP4 rejects the codec tag.
- Preflight (one-time, TECH_SPEC §1.1): confirm CFR 30 via `nb_read_frames / duration` on a short probe recording (RTSP live probes report `avg_frame_rate` as 0/0) and a PTS-delta histogram (~0.0333 s uniform). Trust `avg_frame_rate`, never `r_frame_rate`.
- The mount must not move mid-session; calibration is per-mount. The 2026-08 footage taught the stronger version: **no zoom, no pan** — a single calibration can't hold across a zooming clip (net line moved y=260→170 within one file).

## Config & invariants

`config.yaml` is intentionally minimal and grows per phase, not by guessing: `capture.fps: 30`, `capture.resolution: [1920, 1080]`, `output.highlight_budget_sec: 600`. Two standing rules (TECH_SPEC §1.1): temporal parameters are configured **in seconds** and converted to frames at runtime; timestamps come from **PTS**.

Privacy is a product constraint, not a feature (PRD §6): footage stays local by default, nothing retained in cloud past a processing window, no face recognition / non-consented re-identification ever (ADR-034 prefers opt-in check-in over biometric re-ID for any future identity feature).

## Compute reality (MacBook Air M2, fanless)

- Estimates in TECH_SPEC §9 are FLOPs arithmetic, **not measurements** — the Phase 0 benchmark table in EXPERIMENTS.md ("Pending") is the list of numbers still owed (decode throughput, YOLO CoreML-vs-Metal, thermal behavior, end-to-end wall clock).
- Fanless → sustained loads throttle 20–40%.
- 8 GB RAM → stream frames, accumulate only per-timestep scalars, never hold frame arrays (all current modules follow this: OpenCV `VideoCapture` loops, no frame storage).
- Sampling rate is the cost lever; `detect_ball(sample_fps=10)` exists for affordable whole-clip scans.
- Encoding: `src/render.py` uses libx264/veryfast + faststart (clips play inline everywhere); the spec's `accurate` mode calls for `h264_videotoolbox` when the full reel renderer lands. OpenCV's default mp4v output is **not** web-playable — re-encode to H.264 before delivery (noted in EXPERIMENTS 2026-08-10).
- Do not use moviepy (slow/fragile at 200k-frame scale); ffmpeg via subprocess, as `render.py` does.

## Repo housekeeping

- `main` is local-only, ahead of origin (unpushed, per PROGRESS.md).
- Video sources, `yolov8*.pt` weights, and `cache/` are local artifacts — don't commit them.
- The OpenWiki GitHub Action (`.github/workflows/openwiki-update.yml`) regenerates this wiki daily via PR; don't hand-edit generated pages.
- `AGENTS.md`/`CLAUDE.md` point agents at this wiki; `/openwiki/INSTRUCTIONS.md` is the user-authored brief.

Related: [Key Workflows](../workflows/pipeline.md) for the operator recipes, [Architecture](../architecture/overview.md) for why the pipeline is shaped this way, [Source Map](../source-map.md) for file-level orientation.
