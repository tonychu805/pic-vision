---
type: Runbook
title: Operations & Status — camera pitfalls, config, compute, phase gates
description: Operational knowledge for pic-vision — camera/capture pitfalls with their ADRs, config surface and invariants, compute reality (RunPod GPU for inference, CoreML/M2 and RTX 2000 Ada locally), and the current phase-gate status from CHECKLIST.md with what remains unbuilt.
tags: [operations, runbook, camera, config, phase-status, runpod]
resource: CHECKLIST.md
openwiki:
  roles: [operations]
  change_kinds: [operations, capture]
  source_paths: [config.yaml, Makefile, scripts/pod_infer.py]
  symbols: [pick_net_y, detect_net_y]
  validation_commands: [python3 -m pytest -q]
---

# Operations & Runbook

## Phase status at a glance (CHECKLIST.md)

| Phase | Gate | Status |
|---|---|---|
| 0 — Instrument (calibrate, label, harness) | Harness reports both PRD tables on a stub | **PASSED** (eval-set-A not formally locked yet — do before any tuning run) |
| 0.5 — Benchmark prior art | Baseline number exists | NOT DONE (qualitative only; deprioritized since v1 went direct to detection) |
| 0.6 — Validate dead-time inversion | Markers near-zero during rallies | **FAILED → SKIPPED** (markers inverted on real footage → ADR-039 pivot to v1) |
| 1 — Core pipeline, v0 path | Watchable ≤ 10-min reel, measured | NOT DONE — v0 frozen; superseded in the hot path by ADR-046/047 |
| 1 — TrackNet path (primary) | Same, on clean footage | NOT DONE — **e2e wired and runnable** (`pod_infer.py` → `make process`); blocked on one clean clip for metrics |
| 1.5 — Boundary refinement | ≤ 1.0 s boundary error | NOT STARTED |
| 2 — Ball presence | FP improves, recall holds | PARTIAL (absorbed into the ball-primary path; shoe filter missing) |
| 2.5 — Audio (conditional) | Usability gate passes, then helps | NOT STARTED |
| 3 / 3.5 / 4 — Trajectory / ranker / tidy | Gated | NOT STARTED (`select.py` not built; root one-command `cut.py` per NFR7 not built) |

**Not built:** `src/capture.py` (preflight), `src/motion.py` (T0′ pre-filter), `src/select.py` (ranker + 600 s budget enforce), root `cut.py` (NFR7 single command with capture→select→render), stage caching (NFR3), `run.log` (NFR9). **Built:** TrackNet path end-to-end (`scripts/pod_infer.py`, `src/tracknet.py` incl. the multi-court X-gate + `track_ball` wiring, `src/cut.py`, `src/render.py` incl. `concat_clips` + `pad_sec`), net-line tooling (`src/calib.py` picker + Hough + `court_x_range`), `calibrate.py` (12+2 clicks), `label.py`, `eval/harness.py`, frozen v0 (`players.py`, `events.py`), `track.py` (single-ball tracker, shared by both eras), 67 tests.

**Standing measurement debts** (CHECKLIST.md): TrackNet FP rate on the 659–666 s dead window; pickleball fine-tuned weights loading (TF 2.11 SavedModel vs Keras 3 — TF 2.13/Py3.10 pod or `.keras` re-export); recall/FP/boundary numbers on `eval-set-A` (all blocked on the same clean clip).

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

## Compute reality (split: cloud GPU for detection, local for the rest)

- **Detection runs on a RunPod GPU pod** (ADR-046) — TrackNet is CUDA-only (TF Conv2D NCHW is unsupported on macOS/Apple Silicon). Community RTX 3090 pod ≈ $0.22–0.28/hr; a full session's inference is minutes. Known pod-side gotchas: load weights with `compile=False` (Keras 3 chokes on the legacy Adadelta config); the pickleball fine-tuned SavedModel needs TF 2.13/Python 3.10 or a `.keras` re-export.
- **An RTX 2000 Ada workstation is now available** (2026-08-12, 16 GB VRAM) — designated for PoC iteration and TrackNet fine-tuning instead of the M2; use the `tensorflow/tensorflow:2.11.0-gpu` Docker image for the legacy weights.
- **Local machine (MacBook Air M2, fanless):** decode + ffmpeg cutting only — cheap. Estimates in TECH_SPEC §9 are FLOPs arithmetic, **not measurements**; fanless sustained loads throttle 20–40%; 8 GB RAM → stream frames, never hold frame arrays (all modules follow this).
- **Production direction** (ADR-043, post-prototype): N100 edge box captures full-res → encodes a 720p/2 Mbps proxy (~90 MB/hr, ~8× smaller than full-res) → cloud GPU returns *timestamps only* → N100 cuts from local full-res. Raw footage never leaves the building (privacy); a 50 Mbps venue uplink supports ~25 courts.
- **Archived local-inference notes** (if the YOLO path returns, ADR-040): CoreML `yolov8x.mlpackage` at imgsz=1280 measured 216 ms/frame ANE vs 365 CPU (1.7×, ADR-044); export imgsz must match inference imgsz.
- Encoding: `src/render.py` uses libx264/veryfast + faststart (clips play inline everywhere); the spec's `accurate` mode calls for `h264_videotoolbox` when the full reel renderer lands. OpenCV's default mp4v output is **not** web-playable — re-encode to H.264 before delivery (noted in EXPERIMENTS 2026-08-10).
- Do not use moviepy (slow/fragile at 200k-frame scale); ffmpeg via subprocess, as `render.py` does.

## Repo housekeeping

- `main` is pushed to `origin` (per PROGRESS.md 2026-08-12); active pipeline work happened on `feat/rally-pipeline` and `feat/ball-recipe` branches.
- Video sources, YOLO weights (`yolov8x.pt`, `yolov8x.mlpackage`), and `cache/` are local artifacts — don't commit them. TrackNet weights live **on the pod** (`/workspace/TNV2_old_weights.h5`, from AndrewDettor's TrackNet-Pickleball repo), not in this repo.
- The OpenWiki GitHub Action (`.github/workflows/openwiki-update.yml`) regenerates this wiki daily via PR; don't hand-edit generated pages.
- `AGENTS.md`/`CLAUDE.md` point agents at this wiki; `/openwiki/INSTRUCTIONS.md` is the user-authored brief.

Related: [Key Workflows](../workflows/pipeline.md) for the operator recipes, [Architecture](../architecture/overview.md) for why the pipeline is shaped this way, [Source Map](../source-map.md) for file-level orientation.
