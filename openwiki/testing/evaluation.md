---
type: Testing Guide
title: Testing & Evaluation — harness, labels, benchmark windows, test suite
description: How pic-vision proves quality — the eval harness (temporal IoU, detection/selection metric tables), label files and set discipline, the human-verified benchmark windows that regression-test detector changes (now including TrackNet-vs-YOLO numbers), and the 65-test pytest suite conventions.
tags: [testing, evaluation, harness, metrics, labels]
resource: eval/harness.py
openwiki:
  roles: [testing]
  change_kinds: [detection-pipeline, metrics]
  source_paths: [eval/harness.py]
  symbols: [match_intervals]
  test_paths: [tests/test_harness.py, tests/test_ball.py, tests/test_tracknet.py, tests/test_cut.py]
  invariants: ["Detection is scored on the full rally list before selection, never on the 10-min reel.", "eval-set-A is locked; tune only on dev-set-B."]
  validation_commands: [python3 -m pytest -q, make eval]
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

Concrete human-verified windows from the (compromised) footage, per-window hand-measured net lines, used to check any detector change before clean footage exists. Source: PROGRESS.md + CHECKLIST.md. YOLO columns are historical (path retired, ADR-046) but remain the regression evidence for the tracker.

| Window | Type | YOLO naive | YOLO + tracker | TrackNet (badminton wts) | Target |
|---|---|---|---|---|---|
| IMG_7652 58–77.5 s (net y=260) | RALLY | 36 crossings (pre-size-filter scans) | 16 crossings | **25 crossings** (5 with best YOLO params, ADR-046) | high ✅ |
| IMG_7652 620–638 s (net y=170) | RALLY | 12 | not re-run | — | high ✅ |
| IMG_7655 86–101 s (net y=210) | RALLY | 20 | not re-run | — | high ✅ |
| **IMG_7652 659–666 s (net y=160)** | **DEAD** | **22** | **0** | **not yet run** | ~0 |

The 659–666 s dead window is the **standing FP control**: the YOLO+tracker path passes it (0); **running TrackNet on it is the key owed number** — TrackNet's 54.5% visible-frame rate on the rally window likely includes badminton-domain false positives, and no dead-time control exists yet (CHECKLIST.md). Separately, a full-video TrackNet run on IMG_7655 (36 labeled rallies, fixed net y=210) yielded 5/36 usable clips — the pipeline runs end-to-end at scale but is not benchmark-grade on compromised footage. A clean fixed clip will replace these per-window lines with one calibration.

## Unit test suite (`tests/`, 65 tests, `make test`)

Built test-first throughout (git history: harness and segmenter landed with tests before the detectors they score). Conventions worth preserving:

- **Dependency-light:** torch/ultralytics/tensorflow are never imported at module top level (lazy in-function imports in `players.py`; TrackNet/TF lives only in `scripts/pod_infer.py`, which has no unit tests by design — it runs on the pod). The whole suite runs without a GPU, model weights, or video files.
- **Synthetic signals over fixtures:** tests construct tiny tracks/series/CSVs (`test_ball.py`'s crossing sequences, `test_tracknet.py`'s temp CSVs, `test_cut.py`'s monkeypatched glue) rather than storing video.
- **Behavior-named cases:** e.g. `test_match_one_prediction_cannot_claim_two_labels`, `test_rejects_teleport_to_far_ball`, `test_reacquires_after_long_gap`, `test_net_line_y_prefers_marked_net`, `test_detect_net_y_finds_horizontal_line` — the test names document the ADR-backed rule.

Coverage map: `test_harness.py` (12 — IoU/matching/metrics), `test_ball.py` (14 — net line, size filter, crossings, clustering), `test_players.py` (5) / `test_events.py` (6) (frozen v0 front-end), `test_track.py` (4 — YOLO-era tracker), `test_segment.py` (4), `test_calibrate.py` (3 — order-independent assignment, homography fit), `test_calib.py` (2 — Hough net detect, empty-video error), `test_tracknet.py` (4 — CSV parsing, fps scaling, burst detection, sparse-crossing rejection), `test_cut.py` (2 — orchestrator glue: score forwarding, empty input), `test_render.py` (5 — ffmpeg command shape, concat, padding, manifest), `test_label.py` (3 — I/O + review mode). Archived YOLO pipeline tests live in `archive/tests/` and are not collected.

## What to run when changing things

- Touching matching/metrics → `test_harness.py` + re-run `make eval` on a known `rallies.json`.
- Touching the crossing/cluster spine (`src/ball.py`), TrackNet parsing, or orchestration → `test_ball.py` + `test_tracknet.py` + `test_cut.py`, then the benchmark windows above; record the run in EXPERIMENTS.md (hypothesis first, one change per entry).
- Touching `scripts/pod_infer.py` → no unit tests exist; validate on the pod against the 58–77.5 s rally window (expect ~25 crossings with the current weights) and the 659–666 s dead window (the FP number still owed).
- Touching calibration → `test_calibrate.py` / `test_calib.py` and a fresh re-click on real footage (the 0.356 ft RMSE check is the reference).
- Any selection/budget change → the harness's selection table is the check; budget violation must fail loudly.

See [Rally Detection Concepts](../concepts/rally-detection.md) for the mechanisms under test and [Key Workflows](../workflows/pipeline.md) for the operator sequence these checks slot into.
