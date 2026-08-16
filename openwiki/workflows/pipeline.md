---
type: Workflow
title: Key Workflows — capture, calibrate, detect, cut, score
description: Operator workflows for pic-vision — the clean-footage capture gate, per-mount calibration, rally labeling and review, the active TrackNet/RunPod detection recipe (pod_infer.py → make process → clips + manifest + highlight.mp4), net-line resolution, and scoring with make eval.
tags: [workflow, runbook, capture, calibration, detection-recipe, tracknet, runpod]
resource: PROGRESS.md
openwiki:
  roles: [workflow, operations]
  change_kinds: [detection-pipeline, operations]
  source_paths: [scripts/pod_infer.py, src/cut.py, src/calib.py, calibrate.py, label.py]
  symbols: [cut_rallies_from_predictions, pick_net_y, detect_net_y, court_x_range]
  test_paths: [tests/test_cut.py, tests/test_calib.py]
  validation_commands: [python3 -m pytest tests/test_cut.py tests/test_calib.py -q]
---

# Key Workflows

The pipeline runs batch, never live (ADR-013), and inference no longer runs on the local machine: ball detection happens on a RunPod GPU pod, everything else is local (ADR-046). The active end-to-end path is `pod_infer.py` (on pod) → `make process` (local) — see step 5. The spec's one-command local orchestrator with ranking (NFR7) is still unbuilt; see [Operations & Status](../operations/runbook.md).

## 1. Capture a session (the current gate)

Target rig: Tapo C200 V3, fixed 1080p/30 fps, behind the baseline, elevated ≥ 8 ft, rigid mount. **No zoom, no pan, whole court in frame, well-lit** — the two existing clips (IMG_7652/7655) failed exactly here and every metric on them is considered compromised.

Record over RTSP in 10-minute segments (crash/drop costs one segment, not the session):

```bash
ffmpeg -rtsp_transport tcp -i "rtsp://user:pass@<cam-ip>/stream1" \
  -use_wallclock_as_timestamps 1 \
  -c copy -f segment -segment_time 600 -reset_timestamps 1 \
  session-%03d.mp4
```

Rules that exist because they bit someone (capture pitfalls: [Operations](../operations/runbook.md#capture-pitfalls)):

- Wallclock timestamps, not camera RTP timestamps (ADR-030).
- Clean stop only: `-t <duration>` or SIGINT; hard kills corrupt the container (ADR-031).
- `pcm_alaw` audio forces the MKV container — MP4 rejects that codec tag.
- All downstream timestamps come from PTS, never `frame_index / fps`.

## 2. Calibrate the mount (once per mount)

```bash
python calibrate.py session.mp4 --at 300 --out court_calibration.json
```

Click order is free (ADR-035): the **12 court points** in any order, then the **2 net-tape points** (top of the net, left and right ends — the ball crosses over the tape). `u` undo, `r` reset, ENTER saves once all 14 are placed. Reprojection RMSE > 5 px fails and prompts a re-click. Output feeds both the player homography and the net line (`net_line_y` prefers the marked net; rationale in [Rally Detection Concepts](../concepts/rally-detection.md#court-calibration-calibratepy)).

## 3. Resolve the net line (ADR-041)

Full calibration is overkill for the TrackNet path — it needs only the net's image-y, not court geometry. `src/cut.py` resolves it in this priority order:

1. `--net-y <value>` — explicit, fastest; reuse a known value for a fixed camera.
2. `--calib <json>` — full calibration JSON from step 2 (`net_line_y` prefers the marked net points) — the right choice for a permanent mount. A `--calib` also auto-derives the **court X-gate** bounds (`court_x_range` from the 12 clicked court points, `--court-margin` px padding, default 50) used in step 5 to reject adjacent-court detections.
3. *(default)* interactive picker — `pick_net_y` shows the first frame with a guide line following the mouse; one click on the net tape. Standalone: `python3 -c "from src.calib import pick_net_y; print(pick_net_y('game.MOV'))"`.
4. `--auto-detect` — headless Hough estimate (`detect_net_y`); rough use / CI only (it tends to find the floor service line ~50 px off, not the net — the net mesh has no strong horizontal edge).

Pick once per camera angle, record the value, and reuse it with `--net-y`. Re-pick whenever the camera moves. Dink rallies hover within ±20 px of the net line — tune `--band` (15–30 px expected for behind-baseline 1080p) to stop jitter from inflating crossings (ADR-042).

## 4. Label rallies (eval ground truth)

```bash
python label.py session.mp4 --out eval/labels/session-001.jsonl --from 600 --to 1800
python label.py session.mp4 --out eval/labels/session-001.jsonl --review   # keep/drop pass
```

Keys: `s`/`e` mark start/end, `j/l`/`J/L` seek 2 s/10 s, `u` undo, `q` save+quit. `--review` plays each labeled segment for keep (`k`) / drop (`d`) — built to curate the auto-annotator's output (it curated IMG_7652 from 32 auto-labels down to 9 competitive rallies). The labeling rules are frozen in LABELING.md v2 ([concepts page](../concepts/rally-detection.md#what-a-rally-is-labelingmd-v2)). Protocol rules that matter: label continuous blocks, never cherry-pick; **never split one session across dev and eval sets**; competitive rallies only.

## 5. Run detection (TrackNet + RunPod — the active path)

ADR-046 retired the YOLO detector (5 crossings vs TrackNet's 25 on the benchmark rally). The active recipe:

1. **Upload the video to a RunPod GPU pod** and run inference there (TrackNet is CUDA-only; old TrackNetV2 weights at `/workspace/TNV2_old_weights.h5`, loaded with `compile=False`):

   ```bash
   python3 scripts/pod_infer.py --video /workspace/game.MOV --output /workspace/predictions.csv
   ```

   The script stacks 3 consecutive frames into a (1,9,288,512) tensor, thresholds the heatmap at 0.5, takes the largest blob per frame, and writes `Frame,Visibility,X,Y` rows at full frame rate (coordinates scaled back to source resolution).

2. **Copy `predictions.csv` back locally**, then cut clips:

   ```bash
   make process VIDEO=game.MOV CSV=predictions.csv OUT=clips/            # interactive net picker
   make process VIDEO=game.MOV CSV=predictions.csv NET_Y=210 OUT=clips/  # reuse known net_y
   ```

   This runs `src/cut.py`: `load_predictions` (CSV → timed ball track, invisible frames → `None`) → **court X-gate** (drop detections outside `court_x_min/max`) → **`track_ball`** (reject within-court teleports) → `crossing_times` (side flips across `net_y ± band`) → `cluster_crossings` (bursts with ≥ `min_crossings` → segments) → score = crossing count → `cut_clips` (H.264, `pad_sec=3` context) → `manifest.json` + `concat_clips` → `highlight.mp4`.

   The X-gate + tracker exist because TrackNet's per-frame best-guess ball can land on an adjacent court's real ball (confirmed 2026-08-16 on IMG_7744), and `track_ball` alone re-acquires on it after real dead time exceeds `reset_after`. Passing `--calib` derives the bounds automatically; in a multi-court gym, prefer `--calib` (or explicit `--court-x-min/--court-x-max`) over `--net-y` alone, which gates nothing.

3. **Validated parameters** (IMG_7655 full-video run, EXPERIMENTS 2026-08-12): `gap_sec=3.0`, `min_crossings=3`. Use `band=15–30` for dink-heavy footage (ADR-042). `cut.py` flags: `--gap-sec --min-crossings --band --pad-sec --court-id --session-id --fps`, plus the tracker/gate knobs `--max-jump --reset-after --court-x-min --court-x-max --court-margin`.

4. Sanity-check against the benchmark windows before believing any change ([Testing](../testing/evaluation.md#benchmark-windows)). Standing gaps: TrackNet's FP rate on the 659–666 s dead window is **not yet measured**, and the pickleball fine-tuned weights are **not yet loaded** (TF 2.11 SavedModel vs Keras 3 format break — use a TF 2.13/Python 3.10 pod image or re-export to `.keras`).

### Archived YOLO path (reference only)

The retired local pipeline — `detect_candidates`/`detect_ball` (yolov8x, `max_ball_px` size filter) → `track_ball` → same crossing/cluster spine — lives in `archive/` (`yolo_detect.py`, `yolo_pipeline.py`), with `scripts/scan_crossings.py` (crossing-cluster scan without cutting) and `scripts/debug_detections.py` (annotated JPEG dump) still pointing at the live spine functions for diagnostics. Its tuning knowledge (`max_ball_px` mandatory, ADR-045; CoreML export, ADR-044) survives in the ADRs if a local-inference path returns (ADR-040). Mechanism detail: [Rally Detection Concepts](../concepts/rally-detection.md).

## 6. Score against labels

```bash
make eval    # python3 -m eval.harness --pred rallies.json --labels eval/labels/IMG_7652.jsonl
```

The harness reads `rallies.json` (never rendered video) and prints both PRD §5 tables — detection (recall ≥ 0.90, FP ≤ 1.0/10 min, boundary error ≤ 1.0 s) and selection (budget ≤ 600 s hard, utilization ≥ 0.85, ≥ 12 rallies). Mechanics and targets: [Testing & Evaluation](../testing/evaluation.md).

## 7. The feedback loop the docs enforce

This repo's process is part of the workflow: a run that produces a number goes in `EXPERIMENTS.md` (append-only, hypothesis recorded *before* the result; one change per entry); a durable conclusion becomes an ADR in `DECISIONS.md`; `PROGRESS.md` gets the plain-language narrative (newest first); `CHECKLIST.md` tracks phase gates. When changing detection, update all four — future sessions (human or agent) pick up from PROGRESS's "NEXT SESSION" block, and the subjective gate (watch 3 reels, 2-of-3 "would watch voluntarily") remains a hard gate regardless of metric pass.
