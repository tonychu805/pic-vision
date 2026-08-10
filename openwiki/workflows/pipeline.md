---
type: Workflow
title: Key Workflows — capture, calibrate, detect, cut, score
description: Operator workflows for pic-vision — the clean-footage capture gate, per-mount calibration, rally labeling and review, the shipped v1 detection recipe (detect_candidates → track_ball → crossing_times → cluster_crossings → cut_clips), and scoring with make eval.
tags: [workflow, runbook, capture, calibration, detection-recipe]
resource: PROGRESS.md
---

# Key Workflows

The pipeline runs batch on local files, never live (ADR-013). The end-to-end orchestrator `cut.py` is **not built yet** — the steps below are run as separate tools/library calls until it's wired (Phase 1 back half; see [Operations & Status](../operations/runbook.md)).

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

Click order is free (ADR-035): the **12 court points** in any order, then the **2 net-tape points** (top of the net, left and right ends — the ball crosses over the tape). `u` undo, `r` reset, ENTER saves once all 14 are placed. Reprojection RMSE > 5 px fails and prompts a re-click. Output feeds both the player homography and the v1 net line (`net_line_y` prefers the marked net; rationale in [Rally Detection Concepts](../concepts/rally-detection.md#court-calibration-calibratepy)).

## 3. Label rallies (eval ground truth)

```bash
python label.py session.mp4 --out eval/labels/session-001.jsonl --from 600 --to 1800
python label.py session.mp4 --out eval/labels/session-001.jsonl --review   # keep/drop pass
```

Keys: `s`/`e` mark start/end, `j/l`/`J/L` seek 2 s/10 s, `u` undo, `q` save+quit. `--review` plays each labeled segment for keep (`k`) / drop (`d`) — built to curate the auto-annotator's output (it curated IMG_7652 from 32 auto-labels down to 9 competitive rallies). The labeling rules are frozen in LABELING.md v2 ([concepts page](../concepts/rally-detection.md#what-a-rally-is-labelingmd-v2)). Protocol rules that matter: label continuous blocks, never cherry-pick; **never split one session across dev and eval sets**; competitive rallies only.

## 4. Run v1 detection (shipped recipe)

From PROGRESS.md's "single gate" block — the exact chain to run once clean footage exists:

1. **Measure the ball's pixel size on the footage** and set `max_ball_px` (it is deliberately unset; it can't be tuned on zoomed clips).
2. `detect_candidates(video, weights="yolov8x.pt", max_ball_px=<measured>)` → per-frame candidate lists (`src/ball.py`).
3. `track_ball(candidates, max_jump=…)` → one ball's image-y per frame, teleports rejected (`src/track.py`).
4. `crossing_times(track, net_y=net_line_y(calib), band=…)` → crossing timestamps (`src/ball.py`).
5. `cluster_crossings(times, gap_sec=…, min_crossings≈5)` → rally segments.
6. Sanity-check against the benchmark windows before believing any change ([Testing](../testing/evaluation.md#benchmark-windows)).
7. `cut_clips(video, segments, out_dir)` → H.264 clips + `manifest.json` (`src/render.py`).

For a cheap whole-clip scan, `detect_ball(..., sample_fps=10)` trades exact crossing counts for speed (YOLO is skipped on non-sampled frames; decode is cheap, YOLO isn't).

## 5. Score against labels

```bash
make eval    # python3 -m eval.harness --pred rallies.json --labels eval/labels/IMG_7652.jsonl
```

The harness reads `rallies.json` (never rendered video) and prints both PRD §5 tables — detection (recall ≥ 0.90, FP ≤ 1.0/10 min, boundary error ≤ 1.0 s) and selection (budget ≤ 600 s hard, utilization ≥ 0.85, ≥ 12 rallies). Mechanics and targets: [Testing & Evaluation](../testing/evaluation.md).

## 6. The feedback loop the docs enforce

This repo's process is part of the workflow: a run that produces a number goes in `EXPERIMENTS.md` (append-only, hypothesis recorded *before* the result; one change per entry); a durable conclusion becomes an ADR in `DECISIONS.md`; `PROGRESS.md` gets the plain-language narrative (newest first); `CHECKLIST.md` tracks phase gates. When changing detection, update all four — future sessions (human or agent) pick up from PROGRESS's "NEXT SESSION" block, and the subjective gate (watch 3 reels, 2-of-3 "would watch voluntarily") remains a hard gate regardless of metric pass.
