---
type: Testing Guide
title: Testing & Evaluation — harness, labels, benchmark windows, test suite
description: How pic-vision proves quality — the eval harness (temporal IoU, detection/selection metric tables), label files and set discipline, the IMG_7743 benchmark numbers and older per-window regression targets, the Gemini clip verifier, and the 78-test pytest suite conventions.
tags: [testing, evaluation, harness, metrics, labels]
resource: eval/harness.py
openwiki:
  roles: [testing]
  change_kinds: [detection-pipeline, metrics]
  source_paths: [eval/harness.py, src/verify.py]
  symbols: [match_intervals, verify_clip, verify_clips]
  test_paths: [tests/test_harness.py, tests/test_ball.py, tests/test_tracknet.py, tests/test_cut.py, tests/test_verify.py]
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

Two tiers of regression evidence now exist. **The primary benchmark is IMG_7743** — clean fixed-mount footage, repaired HEVC, calibrated (0.85 ft RMSE, hand-marked net tape), 33 hand labels in `eval/labels/IMG_7743.jsonl` (produced with `label_web.py`), scored at IoU≥0.3 (EXPERIMENTS 2026-08-16). Current standing numbers under the shipped config (`court_wedge` gate, `min_crossings=6`, k14 pickleball weights):

| Metric | PRD §5 target | Measured (2026-08-16) |
|---|---|---|
| Rally recall | ≥ 0.90 | **0.61 (20/33)** — pinned under every gate/threshold tried; the 13 misses are a detection failure (PIC-1), not gating |
| Precision | (FP ≤ 1.0 / 10 min) | **0.29** (≈7.3 FP/10 min — 69 segments, 20 matched) — misses target; was 0.10 with the flat X-gate |
| Boundary error (median) | ≤ 1.0 s | Not measured at this config; 1.05 s on IMG_7655 with k14 weights (different gate/clip) |
| Inference wall clock | ≤ 0.5× source | ~58 fps on the RTX 2000 Ada (≈2× realtime) |

The older per-window table below is from the **compromised** footage (zoom/pan; per-window hand-measured net lines) and is now secondary. YOLO columns are historical (path retired, ADR-046) but remain the regression evidence for the tracker.

| Window | Type | YOLO naive | YOLO + tracker | TrackNet (badminton wts) | Target |
|---|---|---|---|---|---|
| IMG_7652 58–77.5 s (net y=260) | RALLY | 36 crossings (pre-size-filter scans) | 16 crossings | **25 crossings** (5 with best YOLO params, ADR-046) | high ✅ |
| IMG_7652 620–638 s (net y=170) | RALLY | 12 | not re-run | — | high ✅ |
| IMG_7655 86–101 s (net y=210) | RALLY | 20 | not re-run | — | high ✅ |
| **IMG_7652 659–666 s (net y=160)** | **DEAD** | **22** | **0** | **not yet run** | ~0 |

The 659–666 s dead window is the **standing FP control**: the YOLO+tracker path passes it (0); **running the gated TrackNet path on it is still an owed number** (CHECKLIST.md). The IMG_7655 full-video A/B (2026-08-16) is where the pickleball k14 weights proved themselves over the badminton ones: strict-IoU recall 11/36 vs 5/36 @ IoU≥0.5, boundary error 1.05 s vs 1.34 s. **Cross-camera generalisation is untested**: IMG_7744 has a calibration but no labels; IMG_7655 has 36 labels but no calibration (calibrating it is the cheapest real test).

## Gemini clip verification (`src/verify.py`)

A second opinion on the heuristics: `verify_clip` sends each cut clip to **Gemini Flash** (`gemini-2.5-flash` by default) and asks for a strict-JSON verdict `{"is_rally", "confidence", "reason"}` — real rally play vs warmup/dead-time/reset. Crossing-count heuristics (`min_crossings`, `gap_sec`) can't tell a real rally from warmup or a mid-rally lull from a point break; the video-understanding model watches the clip directly, as a **check on those heuristics, not a replacement** for them. `verify_clips` batches a list; `python3 -m src.verify clip1.mp4 clip2.mp4` is the CLI. Requires `GOOGLE_API_KEY` in `.env` (see `.env.example`); raises on API or JSON-parse errors rather than guessing — a broken verifier fails loudly. Not wired into `make process`; run it over `clips/rally_*.mp4` after a cut when you want an independent FP read.

## Unit test suite (`tests/`, 78 tests, `make test`)

Built test-first throughout (git history: harness and segmenter landed with tests before the detectors they score). Conventions worth preserving:

- **Dependency-light:** torch/ultralytics/tensorflow are never imported at module top level (lazy in-function imports in `players.py`; TrackNet/TF lives only in `scripts/pod_infer.py`, which has no unit tests by design — it runs on the pod; the Gemini client in `src/verify.py` is monkeypatched in tests). The whole suite runs without a GPU, model weights, API keys, or video files.
- **Synthetic signals over fixtures:** tests construct tiny tracks/series/CSVs (`test_ball.py`'s crossing sequences, `test_tracknet.py`'s temp CSVs, `test_cut.py`'s monkeypatched glue) rather than storing video.
- **Behavior-named cases:** e.g. `test_match_one_prediction_cannot_claim_two_labels`, `test_rejects_teleport_to_far_ball`, `test_reacquires_after_long_gap`, `test_net_line_y_prefers_marked_net`, `test_detect_net_y_finds_horizontal_line`, `test_court_wedge_caps_the_ceiling_and_widens_below_it` — the test names document the ADR-backed rule.

Coverage map: `test_harness.py` (12 — IoU/matching/metrics), `test_ball.py` (15 — net line, size filter, crossings, clustering), `test_players.py` (5) / `test_events.py` (6) (frozen v0 front-end), `test_track.py` (5 — the single-ball tracker shared by both detection eras), `test_segment.py` (4), `test_calibrate.py` (3 — order-independent assignment, homography fit), `test_calib.py` (3 — Hough net detect, empty-video error, `court_x_range` spans corners + margin), `test_tracknet.py` (9 — CSV parsing, fps scaling, burst detection, sparse-crossing rejection, **adjacent-court teleport rejection, the court-gate-survives-`reset_after`-gap regression, and three `court_wedge` shape tests** — taper rejection, airspace kept above the court, ceiling cap — the multi-court cases encode the 2026-08-16 IMG_7744 bug), `test_cut.py` (2 — orchestrator glue: score forwarding, empty input), `test_render.py` (5 — ffmpeg command shape, concat, padding, manifest), `test_label.py` (4 — I/O + review/grade mode), `test_verify.py` (4 — JSON verdict parsing, non-JSON rejection, batch order, missing API key). Archived YOLO pipeline tests live in `archive/tests/` and are not collected.

## What to run when changing things

- Touching matching/metrics → `test_harness.py` + re-run `make eval` on a known `rallies.json`.
- Touching the crossing/cluster spine (`src/ball.py`), TrackNet parsing/gating (`src/tracknet.py`), the tracker (`src/track.py`), or orchestration (`src/cut.py`) → `test_ball.py` + `test_tracknet.py` + `test_track.py` + `test_cut.py`, then score against the IMG_7743 benchmark (33 labels) above; record the run in EXPERIMENTS.md (hypothesis first, one change per entry). The multi-court regressions in `test_tracknet.py` are the ones to keep green when changing the gate or tracker.
- Touching `src/verify.py` (prompt, model, parsing) → `test_verify.py`; spot-check one real clip against a known rally before trusting a verdict change.
- Touching `scripts/pod_infer.py` → no unit tests exist; validate on the GPU box against the 58–77.5 s rally window (expect ~25 crossings with the current weights) and the 659–666 s dead window (the FP number still owed). Its 98%-of-expected-frames abort guards against the silent-HEVC-decode trap — never bypass it.
- Touching calibration → `test_calibrate.py` / `test_calib.py` and a fresh re-click on real footage (the 0.85 ft RMSE IMG_7743 calibration is the reference; confirm `net_image_points` are present — `net_line_y` warns without them).
- Any selection/budget change → the harness's selection table is the check; budget violation must fail loudly.

See [Rally Detection Concepts](../concepts/rally-detection.md) for the mechanisms under test and [Key Workflows](../workflows/pipeline.md) for the operator sequence these checks slot into.
