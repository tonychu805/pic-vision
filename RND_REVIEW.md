# pic-vision — Detection & Highlight R&D Review

**Scope:** every scored/logged experiment Aug 6 → Oct 24 2026 (99 entries in `EXPERIMENTS.md`), plus this session's serve work.
**Purpose:** what we now *know*, what's *shippable*, what's *close*, and what *needs development* — so effort goes where it pays.
**Author:** synthesis pass, 2026-10-24. Uncommitted working doc.

---

## Legend

| Tag | Meaning |
|-----|---------|
| ✅ **SHIPPED** | Running in production today |
| 🟢 **VALIDATED** | Proven on real data, not yet wired to production |
| 🟡 **PARTIAL** | Works but limited (lossy / narrow / rough) |
| 🔶 **OPEN** | Inconclusive or never measured — not settled |
| ❌ **REJECTED** | Tested properly, does not work — bank the knowledge |
| 🔵 **KNOWLEDGE** | A durable finding/correction, not a feature |

---

## 1. Executive summary

Two months produced **a lot of knowledge and a few ships.** The detector itself is solid and shipped; most of the effort went into *signals on top of it* (rally boundaries, serve detection, highlight types, ball trajectory) — and the honest result is that **most hand-crafted discriminator signals fail, usually because they don't survive a second camera.** The single most valuable finding isn't a feature at all: a long-standing "precision ceiling" turned out to be a **labeling artifact**, not a detector limit.

**Top 5 takeaways**

1. 🔵 The cross-camera precision "ceiling" (~0.27) was a **label artifact** — honest relabeling raised it to ~0.59. Labeling is the hidden variable; humans agree on only ~⅓ of what *is* a rally.
2. 🔵 The recurring failure mode is **"great on one video, fails on the next"** (stillness, swing-magnitude, ball-side, DALI). Cross-venue validation is the one discipline that reliably pays.
3. ✅ The **detection pipeline is solid & shipped**: k14 TrackNet → court_wedge → track_ball → crossings → cluster → ADR-063 ranking → 3 reels.
4. 🟢 **Serve detection**: near-side works (~97–100%); far-side gap was **pose coverage of the serve moment, not the camera** (recovered 2→13). Discrimination & recall still open.
5. ✅/❌ Infra mostly settled: 720p≈native, 30fps required, CFR convert needed; frame-skip & encode-bump rejected; **DALI/TensorRT still genuinely open.**

**Ship ladder at a glance**

```
 ✅ SHIP NOW ......... frozen-frame gate ; adaptive_gap → default
 🟡 CLOSE ............ merge footage_rules ; paddle-hit ranking signal (lossy)
 🔶 NEEDS DEV ........ serve gate (needs pose model + latency + RECALL) ;
                        measure recall ; raise field precision ; DALI/TensorRT
 ❌ DON'T ............ TrackNetV3, Gemini verify, ball-side, serve cues,
                        ball-tempo ranking, 2D trace feature, frame-skip, ...
```

---

## 2. Production pipeline (today) + where proven findings slot

```
                 PRODUCTION  (cloud_pipeline/pod_driver.py)
 ══════════════════════════════════════════════════════════════════════════════

  VENUE (thin agent)            CLOUD                    RunPod GPU pod
  ┌──────────────┐  raw .mkv  ┌────────────┐  trigger  ┌──────────────────────┐
  │ record -c copy│ ────────▶ │ Cloudflare  │ ───────▶ │  pod_driver.run()     │
  │ upload → R2   │ (10-min)   │ Workflow    │          └──────────┬───────────┘
  └──────────────┘            └────────────┘                     │
  ┌───────────────────────────────────────────────────────────────────────────┐
  │ 1. CFR re-encode → proxy      ✅  HEVC/-c copy fix; moved ~40% of detections│
  │ 2. drift check (find_bumps)   ✅  rejects bumped-camera footage             │
  │ 3. video_quality (fps gate)   ✅  BLOCK_BELOW_FPS (ADR-131)                 │
  │        └── GAP ◀── frozen-frame gate goes HERE  [ship-now #1]              │
  │ 4. TrackNet inference         ✅  k14, full-frame, streaming                │
  │ 5. detect_candidates          ✅  court_wedge → track_ball → crossings →    │
  │        gap_sec=3 min_cross=6       cluster    (adaptive_gap could slot here)│
  │ 6. build_reel / burst / top   ✅  rank by WEIGHTS (len/pace/hard/swing)     │
  │        └── serve gate would go HERE  [needs dev]                           │
  │ 7. upload reels → R2          ✅                                            │
  └───────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                     Console / share.picvisionai.com
```

---

## 2b. Architecture — production line vs under-test line (step by step)

```
 LEGEND   ✅ shipped (live)   🧪 under test NOW   ⬆ proven, ship-now
          🔧 needs dev        ⛔ tested, NOT this iteration
```

### SECTION A — PRODUCTION LINE (what runs today)

```
 ┌─ CAPTURE (venue, thin agent — ADR-084) ───────────────────────────────────────┐
 │  [A1] record RTSP  →  -c copy (no transcode)                           ✅      │
 │  [A2] upload raw 10-min chunks → R2                                    ✅      │
 └───────────────────────────────────────────────────────────────────────────────┘
                                   │
 ┌─ ORCHESTRATE (cloud) ─────────────────────────────────────────────────────────┐
 │  [A3] Cloudflare Workflow picks up chunk → spins RunPod GPU pod        ✅      │
 └───────────────────────────────────────────────────────────────────────────────┘
                                   │
 ┌─ ON THE POD  (cloud_pipeline/pod_driver.py) ──────────────────────────────────┐
 │  [A4] CFR re-encode → 720p proxy        (HEVC/-c copy fix; +40% det.)  ✅      │
 │  [A5] drift check (find_bumps)          (reject bumped camera)         ✅      │
 │  [A6] video_quality gate (BLOCK_BELOW_FPS, packet-rate)                ✅      │
 │  [A7] TrackNet inference (k14, streaming)                              ✅      │
 │        └── court_mask ON (masks non-court BEFORE inference)            ✅ 🧪   │
 │  [A8] detect_candidates:                                               ✅      │
 │        court_wedge gate → track_ball → crossing_times →                        │
 │        cluster_crossings  (gap_sec=3.0, min_crossings=6)                        │
 │  [A9] rank + cut 3 reels:  build_reel / burst / top_rallies           ✅      │
 │        rank = WEIGHTS(length, pace, hard, swing)   (ADR-063)                    │
 │  [A10] upload reels → R2 (private bucket)                              ✅      │
 └───────────────────────────────────────────────────────────────────────────────┘
                                   │
 ┌─ DELIVER ─────────────────────────────────────────────────────────────────────┐
 │  [A11] Console / share.picvisionai.com  (pull-based)                  ✅      │
 └───────────────────────────────────────────────────────────────────────────────┘

  NOTE: no serve gate, no highlight-type badges, no frozen-frame gate today.
```

### SECTION B — SUPPOSED / UNDER-TEST LINE (same spine, deltas marked)

```
 ┌─ CAPTURE ─────────────────────────────────────────────────────────────────────┐
 │  [B1] record -c copy  →  [B2] upload → R2              (unchanged)     ✅      │
 └───────────────────────────────────────────────────────────────────────────────┘
                                   │
 ┌─ ORCHESTRATE ─────────────────────────────────────────────────────────────────┐
 │  [B3] Cloudflare Workflow → RunPod pod                 (unchanged)    ✅      │
 │  [B3.5] + footage_rules.usable()  skip Tapo/drill sessions (ADR-158)  ⬆ 🔧   │
 │         (committed, not merged/wired — low-risk gate at job entry)             │
 └───────────────────────────────────────────────────────────────────────────────┘
                                   │
 ┌─ PRE-FLIGHT GATES ────────────────────────────────────────────────────────────┐
 │  [B4] CFR re-encode → proxy                            (unchanged)    ✅      │
 │  [B5] drift check                                      (unchanged)    ✅      │
 │  [B6] video_quality fps gate                           (unchanged)    ✅      │
 │  [B6.5] + FROZEN-FRAME gate (mpdecimate, content)                     ⬆      │
 │         catches Tapo-class footage the fps gate can't see — PROVEN              │
 └───────────────────────────────────────────────────────────────────────────────┘
                                   │
 ┌─ DETECT ──────────────────────────────────────────────────────────────────────┐
 │  [B7] TrackNet inference (k14)                                        ✅      │
 │        └── court_mask ON  — A/B: CAMERA-DEPENDENT (NOT a clean keep)  🧪      │
 │            IMG_7893(camA) mask HELPS 0.46 vs 0.15; pb_draft_cup(camB)             │
 │            mask HURTS 0.44 vs 0.56; IMG_7743 also "mask worse" (08-16);           │
 │            PGC changes seg count (no labels → direction unknown).                 │
 │            Applied blanket to every venue → helping some, hurting others.         │
 │  [B8] detect_candidates: court_wedge → track_ball → crossings →       ✅      │
 │        cluster_crossings                                                        │
 │        └── adaptive_gap?  TESTED on field footage → NO benefit        ⛔      │
 │            (keep fixed gap_sec=3; adaptive stays opt-in long-rally only)        │
 └───────────────────────────────────────────────────────────────────────────────┘
                                   │
 ┌─ QUALIFY  (NEW stage — the real next feature) ────────────────────────────────┐
 │  [B9] SERVE GATE                                                      🔧      │
 │        needs: 2nd GPU model (pose) in pipeline + serve-window pose              │
 │        recall measured → ~0% gate cost on the reel (SAFE)                       │
 │        open: RunPod/Cloudflare latency of a 2nd model; precision value          │
 │        → keeps real points, drops warm-up/junk segments                         │
 └───────────────────────────────────────────────────────────────────────────────┘
                                   │
 ┌─ RANK / TAG ──────────────────────────────────────────────────────────────────┐
 │  [B10] rank = WEIGHTS(length,pace,hard,swing)          (unchanged)    ✅      │
 │        └── ball-tempo features?  TESTED → no gain                     ⛔      │
 │        └── paddle-hit count signal (ADR-157)?  ~half precise          🔧      │
 │  [B10.5] + highlight-type BADGES (Marathon/Firefight/Kitchen War)     🔧      │
 │          designed; types are per-session; validate by detection precision      │
 └───────────────────────────────────────────────────────────────────────────────┘
                                   │
 ┌─ ASSEMBLE / DELIVER ──────────────────────────────────────────────────────────┐
 │  [B11] build 3 reels → upload R2 → Console/share       (unchanged)    ✅      │
 └───────────────────────────────────────────────────────────────────────────────┘
```

### Deltas at a glance

| Step | Change | Status | In this iteration? |
|---|---|---|---|
| B3.5 | footage_rules (skip Tapo/drill) | committed, unwired | yes (small) |
| B6.5 | frozen-frame gate | ⬆ proven | **YES — ship** |
| B7 | court_mask on/off | 🧪 CAMERA-DEPENDENT | per-camera study (helps camA, HURTS camB) |
| B8 | adaptive_gap as default | ⛔ no field benefit | no (stays opt-in) |
| B9 | serve gate (pose model) | 🔧 needs latency | next iteration |
| B10 | ball-tempo ranking | ⛔ no gain | no |
| B10 | paddle-hit ranking | 🔧 lossy | maybe (validate) |
| B10.5 | highlight-type badges | 🔧 designed | later |

**Reading it:** the *spine* is unchanged and solid (A1–A11 = B1, B4–B6, B10, B11). Near-term deltas are two **pre-flight gates** (frozen-frame ⬆, footage_rules 🔧) and the **court_mask decision** (🧪 — the A/B deciding whether B7 even keeps a step production currently runs). The one genuinely *new stage* is **QUALIFY / serve gate (B9)** — recall-safe, blocked on the pose-model latency question. Everything ⛔ is a path the testing *closed* this cycle.

---

## 3. Metrics dashboard (the numbers that matter)

| Metric | Value | Source / note |
|---|---|---|
| Ball detector | **k14 TrackNet** | beat YOLO (25 vs 5 crossings), beat badminton weights |
| Throughput | ~32 fps (RunPod) / ~38–58 (local) | `.predict()` overhead was the old bottleneck |
| Detection precision (honest labels, clean) | **~0.59–0.75** | after the label-artifact correction |
| Detection precision (PGC **field** footage) | **~0.55** | field is harder than the IMG_7743 eval set |
| Recall (good calib) | up to **0.91** | IMG_7743 split-calibration; camera-bump sensitive |
| 15 fps vs 30 fps | recall **0.46 → 0.23** | halved; no threshold recovers it |
| 720p vs native | **≈ equal** | ship 720p proxy |
| Shipped cluster params | `gap_sec=3`, `min_crossings=6` | re-derived, converged on shipped |
| CFR convert impact | **~40% of ball detections** | lossy encode moves them; convert is load-bearing |
| **Near-side serve** precision | **97–100%** | PGC proj 17, brickwall proj 18 |
| **Far-side serve** precision | 47% (depth floor) → **62%** (serve-window pose) | brickwall proj 18 |
| Far-serve recall (coverage fix) | **2 → 13** of 44 rallies | posing the serve moment |
| Serve side-assignment | **~75–81%** (pose) | ball fix fails cross-venue |
| Serve **recall** | **UNMEASURED** | blocks the serve gate |
| Human labeling agreement (is-a-rally) | **~⅓** | PIC-6 — the real noise floor |
| Tapo frozen frames | **~32%** | content, not packet-rate; fps gate misses it |

---

## 4. Theme-by-theme deep dive

### Theme A — Ball detector choice ✅ SETTLED

| Tested | Result | Status |
|---|---|---|
| YOLO nano vs x | x better, still weak | ❌ superseded |
| TrackNet-Pickleball **k14** | 25 vs 5 crossings vs YOLO; beat badminton weights | ✅ **shipped** |
| TrackNetV3 (+InpaintNet) | **fabricates** trajectory on low-detectability footage; worse on the metric that matters, on 2 videos, survived adversarial review | ❌ rejected |
| PikleYOLO / others | surveyed only | — |

### Theme B — Detection pipeline (gate / tracker) ✅ SHIPPED & SOLID

| Tested | Result | Status |
|---|---|---|
| `track_ball` into crossing pipeline | dead-time crossings → 0, rally preserved | ✅ shipped |
| `court_wedge` trapezoid gate | works; perspective-aware; `margin_px=160` holds | ✅ shipped |
| Masking **before** inference | does **not** help | ❌ rejected |
| Blob size / confidence FP filter (PIC-2) | does **not** separate real balls from clutter | ❌ rejected |
| Re-acquisition: predicted-position vs radius | predicted-position wins for bridging dropouts | ✅ shipped |
| Auto net-line (Hough on temporal median) | works for baseline angles; `detect_net_y` breaks on side-on | 🟡 known bug |

### Theme C — Rally clustering params ✅ SHIPPED (+1 validated)

| Tested | Result | Status |
|---|---|---|
| `min_crossings=6`, `gap_sec=3` | re-derived independently, converged on shipped | ✅ shipped |
| **adaptive_gap (PIC-33)** | **beat the fixed constant on every video tested** | 🟢 **validated, not shipped** (ship candidate) |
| Flat `gap_sec=4` bump | wins long-rally footage, loses short — do NOT ship | ❌ rejected |

### Theme D — The precision-ceiling saga 🔵 BIGGEST KNOWLEDGE WIN

```
  "cross-camera precision stuck ~0.27"  ──relabel──▶  0.59   (pb_draft_cup)
  all 4 videos honestly relabeled  ▶  "real-vs-junk" largely dissolves
  PIC-6: humans agree on only ~1/3 of what IS a rally  ← the real noise floor
```
**Lesson:** precision numbers below the labeling noise floor are not trustworthy. The project's own stills-vs-playback rule comes from here (a stills verdict was wrong once).

### Theme E — Rally-start / "who serves" / dead-time signals ❌ mostly REJECTED

| Signal | Result | Status |
|---|---|---|
| Pre-serve **stillness** dip | real (~88% precede real starts) but **doesn't mark the boundary**, **doesn't generalize** to IMG_7743 | 🟡 leading-indicator only |
| Court-depth-at-serve (baseline vs kitchen) | corroborating "who serves" cue | 🔵 not built on |
| **Duration** threshold | real & usable on honest labels, but **redundant** with min_crossings | 🟡 redundant |
| Crossing **rate** threshold | does not separate | ❌ rejected |
| Ball **velocity spikes** | duration confound (named trap) | ❌ rejected |

### Theme F — Paddle / pose detection 🟡 works, hit-detection rough

| Tested | Result | Status |
|---|---|---|
| YOLO-World paddle (zero-shot) | great single-frame, **fails on video** | ❌ |
| Grounding DINO paddle | recovers where YOLO-World fails; same court_wedge ceiling | 🟡 |
| YOLO-pose off-the-shelf | works on real footage untrained | 🟢 (used for serve pose) |
| **Paddle-hit finder (ADR-157)** | arm-swing + ball gate **works — ~half hits, ~half precise** | 🟡 usable-but-rough |

### Theme G — 2D map / ball trajectory ❌ NOT a deliverable

```
  naive floor projection:  only 34% land on court, median depth 45ft on 44ft court
  camera pose: recoverable from calibration (net posts reconstruct to 3.0ft ✓)
  long unoccluded arcs: fit well  |  far-end depth: NEAR-DEGENERATE
  occlusion / net contact: confident WRONG geometry  ← the interesting moments
```
Shelved as a feature (operator decision 2026-10-11). Ball-derived *signals* (bounce, net, speed) still open. 9:16 ball-following auto-crop also prototyped.

### Theme H — LLM verification ❌ REJECTED / deferred

| Tested | Result | Status |
|---|---|---|
| Gemini rally verifier | **59%/52% vs pipeline 73%/67%**, timestamps drift | ❌ rejected |
| Jev (TypeSafe) rally guardrail | catches ball-machine reliably; **fails per-rally bar** (6/75 real flagged) | 🟡 coarse-only; blocked on sending footage out |

### Theme I — Ranking / reel selection ✅ SHIPPED & VALIDATED

| Tested | Result | Status |
|---|---|---|
| ADR-063 ranking (len/pace/hard/swing) | validated vs real quality grades, all 4 videos | ✅ shipped |
| Absolute 0–100 score + top-N | constants re-measured on PGC | ✅ shipped |
| Ball-tempo features (pace/kitchen/escalation/finish) | **no gain** beyond shipped score (underpowered, wrong target) | ❌ / 🔶 inconclusive |

### Theme J — Serve detection 🟢 near works, far recoverable, open parts remain

| Piece | Result | Status |
|---|---|---|
| Near-side detection | ~97–100% real serves | 🟢 validated |
| Far-side detection | gap = **pose coverage of serve moment, not camera**; recovered 2→13 | 🟢 validated (1 video) |
| Far ball detectability | crops recover **7/7** vs full-frame 4/7 | 🟢 |
| Depth floor (geometry) | precision **19→47%** | 🟢 (in proposer) |
| Crossing-anchored timing | serve-time **3.7s→0.2s** | 🟢 (in proposer) |
| Serve-vs-deep-shot discrimination | **every cue rejected** (held-ball, motion, quiet-gap, ball-into-play) | ❌ |
| Side-assignment | ~80% pose; **ball fix fails cross-venue** (100% bw / 53% PGC) | ❌ ball fix / 🟡 pose |
| Serve **recall** | never measured | 🔶 **blocks the gate** |

### Theme K — Infra / speed / cost / cloud ✅ mostly settled, 2 open

| Tested | Result | Status |
|---|---|---|
| 720p proxy vs native | ≈ equal | ✅ ship 720p |
| 30 vs 15 fps | recall halves | ✅ require 30 |
| CFR convert vs repackage | convert needed (moves ~40% detections) | ✅ shipped |
| `.predict()` throughput | was the bottleneck; direct tf.function call | ✅ fixed |
| Chunk-boundary rally loss | measured under 10-min-chunk arch | 🔵 known cost |
| Frame-skip for speed | collapses recall (0.46→0.00 @decimate2) | ❌ rejected |
| Encode-quality bump | visually marginal, 2.3× cost | ❌ rejected |
| **NVIDIA DALI** | numbers came from **broken scripts** (missing mask) — never cleanly tested | 🔶 **OPEN** |
| **TensorRT** | tooling-blocked (3 walls), never measured | 🔶 **OPEN** |

---

## 5. Ship ladder (detailed)

### ✅ Ship now
| # | Item | Why | Effort | Risk |
|---|---|---|---|---|
| 1 | **Frozen-frame gate** | Tapo drops ~⅓ frames as *duplicates*; fps gate (packet-rate) can't see it. Stops billed GPU runs + broken reels. | small | low |
| 2 | **adaptive_gap → default/flag** | Beat fixed `gap_sec` on **every** video tested; already built. | small | low (4-video validation, not whole corpus) |

### 🟡 Close
| # | Item | Why | Effort |
|---|---|---|---|
| 3 | Merge + enforce **footage_rules (ADR-158)** onto main + eval builders | Stops Tapo/drill footage silently poisoning results | small |
| 4 | **Paddle-hit** count into ranking (ADR-157) | A real signal — but ~half precise, so lossy; validate first | medium |

### 🔶 Needs development
| # | Item | Blocker |
|---|---|---|
| 5 | **Serve gate** (the real feature) | 2nd GPU model (pose) in pipeline + **untested RunPod/CF latency** + recall unmeasured |
| 6 | **Measure serve/rally recall** | Never done; gates #5 responsibly |
| 7 | Raise **field-footage precision (~55%)** | No lever found in 2 months |
| 8 | **DALI / TensorRT** re-test | Open, not negative; DALI needs the correct masked recipe |

### ❌ Don't (banked dead ends)
TrackNetV3 · Gemini verify · ball-based side-assignment · serve-discrimination cues · ball-tempo ranking · 2D ball-trace feature · frame-skip · encode bump · masking-before-inference · blob-size/confidence FP filter · stillness-as-boundary · flat gap_sec=4

---

## 6. Cross-cutting lessons

1. **Labeling is the hidden variable.** The biggest "detector" win was discovering a precision ceiling was a *label* artifact; humans agree on only ~⅓ of rallies. → Trust coarse results; distrust fine P/R deltas; judge from playback not stills.
2. **"Great on one video, fails on the next."** Stillness, swing-magnitude, ball-side, DALI all died this way. → Always validate cross-venue / against real labels before believing a result. This is the most reliable practice the project has.
3. **Detection quality, not logic, is usually the limiter.** Near-serve 97% vs far 47% with identical logic; cues work where the ball/player is detected and fail where they aren't.
4. **Don't reach for "camera-limited" too fast.** Brickwall overturned exactly that for far serves (it was pose *coverage*, software-fixable).
5. **Verify your own test harness first.** The DALI investigation ran for sessions on scripts missing the court mask; the "bad" numbers were the bug, not DALI.

---

## 7. Open questions worth resolving (ranked)

1. **Serve recall** — how many serves do we actually catch, each side? Gates the whole serve feature.
2. **Serve-gate latency** — can a 2nd GPU (pose) model run in the RunPod/Cloudflare path within budget?
3. **Field-footage precision (~55%)** — is there *any* lever, or is it the labeling floor again?
4. **DALI** — re-test with the proven masked recipe; it could cut real GPU cost and was never fairly judged.

---

## Appendix — full experiment index (all 99, by date → finding → status)

> Multi-part sagas grouped. Status uses the legend above.

| Date | Finding | Status |
|---|---|---|
| 08-06 | Broadcast-clip marker read (dev scaffold, not eval) | 🔵 |
| 08-06 | Prior-art: vinod-polinati ball-presence detector (ADR-021) | 🔵 |
| 08-08 | First real footage: zoom-compromised; ball-direction reinforced | 🔵 |
| 08-09 | v1 auto-annotator on 7652 raw → segments | 🔵 |
| 08-10 | YOLO nano vs x (visual) | ❌ superseded |
| 08-10 | Corrected net line: rallies clean, dead time noisy → needs tracker | 🔵 |
| 08-11 | `track_ball` wired: dead time → 0, rally preserved | ✅ |
| 08-11 | Alt detector survey (PikleYOLO, TrackNet badminton, Dettor) | 🔵 |
| 08-11 | Auto net-line (Hough on temporal median) | 🟡 |
| 08-11 | `sample_fps=10` default (hang fix) | ✅ |
| 08-12 | TrackNet-Pickleball on RunPod: 25 crossings vs YOLO 5 | ✅ |
| 08-16 | k14 vs badminton weights (IMG_7655 A/B): **k14 wins** | ✅ |
| 08-16 | Crossing-count alone can't separate rallies from casual play | 🔵 |
| 08-16 | Capped trapezoid gate works; **masking-before-inference does NOT** | ✅ / ❌ |
| 08-17 | PIC-1: recall ceiling = mid-session camera **bump**, not detection | 🔵 |
| 08-17 | Split calibration IMG_7743: recall **0.61 → 0.91**; fixed regression | ✅ |
| 08-17 | 2nd camera scored (IMG_7744): precision 0.25 | 🔵 |
| 08-17 | IMG_7744 FPs are **real exchanges**, not clutter | 🔵 |
| 08-17 | 3rd camera (pb_draft_cup): precision holds 0.25–0.29 band | 🔵 |
| 08-17 | PIC-2: blob size/confidence do NOT separate balls from clutter | ❌ |
| 08-18 | 4th camera (brickwall): raw precision 0.59 (density explains it) | 🔵 |
| 08-18 | brickwall FPs mostly **fragments of real rallies** (3rd failure mode) | 🔵 |
| 08-18 | brickwall at playback: only **2 of 44** segments actually wrong | 🔵 |
| 08-18 | pb_draft_cup is SINGLES; format drives rally length, not camera | 🔵 |
| 08-18 | **pb_draft_cup relabelled: 0.27 → 0.59 — ceiling was a LABEL artefact** | 🔵 **key** |
| 08-19 | IMG_7743/7744 re-reviewed at playback: label artefact confirmed | 🔵 |
| 08-19 | FP anatomy (PIC-37): dominant = real dead-time crossings | 🔵 |
| 08-19 | **adaptive_gap (PIC-33): beats fixed constant on every video** | 🟢 |
| 08-19 | PIC-31 duration/rate threshold does NOT separate (first pass) | ❌ |
| 08-19 | Eval-set-A locked (PIC-17) | 🔵 |
| 08-19 | PIC-43: `min_crossings=6` re-derived, converges on shipped | ✅ |
| 08-20 | **PIC-6: labeling self-consistency — ~⅓ agreement (noise floor)** | 🔵 **key** |
| 08-20 | PIC-39: adversarial review of ADR-050/051 — 0/3 survived | 🔵 |
| 08-20 | court_wedge wired into cut.py; margin open | ✅ |
| 08-20 | PIC-7: built-but-unwired quality signals; label-leakage bug caught | 🔵 |
| 08-20 | `margin_px=160` re-derived, holds (not a fluke) | ✅ |
| 08-20 | PIC-43: cap_court_heights/spread — dev-favored does NOT hold on eval | ❌ |
| 08-20 | PIC-42: YOLO-World paddle works single-frame, untrained | 🟡 |
| 08-20 | PIC-42: fails on video (single-frame test misleading) | ❌ |
| 08-20 | PIC-42: Grounding DINO recovers cleanly | 🟡 |
| 08-20 | PIC-42: 2nd camera — court_wedge solves clutter only partially | 🟡 |
| 08-20 | PIC-42: compound-phrase prompting doesn't fuse; same ceiling | 🟡 |
| 08-20 | PIC-10: Gemini verifier scoring blocked; harness now reusable | 🔵 |
| 08-20 | Direction-setting: past crossing-count arithmetic; options scoped | 🔵 |
| 08-21 | PIC-47: TrackNetV3 first benchmark (brickwall) | 🔶→❌ |
| 08-21 | Kitchen dinks **double-count** net crossings (structural defect) | 🔵 |
| 08-22 | YOLO-pose off-the-shelf works on real footage | 🟢 |
| 08-22 | **Pre-serve stillness**: sharp signal for rally START | 🟡 |
| 08-22 | Court-depth-at-serve: 2nd corroborating "who serves" signal | 🔵 |
| 08-23 | Stillness does NOT generalize to IMG_7743 (fails PIC-37 test) | ❌ |
| 08-23 | 2 "confirmed" PIC-37 FPs are actual plays (playback) | 🔵 |
| 08-23 | **All 12 PIC-37 "FPs" are real plays — zero dead time** | 🔵 |
| 08-23 | IMG_7743 postbump relabelled: precision ~perfect; recall is story | 🔵 |
| 08-23 | Correction: that framing measured wrong target; min_crossings OK | 🔵 |
| 08-23 | IMG_7744 same label gap; ADR-059 holds on 2nd video | 🔵 |
| 08-23 | **Capstone: all 4 videos honestly labeled; detection story closes** | 🔵 **key** |
| 08-23 | PIC-53: duration is a real usable signal; rate still isn't | 🟡 |
| 08-23 | Stillness ratio can't be re-tested (no genuine dead time left) | 🔵 |
| 08-23 | Stillness dip vs rally start: localization + convention finding | 🟡 |
| 08-23 | ~⅓ of ADR-060 "boundary fragments" are render.py padding, not gap | 🔵 |
| 08-23 | Selection signals: duration confirmed, crossing rate w/ caveat | ✅ |
| 08-23 | Ball velocity spikes: rejected (duration confound trap) | ❌ |
| 08-23 | Held-out: stillness dip mostly absent vs detector's own boundary | ❌ |
| 08-23 | Held-out labels: precision holds, recall doesn't (truncated points) | 🔵 |
| 08-23 | **Reel ranking: 2nd formula locked as ADR-063** | ✅ |
| 08-24 | First true E2E run on new footage (Brick-Wall-Mid-Atlantic) | ✅ |
| 08-24 | Coordinate bug found via overlay, fixed, impact measured (ADR-064) | 🔵 |
| 08-24 | Signal-overlay diagnostic reusable; stillness 0.60 data point | 🔵 |
| 08-24 | First ranked reel for IMG_7743; split-calib cutting generalized | ✅ |
| 08-24 | brickwall_pro_series_finals reel (fresh inference) | 🔵 |
| 08-24 | IMG_7652 / IMG_7655: two explained dead ends | 🔵 |
| 08-24 | select.py ranking validated vs real quality grades | ✅ |
| 08-25 | Local throughput regression = `.predict()` overhead | ✅ fixed |
| 08-25 | Full-length confirm + 2 optimizations; fix adopted | ✅ |
| 08-25 | Chunk-boundary rally loss under 10-min-chunk arch | 🔵 |
| 08-25 | **TrackNetV3 vs k14: InpaintNet config mismatch; fabrication** | ❌ |
| 08-26 | IMG_7744 (TrackNetV3): fabrication holds, worse on key metric | ❌ |
| 08-28 | 720p proxy vs native: ≈ equal (closes ADR-069) | ✅ |
| 09-04 | track_ball re-acquisition: predicted-position beats radius | ✅ |
| 09-06 | **15fps: recall halves, no threshold recovers** | ❌ 15fps |
| 09-23 | Auto-split rehearsal (ADR-127/128): 10-min parts, real cloud | ✅ |
| 09-23 | Two-camera auto-split rehearsal | ✅ |
| 09-24 | Convert-skip (ADR-130): repackage vs re-encode & detection | 🔵 |
| 09-24 | Keep-running rehearsal, real cloud | ✅ |
| 09-28 | Fixed-scale absolute rally score + session top-10 | ✅ |
| 09-28 | 0–100 score constants re-measured on PGC field footage | ✅ |
| 09-28 | 9:16 ball-following crop over a session | 🟡 |
| 10-06 | **Frame-skip for speed: collapses detection** | ❌ |
| 10-06 | Inference profiling: CPU preprocess dominates on RunPod | 🔵 |
| 10-06 | **DALI: inconclusive — scripts were broken (no mask)** | 🔶 open |
| 10-06 | **TensorRT: tooling-blocked, never measured** | 🔶 open |
| 10-07 | Encode-quality bump: marginal, not worth it | ❌ |
| 10-11 | **2D ball trace / top-down map: not a deliverable** | ❌ feature |
| 10-12 | Ball-tempo features: no gain beyond shipped score | ❌/🔶 |
| 10-23 | **Far-serve ground truth + depth floor: 19 → 47%** | 🟢 |
| 10-23 | TrackNet on far crops: detection **7/7**; discrimination not solved | 🟢 / ❌ |
| 10-24 | Brickwall: far gap = pose **coverage** (2→13); ball-side fix fails | 🟢 / ❌ |

---

*End of review. Ship-now pair (frozen-frame gate + adaptive_gap) and serve-recall measurement are the recommended next actions.*
