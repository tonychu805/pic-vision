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

**Frozen, not the current effort** (ADR-039/ADR-047 — ball-first TrackNet, below, is primary). Components: `src/players.py` and `src/events.py` (✅, motion + kitchen signals) exist; `src/motion.py` and `src/select.py` were never built; there is **no v0-specific `cut.py`** — the only `cut.py` in the repo is the v1/TrackNet orchestrator in the next section, so don't read "cut.py not built" here as contradicting that. v0 was never run end-to-end on clean footage and has no measured numbers. Revisit per ADR-047's conditions (movement-analytics product, boundary-fusion, or a fallback if ball detection stays unreliable) rather than by default.

**Gate status: NOT STARTED** — frozen before reaching it, not failing it.

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
| `src/calib.py` — `court_wedge` (perspective-aware court gate) | ✅ | Replaces flat `court_x_range`; adds the height cap (EXPERIMENTS.md 2026-08-16) |
| `label_web.py` — browser-based two-pass labeler | ✅ | Mark (`s`/`e`) then grade (`1`/`2`/`3`) with hindsight; used to produce the 33 IMG_7743 labels |
| TrackNet FP rate on dead-time window | ❌ | 659–666s window (compromised footage) not run through TrackNet; superseded by the full clean-footage precision number below |
| Pickleball fine-tuned weights loaded | ✅ | Loaded 2026-08-16 via TF 2.15 (Keras-2 load path, `compile=False`); beats badminton weights on strict-IoU recall (31% vs 14%) and boundary error (1.05s vs 1.34s) — EXPERIMENTS.md 2026-08-16, now the default |
| `max_ball_px` calibrated to actual ball pixel size | ❌ | Not set for TrackNet path (TrackNet has no equivalent filter); size/confidence filtering is `PIC-2`, in progress |
| **33-label IMG_7743 benchmark** (blind ground truth vs blind detector) | ✅ | First trustworthy clean-footage eval; see below |
| Recall measured on `eval-set-A` | ✅ | 20/33 (61%) @ IoU≥0.3, `min_crossings=6`, `court_wedge` gate (EXPERIMENTS.md 2026-08-16) — **below the ≥0.90 target** |
| FP/10min measured | ⚠️ | Not reported as FP/10min directly; derivable from the same run (69 segments − 20 matched = 49 FP over 67.3 min ≈ **7.3/10min**) — well above the ≤1.0 target |
| Boundary error measured | ❌ | Not measured on IMG_7743 at `min_crossings=6`. A different run (IMG_7655, different gate) measured 1.05s median — see `EXPERIMENTS.md` 2026-08-16 A/B |

**Benchmark results (compromised footage, historical — superseded by the clean-footage numbers below):**

| Window | Type | YOLO | TrackNet (badminton wts) | Target |
|---|---|---|---|---|
| IMG_7652 58–77.5s (net y=260) | RALLY | 5 crossings | 25 crossings | high ✅ |
| IMG_7655 full video (net y=210 fixed) | 36 rallies | — | 5/36 usable clips (14% recall) | — |
| IMG_7652 659–666s (net y=160) | DEAD | 0 (tracked) ✅ | not yet run | ~0 |

**Benchmark results — four cameras, shipped config (`court_wedge`, `gap_sec=3.0`, `min_crossings=6`), scored at IoU≥0.5 (`TECH_SPEC.md` §11):**

| Video | format | precision | recall | FPs reviewed at playback? |
|---|---|---|---|---|
| brickwall | doubles, tournament | **0.64** | 0.80 (28/35) | ✅ yes |
| pb_draft_cup | **singles** | **0.59** | 0.72 (13/18) | ✅ yes |
| IMG_7743 (combined pre/post-bump) | casual doubles | **0.44** | 0.75 (40/53) | ✅ yes (2026-08-19) |
| IMG_7744 | casual doubles | **0.54** | 0.65 (13/20) | ✅ yes (2026-08-19) |

**All four cameras now reviewed — the label artefact is confirmed everywhere it's been checked, not withdrawn on any of them.** Reviewing false positives at playback speed and correcting the labels moved every video the same direction: pb_draft_cup 0.27 → 0.59, brickwall 0.59 → 0.64, IMG_7743 0.29 → 0.44, IMG_7744 0.25 → 0.54 — with no change to predictions, calibration, config, or scoring code in any case (ADR-050; IMG_7743/7744 in `EXPERIMENTS.md` 2026-08-19). The earlier "precision pinned at 0.25–0.29 across cameras" reading is fully withdrawn; it was measuring label completeness, not the detector. **What's still open:** IMG_7743/7744's anatomy is now done (`EXPERIMENTS.md`, 2026-08-19 later entry, PIC-37) — 26% fragment, 48% real dead-time crossing, 21% noise, 5% ambiguous, combined. The dominant remaining mechanism is real crossings during dead time (courtesy return / between-point practice, PIC-31), **not** phantom crossings as previously assumed — read from per-frame trajectory plots. The two longest/highest-stakes segments (24.4s and 17.9s, both looked like clean real rallies in the plot) were playback-confirmed 2026-08-19: both warm-up with a lot of exchanges, not missed rallies — supports trusting the plot-read method on the rest of the batch. `pb_draft_cup` has not had this treatment yet (PIC-36 still open).

**Recall split by grade** — the blended figure hides the metric that matters, since missing an ordinary rally is cheap and missing a highlight is the product failing:

| Video | highlight recall | ordinary recall | blended |
|---|---|---|---|
| brickwall | **0.92** (12/13) | 0.73 (16/22) | 0.80 |
| pb_draft_cup | 1.00 (2/2, n too small) | 0.69 (11/16) | 0.72 |

**Gate status: PARTIAL** — e2e pipeline wired, runnable, and now measured on four cameras. brickwall's **highlight** recall (0.92) meets the PRD's ≥0.90 detection target; blended recall and precision do not. Three distinct failure modes are separated and none is fixed: rally fragmentation by a too-tight `gap_sec` on long doubles points, phantom crossings from a tossed ball, and courtesy returns (PIC-31). Neither clean footage nor the recall ceiling is the blocker any more — measurement hygiene was, and the remaining work is code.

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
| Courtesy-return suppression | ✅ | `cluster_crossings`'s own default is still 2, but the shipped pipeline default is **6**, tuned by direct measurement on the 33-label IMG_7743 benchmark (ADR-048, `EXPERIMENTS.md` 2026-08-16) — precision 0.29 vs 0.12 at the same 61% recall |
| Measured FP improvement vs v0 | ❌ | v1 now has a clean-footage precision/recall number (above); v0 has never been run on clean footage, so there is still no fair v0-vs-v1 comparison |

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

**Cleared 2026-08-16.** IMG_7743 is a clean fixed-mount recording, repaired, calibrated (0.85ft RMSE), hand-labelled (33 rallies), and scored — the first trustworthy numbers the project has produced. The gate this section used to name is done.

**Diagnosed 2026-08-17 (`PIC-1`, `EXPERIMENTS.md`, ADR-049) — it was not a detection failure.** 11 of the 13 missed rallies are every single rally after t≈2859s, when the camera was physically bumped mid-recording; TrackNet kept finding the ball fine (~50% visibility, normal), but `net_y=552` silently went stale for the rest of the session. Patching `net_y` for the tail alone recovers recall 0.61→0.85 on the full 33 labels. The new binding constraint is a **capture-robustness** one, not a model/gating one:

> **A single mid-session camera bump cost 11 of 33 rallies, and no threshold tuning could have recovered it.** The fix is to detect calibration drift (e.g. periodic net-line position check) and split/re-calibrate around it — not yet built. The other 2 misses (label#3/#19) are the separate, already-known `gap_sec` boundary tradeoff.

Precision (0.29) is also well short of a usable product, but it responded strongly to gating/threshold work (0.10 → 0.29) — it is not obviously stuck the way recall was before this diagnosis.

---

## PRD §5 metric targets vs current measured values

Measured on the 33-label IMG_7743 benchmark, IoU≥0.3, shipped config (`court_wedge` gate, `min_crossings=6`) — `EXPERIMENTS.md` 2026-08-16.

| Metric | Target | Measured | Source |
|---|---|---|---|
| Rally recall | ≥ 0.90 | **0.61** (20/33) — misses target | `EXPERIMENTS.md` 2026-08-16 |
| False positives / 10 min | ≤ 1.0 | **≈7.3** (49 FP / 67.3 min) — misses target | Derived from the same run (69 segments − 20 matched) |
| Boundary error (median) | ≤ 1.0 s | Not measured at this config; 1.05s under a different gate/clip (IMG_7655 A/B) | `EXPERIMENTS.md` 2026-08-16 |
| Wall clock | ≤ 0.5× source | ~58 fps local GPU inference (≈2× realtime) | `EXPERIMENTS.md` 2026-08-16 |
| Budget compliance | ≤ 600 s | — | No reel yet (`select.py` not built) |
| Budget utilization | ≥ 0.85 | — | No reel yet |
| Rally count in reel | ≥ 12 | — | No reel yet |
| Subjective gate | 2 of 3 sessions | — | No reel yet |
