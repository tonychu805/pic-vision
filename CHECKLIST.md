# Phase Checklist

Tracks build status and gate measurements against the PRD §7 / TECH_SPEC §13 milestones.
Updated as phases complete. Measurement runs go in `EXPERIMENTS.md`; decisions in `DECISIONS.md`.

**Legend:** ✅ done · ⚠️ partial / known gap · ❌ not built · — not applicable

---

## Phase 0 — Instrument

**Gate:** harness reports both §5 tables on a hand-written stub.

| Item | Status | Notes |
|---|---|---|
| Preflight script (`src/capture.py`) | ❌ | Described in TECH_SPEC §1.1; not written |
| RTSP recording validated | ✅ | 90–96% frame delivery; clean-stop documented (ADR-030/031) |
| `calibrate.py` — 12 court + 2 net clicks | ✅ | Order-independent (ADR-035); net marking added |
| `label.py` — rally interval labeler | ✅ | `--review` mode tested |
| Eval harness (`eval/harness.py`) | ✅ | IoU matching, detection + selection tables, 12 tests |
| Labels exist for at least one clip | ✅ | `IMG_7652.jsonl` (9 competitive), `IMG_7655.jsonl`, `austin_rally2.jsonl` |
| Eval sets assigned (A locked / B tuning / C low-light) | ❌ | Labels exist but roles not formally assigned; eval-set-A not locked |
| Harness runs on hand-written stub | ✅ | Proven in Phase 0 session |

**Gate status: PASSED** (harness works; eval-set-A not formally locked yet — do this before any tuning run)

---

## Phase 0.5 — Benchmark prior art

**Gate:** baseline recall/FP number exists from running an existing project against `eval-set-A`.

| Item | Status | Notes |
|---|---|---|
| vinod-polinati run against our labels | ❌ | Assessed qualitatively in TECH_SPEC §2 / EXPERIMENTS.md; never scored |
| Prior art scored with our harness | ❌ | — |

**Gate status: NOT DONE** — qualitative assessment only; no measured baseline.
This is now lower priority because: (a) we already read the source and know it has no accuracy numbers, and (b) the v1 ball path went directly to detection. Revisit if we need a comparison point.

---

## Phase 0.6 — Validate the approach

**Gate:** dead-time events (net crossing, court exit, all stationary) fire near-zero times during labelled rallies.

| Item | Status | Notes |
|---|---|---|
| Measure net-crossing event rate during labeled rallies | ❌ | Never done |
| Measure court-exit event rate during labeled rallies | ❌ | — |
| Measure all-stationary rate during labeled rallies | ❌ | — |
| Measure courtesy-return false rally rate | ❌ | — |

**Gate status: SKIPPED** — Real footage (2026-08-08) showed player-activity markers *inverted* on casual play (dead time more active than dink rallies). This failed the spirit of Phase 0.6's check. Response: pivot to v1 (ball net-crossings) as the primary signal (ADR-039). v0 player baseline frozen; v1 is the current challenger.

---

## Phase 1 — Core pipeline (v0 path: players → segmentation → selection → render)

**Gate:** watchable ≤10-min reel; recall and FP measured on `eval-set-A`; subjective gate once.

| Item | Status | Notes |
|---|---|---|
| `src/motion.py` — T0′ motion pre-filter | ❌ | Not built |
| `src/players.py` — player detection + court coords | ✅ | foot point → court coords, on-court filter |
| `src/events.py` — motion + kitchen signals | ✅ | `mean_motion`, `motion_series`, `n_at_kitchen` |
| Dead-time event list (§5.2.1: net crossing, court exit, ball held, all stationary, player shortfall) | ⚠️ | Only motion/kitchen built; net-crossing, court-exit, ball-held events not in `events.py` |
| `src/segment.py` — gap-tolerant segmenter | ✅ | Signal-agnostic; used by both v0 and v1 |
| `src/select.py` — ranker + budget selection | ❌ | Not built |
| `src/render.py` — H.264 cut module | ✅ | `cut_clips`, manifest; 2 tests |
| `cut.py` — end-to-end orchestrator | ❌ | Not built; must wire capture → detect → segment → select → render |
| End-to-end run → `rallies.json` | ❌ | v0 produced timestamps on compromised footage (plumbing check); no valid run |
| `highlights.mp4` produced | ❌ | — |
| Recall measured on `eval-set-A` | ❌ | — |
| FP/10min measured | ❌ | — |
| Boundary error measured | ❌ | — |
| Subjective gate (watch 3 sessions) | ❌ | — |

**Gate status: NOT DONE** — pipeline components exist but not wired; no measured numbers; no reel.

---

## Phase 1 — v1 path (ball net-crossings — current primary effort)

This runs in parallel with Phase 1 v0 (ADR-039). v1 is the current focus; v0 remains frozen as a baseline.

| Item | Status | Notes |
|---|---|---|
| `src/ball.py` — `net_line_y`, `crossing_times`, `cluster_crossings` | ✅ | Backend-agnostic; 8 tests |
| `src/track.py` — `track_ball` (teleport-rejecting spatial tracker) | ✅ | 4 tests |
| `src/tracknet.py` — parse predictions.csv → rally segments | ✅ | 4 tests; replaces YOLO pipeline (ADR-046) |
| `src/segment.py` — shared with v0 | ✅ | — |
| `src/render.py` — shared with v0 | ✅ | — |
| `src/cut.py` — end-to-end orchestrator (TrackNet path) | ✅ | `cut_rallies_from_predictions` + CLI; 2 tests |
| `scripts/pod_infer.py` — RunPod GPU inference script | ✅ | Produces predictions.csv; argparse CLI |
| `scripts/process_footage.py` — local: CSV + video → clips | ✅ | `make process VIDEO=... CSV=... NET_Y=... OUT=...` |
| TrackNet FP rate on dead-time window | ❌ | 659–666s window not yet run through TrackNet |
| Pickleball fine-tuned weights loaded | ❌ | TF 2.11/Ada compatibility check pending on workstation |
| `max_ball_px` calibrated to actual ball pixel size | ❌ | Requires clean fixed footage |
| Recall measured on `eval-set-A` | ❌ | Requires clean footage |
| FP/10min measured | ❌ | — |
| Boundary error measured | ❌ | — |

**Benchmark results (compromised footage, not eval):**

| Window | Type | YOLO | TrackNet (badminton wts) | Target |
|---|---|---|---|---|
| IMG_7652 58–77.5s (net y=260) | RALLY | 5 crossings | 25 crossings | high ✅ |
| IMG_7655 full video (net y=210 fixed) | 36 rallies | — | 5/36 usable clips (14% recall) | — |
| IMG_7652 659–666s (net y=160) | DEAD | 0 (tracked) ✅ | not yet run | ~0 |

**Gate status: NOT DONE** — e2e pipeline wired and runnable; no harness numbers. Blocked on clean footage for meaningful metrics.

---

## Phase 1.5 — Boundary refinement

**Gate:** boundary error ≤ 1.0 s on `eval-set-A`.

| Item | Status | Notes |
|---|---|---|
| Dense re-detection in ±3 s boundary windows | ❌ | Not built |
| Audio onset gating (§5.1b) | ❌ | Not built |

**Gate status: NOT STARTED**

---

## Phase 2 — Ball presence (now partially absorbed into v1)

**Gate:** FP improves, recall doesn't regress vs Phase 1.

| Item | Status | Notes |
|---|---|---|
| yolov8x sports-ball detection at imgsz=1280 | ✅ | In `ball.py` |
| Size filter (reject heads/bodies) | ✅ | `ball_box_ok` |
| Shoe filter (reject detections in bottom 45% of player box) | ❌ | Described in TECH_SPEC §5.3.1; not implemented |
| Physics filter (reject >300 px/frame jumps) | ⚠️ | `track_ball` max_jump rejects teleports but is not explicitly 300 px |
| Ball side-alternation feature | ⚠️ | `crossing_times` counts net-side flips, which is equivalent |
| Courtesy-return suppression (≥2 crossings required) | ⚠️ | `cluster_crossings(min_crossings=2)` does this; threshold not yet tuned |
| Measured FP improvement vs v0 | ❌ | No clean-footage run |

**Gate status: PARTIAL** — core detection and tracker built; shoe filter missing; no measured comparison.

---

## Phase 2.5 — Audio (conditional)

**Gate:** audio usability gate passes AND boundary error improves.

| Item | Status | Notes |
|---|---|---|
| Audio usability gate (onset density during dead time) | ❌ | — |
| Spectral flux onset detector | ❌ | — |
| Cross-modal gating on court-ROI motion | ❌ | — |

**Gate status: NOT STARTED** — not a blocker; only entered if usability gate passes.

---

## Phase 3 — Ball trajectory (gated)

**Gate:** only entered if Phases 1.5 and 2.5 both miss boundary error target.

**Gate status: NOT ENTERED**

---

## Phase 3.5 — Tune ranker

**Gate:** 2 of 3 sessions pass subjective gate; utilization ≥ 0.85; ≥ 12 rallies.

**Gate status: NOT STARTED** — `select.py` not built; no sessions to watch.

---

## Phase 4 — Tidy

**Gate:** re-runnable a month later without re-reading the code (`cut.py session.mp4 --budget 600`).

| Item | Status | Notes |
|---|---|---|
| `cut.py` single-command entry point | ❌ | — |
| Resumability (stage cache, NFR3) | ❌ | Cache dir exists but no cache-keyed resume logic |
| Structured logging to `run.log` (NFR9) | ❌ | — |
| `README.md` — how to run | ⚠️ | Exists (not reviewed this session) |

**Gate status: NOT STARTED**

---

## The one real gate

Everything above is blocked on this:

> **Capture one clean clip** — rigid mount, no zoom, no pan, whole court in frame, well-lit, calibrated with the 12+2 flow.

Until then: no meaningful recall/FP/boundary numbers are possible, `max_ball_px` can't be set, and the subjective gate can't run. The pipeline is built. The footage is the blocker.

---

## PRD §5 metric targets vs current measured values

| Metric | Target | Measured | Source |
|---|---|---|---|
| Rally recall | ≥ 0.90 | — | No clean run |
| False positives / 10 min | ≤ 1.0 | — | No clean run |
| Boundary error (median) | ≤ 1.0 s | — | No clean run |
| Wall clock | ≤ 0.5× source | — | Not measured |
| Budget compliance | ≤ 600 s | — | No reel yet |
| Budget utilization | ≥ 0.85 | — | No reel yet |
| Rally count in reel | ≥ 12 | — | No reel yet |
| Subjective gate | 2 of 3 sessions | — | No reel yet |
