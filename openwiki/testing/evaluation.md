---
type: Testing Guide
title: Testing & Evaluation — harness, labels, benchmark windows, test suite
description: How pic-vision proves quality — the eval harness (temporal IoU, detection/selection metric tables), label files and set discipline, the human-verified benchmark windows that regression-test detector changes, and the 53-test pytest suite conventions.
tags: [testing, evaluation, harness, metrics, labels]
resource: eval/harness.py
---

# Testing & Evaluation

Honest measurement against labeled holdout is the non-negotiable point of the prototype (PRD §1). Two measurement layers exist: the **eval harness** (scores `rallies.json` against labels) and the **benchmark windows** (human-verified clip segments for eyeballing detector changes before any harness number means anything).

## Eval harness (`eval/harness.py`)

Reads JSON only, never video. `rallies.json` is the single contract between detection and evaluation (TECH_SPEC §11.3).

- **Matching:** temporal IoU ≥ 0.5, greedy one-to-one assignment by descending IoU (`match_intervals`) — one prediction spanning two labeled rallies can claim only one.
- **Detection table** (ignores `selected`): recall (target ≥ 0.90), false positives per 10 min (≤ 1.0), median boundary error (≤ 1.0 s). Detection is measured on the complete rally list, *before* selection — otherwise "dropped to fit budget" is indistinguishable from "failed to detect" (ADR-018).
- **Selection table** (reads `selected`): budget compliance (≤ 600 s, hard — a violation fails the run rather than emitting a non-conforming file), utilization (≥ 0.85), rally count (≥ 12), keep rate (reported, not targeted).
- Run it: `make eval` → `python3 -m eval.harness --pred rallies.json --labels eval/labels/IMG_7652.jsonl`.

**Anti-metrics — do not optimize:** compression ratio (gamed by cutting aggressively) and budget utilization alone (padded rallies fill budget at lower quality; only meaningful next to rally count).

## Label sets and discipline

`eval/labels/*.jsonl` — one `{"start", "end", "duration", "rally_id"}` object per line, written by `label.py`. Current files: `IMG_7652.jsonl` (9 curated competitive rallies), `IMG_7655.jsonl`, `austin_rally2.jsonl` (broadcast dev-scaffold clip).

The three planned sets (TECH_SPEC §11.1) — `eval-set-A` (20 min daylight, **locked, never tuned against**), `dev-set-B` (different session, all tuning), `eval-set-C` (10 min poor light) — exist as *labels* but roles aren't formally assigned and A isn't locked yet (CHECKLIST flags this as a pre-tuning to-do). Rules that protect the numbers: never split one session across dev and eval; tune only on B; any recall regression on A reverts regardless of how the reel looks. LABELING.md also prescribes a one-time **self-consistency check** (label the same 5 min twice, a day apart) — that number is the noise floor under every metric.

## Benchmark windows

Concrete human-verified windows from the (compromised) footage, per-window hand-measured net lines, used to check any detector change before clean footage exists. Source: PROGRESS.md + CHECKLIST.md.

| Window | Type | v1 no tracker | v1 + tracker | Target |
|---|---|---|---|---|
| IMG_7652 58–77.5 s (net y=260) | RALLY | 33 crossings | 15 crossings | high ✅ |
| IMG_7652 620–638 s (net y=170) | RALLY | 12 | not re-run | high ✅ |
| IMG_7655 86–101 s (net y=210) | RALLY | 20 | not re-run | high ✅ |
| **IMG_7652 659–666 s (net y=160)** | **DEAD** | **18** | **0** | ~0 ✅ (tracker) |

The 659–666 s dead window is the **standing regression test for the tracker**: any change that lets out-of-play balls produce phantom crossings shows up here first. A clean fixed clip will replace these per-window lines with one calibration.

## Unit test suite (`tests/`, 53 tests, `make test`)

Built test-first throughout (git history: harness and segmenter landed with tests before the detectors they score). Conventions worth preserving:

- **Dependency-light:** torch/ultralytics is imported lazily inside functions (`players.py`, `ball.py`), so the whole suite runs without a GPU, model weights, or video files.
- **Synthetic signals over fixtures:** tests construct tiny tracks/series (`test_ball.py`'s crossing sequences, `test_track.py`'s smooth-ball-vs-distractor frames) rather than storing video.
- **Behavior-named cases:** e.g. `test_match_one_prediction_cannot_claim_two_labels`, `test_rejects_teleport_to_far_ball`, `test_reacquires_after_long_gap`, `test_net_line_y_prefers_marked_net` — the test names document the ADR-backed rule.

Coverage map: `test_harness.py` (IoU/matching/metrics, 12), `test_calibrate.py` (order-independent assignment, homography fit, 3), `test_ball.py` (14: net line, size filter, crossings, clustering), `test_track.py` (4), `test_players.py` (5) / `test_events.py` (6) (v0 front-end), `test_segment.py` (4), `test_render.py` (2: ffmpeg command shape, manifest), `test_label.py` (3: I/O + review mode).

## What to run when changing things

- Touching matching/metrics → `test_harness.py` + re-run `make eval` on a known `rallies.json`.
- Touching detection or the tracker → the four benchmark windows above, then the harness; record the run in EXPERIMENTS.md (hypothesis first, one change per entry).
- Touching calibration → `test_calibrate.py` and a fresh re-click on real footage (the 0.356 ft RMSE check is the reference).
- Any selection/budget change → the harness's selection table is the check; budget violation must fail loudly.

See [Rally Detection Concepts](../concepts/rally-detection.md) for the mechanisms under test and [Key Workflows](../workflows/pipeline.md) for the operator sequence these checks slot into.
