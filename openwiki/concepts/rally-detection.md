---
type: Domain Concept
title: Rally Detection Concepts — rallies, net crossings, TrackNet, calibration
description: Domain vocabulary and core mechanisms of pic-vision's rally detection — the rally definition, why net-crossing count is the rally signal, the backend-agnostic crossing spine, the active TrackNet detector and the retired YOLO one, the single-ball tracker, court calibration, and the failure modes measured on real footage.
tags: [domain, rally, ball-tracking, calibration, net-crossing, tracknet]
resource: src/ball.py
openwiki:
  roles: [domain]
  change_kinds: [detection-pipeline]
  source_paths: [src/ball.py, src/tracknet.py, src/track.py, src/calib.py]
  symbols: [crossing_times, cluster_crossings, count_crossings, net_line_y, ball_box_ok, load_predictions, track_ball]
  test_paths: [tests/test_ball.py, tests/test_tracknet.py, tests/test_track.py, tests/test_calib.py]
  invariants: ["A rally = burst of >= min_crossings net-crossings within gap_sec; courtesy returns produce exactly one crossing and must be rejected.", "Crossing math works in image space, not court space (ball is above the ground plane)."]
  validation_commands: [python3 -m pytest tests/test_ball.py -q]
---

# Rally Detection Concepts

## What a rally is (LABELING.md v2)

A **rally** runs from **serve contact to the moment the ball becomes dead** — next touches the ground or goes out of play. "Ball-dead" is deliberately later than "last paddle contact" (up to ~1 s on balls sailing long, a large fraction of the 1.0 s boundary target). Edge cases decided once and frozen: serve faults and courtesy returns are never rallies; warm-up is excluded; interrupted rallies are labeled up to the interruption. Courtesy returns are *non-negotiable* non-rallies because they are the exact false positive the detector must reject — one happens after every point, so the error is systematic, not rare.

## The v1 signal: net crossings

The core idea (ADR-022, extended): a rally is a sequence of ball exchanges, and every exchange crosses the net. So **count the times the ball's image-y crosses the net line** and you have a rally signal that is strong exactly where player motion is weak (dink rallies — the case that killed v0).

Mechanics, all in `src/ball.py` (deliberately **backend-agnostic** — these functions accept any timed ball track: TrackNet, YOLO, or synthetic; this is what let ADR-046 swap detectors without touching the spine):

- **Image space, not court space.** The ball flies above the ground plane, so the calibration homography mis-projects it (parallax). From a behind-baseline camera, large image-y = near side, small image-y = far side. `net_line_y(calib)` gives the net's image-y: it **prefers the two hand-marked net-tape clicks** from `calibrate.py` and falls back to projecting court-y=22 through the homography (`net_image_y`). The marked line exists because the derived line landed *below* the real net on zoomed footage (EXPERIMENTS 2026-08-10) — mark the **top of the tape**, since the ball crosses over it. When no calibration exists, `src/calib.py` resolves the line directly: interactive one-click picker (`pick_net_y`, the default) or headless Hough estimate (`detect_net_y`, rough) — priority order in ADR-041.
- **Hysteresis band.** `count_crossings` / `crossing_times` classify each frame near/far only when the ball is outside `net_y ± band`; frames inside the band or with no detection are skipped. This stops jitter near the net from inflating the count. The band encodes **court geometry, not detection quality** (ADR-042): during dink rallies the ball hovers within ±20 px of the net line, so band must be tuned per camera angle (expected 15–30 px at behind-baseline 1080p) even with a perfect detector. Tuning order: net_y → band → fine-tune model → recheck band.
- **Bursts → rallies.** `cluster_crossings(times, gap_sec, min_crossings)` groups crossings within `gap_sec` into segments and keeps only bursts with ≥ `min_crossings` — the courtesy-return suppressor (a tap-back produces exactly one crossing; a real rally several). Validated defaults for the TrackNet path: `gap_sec=3.0, min_crossings=3` (EXPERIMENTS 2026-08-12; `gap_sec=1.0` dissolves real rallies since crossings can be ~2 s apart).

## TrackNet — the active detector (ADR-046)

TrackNet is a 3-frame heatmap architecture: three consecutive frames → per-frame ball-position heatmap, thresholded at 0.5, largest blob wins. It sees the small, fast ball *across the net* where YOLO largely misses it — on the rally-#3 benchmark window it found **25 crossings vs YOLO's 5** (EXPERIMENTS 2026-08-12), even with domain-mismatched badminton weights. That 5× gap was too large to bridge with tuning, so the YOLO path was retired.

It is **CUDA-only** (TF Conv2D NCHW requires an NVIDIA GPU — the 2026-08-11 detector survey found it cannot run on macOS), so inference runs on a **RunPod GPU pod** (~$0.28/hr; ADR-043's proxy trick — upload 720p, cut full-res locally — applies at venue scale):

- `scripts/pod_infer.py` runs **on the pod**: loads `TNV2_old_weights.h5` with `compile=False` (Keras 3 refuses the legacy optimizer config), and emits `predictions.csv` with `Frame,Visibility,X,Y` at full frame rate, coordinates scaled to source resolution.
- `src/tracknet.py` runs **locally**: `load_predictions` parses the CSV into a `(time_sec, y or None)` track (frame numbers ÷ fps; `Visibility=0` → `None`), then `rally_segments_from_predictions` feeds that track through the unchanged `crossing_times` → `cluster_crossings` spine.
- `src/cut.py` glues it together (`cut_rallies_from_predictions`): segments get `score = crossings` (the exchange-count ranking from ADR-039), then `cut_clips` + `concat_clips` produce clips, `manifest.json`, and `highlight.mp4`. Full operator flow: [Key Workflows](../workflows/pipeline.md#5-run-detection-tracknet--runpod--the-active-path).

**Open caveats (measured, not yet resolved):** the pickleball fine-tuned weights won't load under TF 2.21/Keras 3 (TF 2.13 + Python 3.10 pod image or `.keras` re-export needed — the RTX 2000 Ada workstation is the target); TrackNet's dead-time FP rate is unmeasured (the 659–666 s control window has only been run through the *YOLO+tracker* path); the 54.5% visible-frame rate on the benchmark likely contains badminton-domain false positives. A full-video run on IMG_7655 (36 labeled rallies) produced 5/36 usable clips (14% recall) — the mechanism works but is not yet benchmark-grade; clean footage is the gate.

## The retired YOLO detector (`archive/`, ADR-046)

The first ball detector ran locally: `detect_ball`/`detect_candidates` used off-the-shelf **yolov8x** on COCO class 32 (`sports ball`) at `imgsz=1280` (never 640 — ADR-006 measures ~60% → ~100% detection at 1280), with a `ball_box_ok` size/aspect filter (`max_ball_px` **mandatory**, ADR-045 — without it the class latches onto 30–60 px player heads/torsos instead of the 10–21 px ball) and the single-ball tracker below. Two facts killed it: yolov8x scores only 0.2–0.3 confidence **at the net** — *the crossing moment is intrinsically the hardest detection from a behind-baseline camera* — and TrackNet's 5× crossing count on identical footage. The code lives in `archive/yolo_detect.py` + `archive/yolo_pipeline.py` with its tests, recoverable if a local-inference path (fine-tuned yolov8n on Jetson, ADR-040) ever beats TrackNet on clean footage. `ball_box_ok` stays in `src/ball.py` as shared signal-side code. CoreML export (`yolov8x.mlpackage`, 1.7× on ANE, ADR-044) was the local-speed fix while the YOLO path was live.

## The single-ball tracker (`src/track.py`) — YOLO-era, concept still load-bearing

The third failure mode found on real footage: in a multi-court gym a per-frame detector finds *real* balls that aren't in play (adjacent courts, idle balls). "Best ball anywhere per frame" hops between them, flipping net sides → phantom crossings during dead time. The standing regression evidence (YOLO path, CHECKLIST.md/PROGRESS.md): IMG_7652 659–666 s dead window produced **22 crossings without the tracker → 0 with it**, while the 58–77.5 s rally kept a strong 16.

`track_ball(frames, max_jump, reset_after=15)` follows one ball: initialize on the most confident candidate, then take the nearest candidate within `max_jump` px each frame; anything farther is a teleport (a different ball) and is rejected as a gap. After `reset_after` consecutive gaps the track releases so a new rally can re-acquire. It needs **dense per-frame candidates** so real ball motion stays under `max_jump` between frames. This is the "ball cannot teleport" max-step constraint arrived at independently by both prior-art projects (TECH_SPEC §2).

The tracker is **not in the active TrackNet path** — TrackNet emits a single position per frame, so there are no competing candidates to disambiguate. It stays in-tree (used by `scripts/scan_crossings.py`), and its dead-window discipline is the template for the TrackNet FP control that still has to be run (the 659–666 s window through TrackNet).

## Court calibration (`calibrate.py`)

Manual, once per camera mount (ADR-007 — three prior-art projects independently concluded hand-clicking beats trained keypoint regressors on unfamiliar angles). The operator clicks **12 court intersections in any order** (order-independent assignment, ADR-035 — a real 28.2 ft mis-ordered calibration recovered to 0.36 ft) **plus 2 net-tape points**, onto a canonical 20 × 44 ft court (net at y=22, NVZ lines at y=15/29). Output JSON: homography, per-point and RMSE reprojection error (feet), and `net_image_points`. `src/players.py` consumes the homography (`load_calibration`, `to_court`); `src/ball.py` consumes the net points.

## v0 player markers (frozen baseline)

`src/players.py` (YOLO person detection → foot point → court feet → asymmetric on-court filter: tight ±4 ft sidelines, generous ±10 ft baselines for lob retrieval) and `src/events.py` (`mean_motion` — tracking-free nearest-neighbour displacement; `n_at_kitchen` — players within 4 ft of an NVZ line, the dink-formation signal that is live even at near-zero motion). These implement the ADR-037 two-sided marker idea. They measured **inverted** on casual play (2026-08-08) — dead time more active than low-energy rallies — which is why v1 is primary, but v0 was never fairly tested (compromised footage), so it stays frozen per ADR-039.

## Known failure modes (all measured, EXPERIMENTS.md)

1. **Zoom/pan invalidates everything** — the net line moved y=260 → 170 between two rallies of one clip. Fixed mount is non-negotiable; one calibration cannot hold across a zooming clip.
2. **Derived net line ≠ real net** on any calibration made from a differently-framed shot → mark the net directly (shipped).
3. **Small far ball at the net** — confidence cutoff alone can't catch crossings. YOLO's answer (size filter + tracker) measured insufficient → TrackNet; a higher/side-on mount remains a capture lever (ADR-038: prove software before hardware).
4. **Out-of-play balls** — fixed for the YOLO path by the tracker (above); for TrackNet the equivalent FP control (dead window through TrackNet) is still owed. An image-region gate for the active court is a noted maybe.
5. **Dink rallies vs. dead time** — indistinguishable by player motion; the reason the ball signal exists.

How these get measured: [Testing & Evaluation](../testing/evaluation.md). How an operator runs the recipe end-to-end: [Key Workflows](../workflows/pipeline.md). Where each function lives: [Source Map](../source-map.md).
