---
type: Domain Concept
title: Rally Detection Concepts — rallies, net crossings, tracker, calibration
description: Domain vocabulary and core mechanisms of pic-vision's rally detection — the rally definition, why net-crossing count is the rally signal, the single-ball tracker that rejects out-of-play balls, court calibration, and the known failure modes measured on real footage.
tags: [domain, rally, ball-tracking, calibration, net-crossing]
resource: src/ball.py
---

# Rally Detection Concepts

## What a rally is (LABELING.md v2)

A **rally** runs from **serve contact to the moment the ball becomes dead** — next touches the ground or goes out of play. "Ball-dead" is deliberately later than "last paddle contact" (up to ~1 s on balls sailing long, a large fraction of the 1.0 s boundary target). Edge cases decided once and frozen: serve faults and courtesy returns are never rallies; warm-up is excluded; interrupted rallies are labeled up to the interruption. Courtesy returns are *non-negotiable* non-rallies because they are the exact false positive the detector must reject — one happens after every point, so the error is systematic, not rare.

## The v1 signal: net crossings

The core idea (ADR-022, extended): a rally is a sequence of ball exchanges, and every exchange crosses the net. So **count the times the ball's image-y crosses the net line** and you have a rally signal that is strong exactly where player motion is weak (dink rallies — the case that killed v0).

Mechanics, all in `src/ball.py`:

- **Image space, not court space.** The ball flies above the ground plane, so the calibration homography mis-projects it (parallax). From a behind-baseline camera, large image-y = near side, small image-y = far side. `net_line_y(calib)` gives the net's image-y: it **prefers the two hand-marked net-tape clicks** from `calibrate.py` and falls back to projecting court-y=22 through the homography (`net_image_y`). The marked line exists because the derived line landed *below* the real net on zoomed footage (EXPERIMENTS 2026-08-10) — mark the **top of the tape**, since the ball crosses over it.
- **Hysteresis band.** `count_crossings` / `crossing_times` classify each frame near/far only when the ball is outside `net_y ± band`; frames inside the band or with no detection are skipped. This stops jitter near the net from inflating the count.
- **Detection.** `detect_ball` (best box per frame) and `detect_candidates` (all boxes per frame, the tracker's input) run off-the-shelf **yolov8x** on COCO class 32 (`sports ball`) at `imgsz=1280`, `conf=0.10`. Never downscale to 640 (ADR-006: prior art measures ball detection going ~60% → ~100% from 640 to 1280). yolov8x over nano was a measured fix: nano tagged heads as "ball"; yolov8x finds the real ball (0.91 mid-court confidence) — but only 0.2–0.3 **at the net**, which is small/far from a baseline camera. *The crossing moment is intrinsically the hardest detection from this angle* — a plain confidence cutoff drops exactly the frames that matter.
- **Size filter.** `ball_box_ok(box, max_dim_px)` drops boxes too big or too elongated to be a ball (heads, bodies, limbs). `max_ball_px` **must be measured on the actual footage** — it is currently unset because the zoom-compromised clips can't calibrate it.
- **Bursts → rallies.** `cluster_crossings(times, gap_sec, min_crossings)` groups crossings within `gap_sec` into segments and keeps only bursts with ≥ `min_crossings` — the courtesy-return suppressor (a tap-back produces exactly one crossing; a real rally several). Current suggestion from PROGRESS: `min_crossings ≈ 5`, untuned pending clean footage.

## The single-ball tracker (`src/track.py`) — required, not optional

The third failure mode found on real footage: in a multi-court gym the detector finds *real* balls that aren't in play (adjacent courts, idle balls). "Best ball anywhere per frame" hops between them, flipping net sides → phantom crossings during dead time. The standing regression test (CHECKLIST.md): IMG_7652 659–666 s dead window produced **18 crossings without the tracker → 0 with it**, while the 58–77.5 s rally kept a strong 15.

`track_ball(frames, max_jump, reset_after=15)` follows one ball: initialize on the most confident candidate, then take the nearest candidate within `max_jump` px each frame; anything farther is a teleport (a different ball) and is rejected as a gap. After `reset_after` consecutive gaps the track releases so a new rally can re-acquire. It needs **dense per-frame candidates** so real ball motion stays under `max_jump` between frames. This is the "ball cannot teleport" max-step constraint arrived at independently by both prior-art projects (TECH_SPEC §2). `src/pipeline.py` is the seam that wires the tracker between detection and crossing counting (`detect_candidates → track_ball → crossing_times → cluster_crossings`); `src/cut.py` then turns the resulting segments into clips ([Key Workflows](../workflows/pipeline.md)).

## Court calibration (`calibrate.py`)

Manual, once per camera mount (ADR-007 — three prior-art projects independently concluded hand-clicking beats trained keypoint regressors on unfamiliar angles). The operator clicks **12 court intersections in any order** (order-independent assignment, ADR-035 — a real 28.2 ft mis-ordered calibration recovered to 0.36 ft) **plus 2 net-tape points**, onto a canonical 20 × 44 ft court (net at y=22, NVZ lines at y=15/29). Output JSON: homography, per-point and RMSE reprojection error (feet), and `net_image_points`. `src/players.py` consumes the homography (`load_calibration`, `to_court`); `src/ball.py` consumes the net points.

## v0 player markers (frozen baseline)

`src/players.py` (YOLO person detection → foot point → court feet → asymmetric on-court filter: tight ±4 ft sidelines, generous ±10 ft baselines for lob retrieval) and `src/events.py` (`mean_motion` — tracking-free nearest-neighbour displacement; `n_at_kitchen` — players within 4 ft of an NVZ line, the dink-formation signal that is live even at near-zero motion). These implement the ADR-037 two-sided marker idea. They measured **inverted** on casual play (2026-08-08) — dead time more active than low-energy rallies — which is why v1 is primary, but v0 was never fairly tested (compromised footage), so it stays frozen per ADR-039.

## Known failure modes (all measured, EXPERIMENTS.md)

1. **Zoom/pan invalidates everything** — the net line moved y=260 → 170 between two rallies of one clip. Fixed mount is non-negotiable; one calibration cannot hold across a zooming clip.
2. **Derived net line ≠ real net** on any calibration made from a differently-framed shot → mark the net directly (shipped).
3. **Small far ball at the net** — confidence cutoff alone can't catch crossings; needs size filter + tracker, and possibly a higher/side-on mount (a capture lever, ADR-038: prove software before hardware).
4. **Out-of-play balls** — fixed by the tracker (above); an image-region gate for the active court is a noted maybe.
5. **Dink rallies vs. dead time** — indistinguishable by player motion; the reason the ball signal exists.

How these get measured: [Testing & Evaluation](../testing/evaluation.md). How an operator runs the recipe end-to-end: [Key Workflows](../workflows/pipeline.md). Where each function lives: [Source Map](../source-map.md).
