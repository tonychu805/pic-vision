# Decision Log

Append-only. Newest at the bottom. Each entry records what was decided, why, and what it costs — so a decision doesn't get silently reversed in six weeks when nobody remembers the reasoning.

**Format:** Context → Decision → Consequences. Keep entries short. If an entry needs more than 20 lines, the detail belongs in [`TECH_SPEC.md`](./TECH_SPEC.md) and the entry should link to it. Requirements live in [`PRD.md`](./PRD.md); measurements in [`EXPERIMENTS.md`](./EXPERIMENTS.md).

**Status values:** `accepted` · `superseded by ADR-NNN` · `revised`

**Tier naming.** Entries before ADR-026 use the original `T0 / T1 / T2` (audio+motion / players / ball). ADR-028 restructured these to `T0′ / T1′ / T2′` (motion pre-filter / players+geometry / ball presence). Older entries are left as written — they record what was decided at the time, which is the point of an append-only log. `TECH_SPEC.md` always uses current naming.

---

## ADR-001 — Prototype scope, not production

**Date:** 2026-07-30 · **Status:** accepted

**Context.** The original plan opened by describing a "production-grade AI video processing pipeline." That framing is what justified two labeled datasets, two trained models, and a seven-week runway before anyone had confirmed the core idea works.

**Decision.** Scope this explicitly as a prototype: one operator, one camera, one court, CLI only. The single production-grade discipline retained is honest measurement against a holdout set.

**Consequences.** No packaging, UI, hosting, or multi-user support. The deliverable is a *decision* about whether the approach works, not a product. If it works, a production PRD gets written with real numbers.

---

## ADR-002 — Lighting, not frame rate, is the binding capture constraint

**Date:** 2026-07-30 · **Status:** accepted

**Context.** The original plan required "30 FPS minimum, 60 recommended." Frame rate turns out to be the wrong variable. Motion blur is governed by *exposure time*: a ball at 40 mph smears ~125 px at 1/30 s and ~8 px at 1/500 s. The Tapo C200 exposes no manual shutter control, so in low light it opens the shutter and the ball becomes untrackable regardless of frame rate.

**Decision.** Make bright outdoor daylight the stated hard requirement for ball tracking. Frame rate is not the headline constraint.

**Partial mitigation (added via the ADR-025 revision).** Locking the camera to 30 fps caps the maximum exposure at 1/30 s, because a camera cannot expose longer than its frame interval. That bounds the worst-case smear at ~125 px instead of the ~250 px that 15 fps would have allowed. It does not deliver the ~1/500 s daylight tracking wants, so **lighting remains the binding constraint** — but the floor is no longer open-ended, and it costs nothing.

**Consequences.** Indoor sessions are expected to fail ball tracking — this drove ADR-003. A low-light eval set exists specifically to measure the degraded path.

---

## ADR-003 — Tiered architecture, each tier independently shippable

**Date:** 2026-07-30 · **Status:** accepted

**Context.** The original design was a single pipeline: detect court keypoints, detect ball and players, apply spatial logic, cut. If ball detection failed — and per ADR-002 it fails in poor light — the pipeline produced nothing.

**Decision.** Three tiers. T0 (audio + motion, CPU) produces a complete rally cut on its own. T1 (players) and T2 (ball) only refine it. Higher tiers are never load-bearing.

**Consequences.** More plumbing, and every tier needs a fallback path. In exchange, there is no single point of total failure, and each phase ends with a working artifact. See `TECH_SPEC.md` §3.

---

## ADR-004 — Audio is an optional refinement signal, not the primary detector

**Date:** 2026-07-30 · **Status:** **revised 2026-07-30** (see revision note)

**Context.** The original plan had no audio component at all. Paddle-on-ball impact is a loud, sharp, spectrally distinctive transient — far easier to detect than a 10-px motion-blurred object. A rally is a dense cluster of impacts; dead time is silence and conversation.

**Original decision.** Lead with audio onset detection. No labels, no training, no GPU. Described as "the highest signal-to-effort ratio in the system."

### Revision — audio has no spatial selectivity

That claim holds for a single court in the open. It fails in a venue, for a reason that isn't about noise levels at all:

> **A camera pointed at one court sees only that court. A microphone hears the entire building.**

In a multi-court hall every court produces *acoustically identical* paddle impacts. That is not noise to be filtered — it is the exact signal being searched for, arriving from the wrong place, and a single omnidirectional mic cannot separate it. Impact density then means "someone, somewhere, is playing," which is worthless.

Three further venue problems, in severity order: adjacent courts (unfixable with one mic), long reverberation smearing the transient attacks that onset detection depends on, and PA music generating continuous false onsets.

**Revised decision.** Audio is **one signal whose weight is context-dependent**, never a dependency:

| Context | Role |
|---|---|
| Single court, outdoor, own camera (the prototype) | Useful. Cheap boundary precision. |
| Multi-court indoor venue | Weight drops to zero. Video carries the product. |

Two mechanisms make this automatic rather than a judgement call:

1. **Audio usability gate** (`TECH_SPEC.md` §1.1) — measure onset density during a known dead-time stretch. Dense onsets while nothing is happening on *your* court means audio is contaminated, and its weight is set to zero for that recording.
2. **Cross-modal gating** (ADR-027) — where audio is used, gate onsets on simultaneous court-ROI motion.

**Consequences.** Detection must work with audio entirely absent, which forced the restructure in ADR-026. Open question #1 is downgraded from "gates the project" to "determines which configuration is used" — a much healthier place for it. The tiered architecture (ADR-003) absorbed this without redesign, which is the third time it has paid for itself.

---

## ADR-005 — Ball detection: high-resolution YOLO first, motion-based architecture as fallback

**Date:** 2026-07-30 · **Status:** **revised 2026-07-30** (see revision note)

**Context.** The original plan used YOLOv8 for the ball. YOLO detects from a single frame, and a 6–15 px motion-blurred ball has little single-frame appearance signal — much of the information lives in motion across frames.

**Original decision.** If ball tracking is built, use a TrackNet-family architecture (3 consecutive frames → heatmap regression, trajectory as a detection cue), on an estimate of ~40–60% recall from single-frame YOLO versus 85%+ from a motion-based model.

### Revision — prior art contradicts the estimate

Three independent pickleball CV projects (see `TECH_SPEC.md` §2, prior art) report workable ball detection from plain YOLOv8:

- Tolone reports **~60% ball detection at `imgsz=640`, rising to ~100% at `imgsz=1280`** with a fine-tuned detector.
- vinod-polinati gets usable rally segmentation from **off-the-shelf YOLOv8x on the COCO `sports ball` class** at 1280, confidence 0.15, with size / shoe / physics filters compensating for the low threshold.

The ~40–60% figure was right — **for 640**, which matches Tolone's 640 number closely. It was wrong as a claim about YOLO in general, because it silently assumed the resolution the original plan specified and ADR-006 rejected.

**Revised decision.** A detection ladder, cheapest first:

1. Off-the-shelf YOLOv8 at `imgsz=1280` on the COCO `sports ball` class, with aggressive filtering
2. YOLOv8 fine-tuned on pickleball footage, same resolution
3. TrackNet-family architecture — **fallback, not default**

**Consequences.** Phase 3 gets substantially cheaper and less risky: rung 1 needs no labels and no training at all. TrackNet stays specified in case rungs 1–2 miss the boundary-error target, but is no longer assumed. This also strengthens ADR-006 — the entire disagreement turned on resolution.

---

## ADR-006 — Never downscale to 640×640

**Date:** 2026-07-30 · **Status:** accepted · **reinforced by the ADR-005 revision**

**Context.** The original plan resized frames to 640×640 "for inference speed." At 1080p the ball is 6–15 px; that downscale leaves 2–3 px, and it also breaks aspect ratio.

**Decision.** Crop to the court region and run at higher resolution, or use sliced inference. Players survive a downscale; the ball does not.

**Consequences.** Higher per-frame cost, offset by running on far fewer frames (ADR-012). Prior art puts a number on this: Tolone measures ball detection going from ~60% at 640 to ~100% at 1280. The entire ADR-005 disagreement turned out to be about this one parameter.

---

## ADR-007 — Calibrate the court by hand, once

**Date:** 2026-07-30 · **Status:** accepted

**Context.** The original plan trained a `yolov8n-pose` model to locate the 12 court intersections, requiring its own labeled dataset. But the camera is fixed by product constraint — the court never moves in frame.

**Decision.** Click the 12 intersections once per mount, store the calibration to JSON, reuse it for every session.

**Consequences.** Roughly 90 seconds of human time replaces ~2 weeks of labeling and training. Deletes an entire dataset. Revisit only if multi-court generalization is ever promoted from deferred — that is the one scenario where a keypoint model earns its cost.

---

## ADR-008 — No player tracking (ByteTrack) in the prototype

**Date:** 2026-07-30 · **Status:** accepted

**Context.** The original plan used ByteTrack to assign persistent IDs to players.

**Decision.** Cut it. Rally detection does not need to know which player is which.

**Consequences.** In doubles, IDs would swap on every crossing and net occlusion anyway, so little is lost. Revisit when per-player statistics become a goal — that feature needs tracking *and* re-identification across occlusions.

---

## ADR-009 — Ground-plane projection applies to feet only

**Date:** 2026-07-30 · **Status:** accepted

**Context.** The original plan mapped all detected entities to court coordinates through the court homography. A homography maps a *plane*. An airborne ball projected through a ground-plane homography yields a meaningless coordinate whose error grows with the ball's height.

**Decision.** Project only player foot positions (bounding-box bottom-center) to court space. Detect ball bounces from trajectory curvature in image space instead.

**Consequences.** Any future feature needing true 3D ball position (shot classification, line calls) requires a second camera or a ballistic model. Noted so nobody assumes court-space ball coordinates are available.

---

## ADR-010 — Rally boundaries come from a debounced state machine

**Date:** 2026-07-30 · **Status:** accepted

**Context.** The original heuristics were "rally ends when ball velocity reaches zero" and "when tracking drops for > 2 s." The first is never observable — the ball is lost long before it stops. The second fires constantly mid-rally on ordinary detection dropouts, splitting single rallies into several.

**Decision.** An explicit state machine with hysteresis: separate enter and exit thresholds, a sustained-signal requirement before arming, and a cooldown that can recover mid-rally rather than terminating. Detail in `TECH_SPEC.md` §6.

**Consequences.** Four tunable parameters instead of one threshold, all of which must be fit on the dev set only (ADR-016).

---

## ADR-011 — Ball tracking is gated on the coarse tiers falling short

**Date:** 2026-07-30 · **Status:** accepted

**Context.** Ball tracking is the most expensive component — a custom training run, new labels, and per ADR-014 the only stage that cannot run locally at full scope.

**Decision.** Phase 3 is entered only if Phases 1–2 miss the PRD's detection targets. If audio and player motion suffice, ball tracking never gets built.

**Consequences.** Total timeline swings between 2.5 and 4.5 weeks. Requires the discipline to actually stop when the numbers pass, rather than building the interesting part anyway.

---

## ADR-012 — Local coarse pass, cloud only for what needs it

**Date:** 2026-07-30 · **Status:** accepted

**Context.** A 2-hour session is ~2.7 GB. Uploading all of it to cloud compute is often slower than the processing, and ~60% of it is dead time nobody needs to process.

**Decision.** Run T0 locally on the full recording. Upload only candidate segments (~40%) if a later tier needs a GPU. Cut and render locally from the original full-quality file.

**Consequences.** Frame budget drops from ~216,000 to ~80,000, and upload volume by more than half. Adds a stage boundary and a caching requirement. Largely superseded in practice by ADR-014 — most tiers turn out to run locally anyway.

---

## ADR-013 — Do not stream live to cloud compute

**Date:** 2026-07-30 · **Status:** accepted · **scope narrowed by ADR-024**

> **Scope note.** This ADR rejects **live streaming** specifically. It does *not* reject recording locally and uploading afterward — that is a different architecture and ADR-024 accepts it for venue deployment.

**Context.** Considered streaming the camera's feed directly to a cloud GPU over the network.

**Decision.** Rejected. Capture to a local file with `ffmpeg`, segmented for crash safety; process afterward.

**Consequences.** Four reasons, each sufficient on its own:

1. **Cost inverts** — streaming means transporting and processing 100% of the footage and renting the GPU for the full session wall-clock, roughly 3–8× the cost for a worse result.
2. **Exposure** — reaching the camera from outside the LAN means exposing a consumer camera's stream to the internet, publishing a live video feed of a public court.
3. **No recovery** — a local recording survives a network hiccup or a preempted cloud session. A live stream doesn't; those two hours are gone.
4. **Loses lookahead** — deciding a rally *ended* requires seeing what happens after it. Batch gets this free; live forces causal-only decisions.

---

## ADR-014 — MacBook Air M2 runs everything except ball tracking

**Date:** 2026-07-30 · **Status:** accepted

**Context.** Target machine is a fanless MacBook Air M2. Two properties matter: a hardware media engine (H.264 encode *and* decode), and a GPU reachable from PyTorch via Metal plus a Neural Engine reachable via CoreML.

**Decision.** Run capture, T0, T1, and rendering locally. Send only ball-tracking *training* to free cloud GPU (Kaggle).

**Consequences.** Rough estimates, to be replaced by Phase 0 measurements:

| Stage | On the M2 | Notes |
|---|---|---|
| Decode + encode | Fast | Hardware media engine; the codec-bound bottleneck largely disappears |
| T0 motion + audio | ~10–15 min per 2 h session | Frame differencing is a few seconds; decode dominates |
| T1 players | ~3–6 min | Requires sampling at ~2 fps and CoreML on the Neural Engine, not Metal |
| T2 ball, full rallies | ~2 h, thermally throttled | Exceeds the runtime budget on its own — drove ADR-015 |

Fanless means sustained loads throttle; add 20–40% to any peak figure.

---

## ADR-015 — Ball tracking runs only in windows around boundaries

**Date:** 2026-07-30 · **Status:** accepted

**Context.** Ball tracking has no temporal sampling lever. Motion energy and player position are slowly varying and can be sampled at 2–5 fps; a 3-frame trajectory model needs *every consecutive frame* by construction. That is what makes it ~100× more expensive than player detection — not model size. At full scope it is ~86,000 frames and ~2 hours on the M2, which alone breaks the runtime budget.

**Decision.** Run it only in ±3 s windows around already-detected rally boundaries — its sole job is tightening timestamps, and detection already works without it.

**Consequences.** ~14,000 frames instead of ~86,000: about 6× cheaper, ~16 min on the M2, and the whole pipeline stays local. Gives up mid-rally ball trajectory, which nothing in scope uses. Full-rally tracking is reserved for whenever shot classification is promoted.

---

## ADR-016 — Build the eval sets before building anything else

**Date:** 2026-07-30 · **Status:** accepted

**Context.** The original plan contained no success metric — no claim in it was falsifiable. Its first two weeks were labeling data for models that ADR-005 and ADR-007 later cut.

**Decision.** Phase 0 labels three sets — a locked acceptance set, a tuning set, and a low-light set — and stands up the eval harness against a hand-written stub before any detector exists. Rally intervals only; a few seconds of labeling each.

**Consequences.** About an hour of work, and it is what makes every subsequent claim checkable. Requires never tuning on the acceptance set, which is easy to violate accidentally and is the quiet high-impact risk in the PRD.

---

## ADR-017 — Two artifacts: a ranked reel and a complete cut

**Date:** 2026-07-30 · **Status:** accepted

**Context.** The original summary promised a reel of "the best moments" while its logic produced *every* rally — two different products described in one document. Then a hard requirement landed: output must be under 10 minutes. A 2-hour session holds 25–40 minutes of live play, so cutting dead time alone cannot reach 10 minutes. Selection is mandatory, which promotes ranking from deferred into the prototype.

**Decision.** One detection pass, two renders: a ranked reel under budget, and the complete cut. They differ only in a selection stage.

**Consequences.** Costs ~30 lines and keeps the study-play use case instead of trading it away. Requires detection and selection metrics to be measured separately (ADR-018).

---

## ADR-018 — Detection and selection are measured separately

**Date:** 2026-07-30 · **Status:** accepted

**Context.** With selection in the pipeline, a rally can be absent from the reel for two very different reasons: it was never detected, or it was detected and deliberately dropped to fit the budget.

**Decision.** Detection metrics are computed on the complete rally list, before selection. Selection metrics are computed on the reel. Never combined.

**Consequences.** Measured together, recall would silently absorb budget decisions and stop meaning anything. The complete list is retained in the output regardless of what's selected, so re-running selection with different weights never requires re-running detection.

---

## ADR-019 — The ranker stays deliberately dumb

**Date:** 2026-07-30 · **Status:** accepted

**Context.** Selection needs a rally score. A learned or preference-validated ranker would need pairwise human judgments and a model — weeks of work, and pointless if detection turns out not to work.

**Decision.** Three hand-weighted features already produced by detection: rally duration, impact count, peak motion. No new model, no new labels.

**Consequences.** Every quantitative metric can pass on a reel that's boring — the highest-impact risk nothing in the metrics catches. Mitigated by making the subjective gate a hard gate. Preference-validated ranking is the first deferred item to revisit.

---

## ADR-020 — Chronological order in the reel

**Date:** 2026-07-30 · **Status:** accepted

**Context.** Selection produces rallies ranked by score. They could be rendered in that order.

**Decision.** Re-sort chronologically before rendering.

**Consequences.** Score order produces a reel that jumps around the session with no narrative and inconsistent light. Chronological is what makes it watchable. Whether building to a climax beats chronological is open question #5 — worth one experiment, not now.

---

## ADR-021 — Benchmark prior art before building a detector

**Date:** 2026-07-30 · **Status:** accepted

**Context.** A survey turned up several open pickleball CV projects (`TECH_SPEC.md` §2). One of them — vinod-polinati, MIT licensed, ~200 lines — implements roughly Phases 1–2 of this plan: YOLO ball detection, filtering, a binary ball-present timeline with gap tolerance, and FFmpeg clip extraction. None of them publishes a single accuracy number.

**Decision.** Phase 1 begins by running existing implementations against `eval-set-A` and scoring them with our harness, **before** writing a detector.

**Consequences.** A day of work with two good outcomes: it performs well and two weeks are saved, or it fails and we know precisely how, with a baseline to beat. The eval harness (ADR-016) is what makes this possible — it is the thing these projects lack, which is a reasonable sign it was the right first build.

Risk: temptation to adopt an unmeasured implementation because it exists. The harness result governs, not the README.

---

## ADR-022 — Ball *presence* may be a sufficient rally signal

**Date:** 2026-07-30 · **Status:** accepted (as a hypothesis to test)

**Context.** This plan assumed rally detection needs good ball *tracking* — trajectory, velocity, bounces. vinod-polinati instead builds a binary "is a ball visible this frame" timeline and applies gap tolerance. Detection quality barely matters, because occasional misses are bridged by the same debouncing the state machine already does.

**Decision.** Treat ball presence as a candidate feature in the fusion score, alongside audio onsets and motion energy — not as a separate tier requiring trajectory quality.

**Consequences.** Substantially weakens the requirement that motivated ADR-005, and reinforces the ADR-011 gate: full trajectory tracking may never be needed for rally detection at all. Trajectory is still required for tight *boundaries* (ADR-015) and for any future shot classification.

---

## ADR-023 — ONNX is the canonical model exchange format

**Date:** 2026-07-30 · **Status:** accepted

**Context.** Local inference was specified as CoreML on Apple Silicon. That is a dead end anywhere else, and it entangles the training framework with the deployment target. Separately, TensorFlow's Metal plugin has documented problems — GPU slower than CPU on small models, unfused op fallbacks, correctness bugs in some layers.

**Decision.** Train in whatever framework the reference implementation uses, export to **ONNX**, then convert per platform: CoreML on Apple Silicon, DirectML or OpenVINO on Windows, TensorRT on NVIDIA. Accelerator selection is a config key (`hwaccel`, `inference_backend`), never hard-coded.

**Consequences.** The training framework becomes an implementation detail of whichever repo we fork — the TensorFlow-versus-PyTorch question disappears. ~20 lines of abstraction now, versus a rewrite later. Prefer PyTorch ports where available anyway: its Metal support is more mature than TensorFlow's.

---

## ADR-024 — Upload-then-process is accepted for venue deployment

**Date:** 2026-07-30 · **Status:** accepted (post-prototype; not built now)

**Context.** Venue deployment would mean unknown, varied Windows hardware — no reliable accelerator, no consistent runtime. Uploading recordings to cloud compute removes hardware variance entirely: the venue machine only records and uploads, which any CPU can do.

This is **not** what ADR-013 rejected. Three of that ADR's four objections don't apply: nothing inbound is exposed, the local recording survives network failure, and processing stays batch so lookahead is preserved. Only the cost objection carries over, and tiering mitigates it.

**Decision.** Accepted as the architecture *if* venue deployment happens. Not built during the prototype.

**Consequences.**

- **Bandwidth becomes the ceiling, not compute.** ~2.7 GB per 2-hour session; a 4-court venue generates ~43 GB/day, roughly 5 hours of saturated 20 Mbps uplink. Beyond ~6 courts it stops working.
- **The tiering already fits:** cheap CPU workers run T0, GPU workers run T1/T2 on candidate segments only. NFR2 becomes a cost lever rather than a laptop constraint.
- **Privacy posture inverts** — this contradicts the prototype's local-only default and becomes a work stream: encryption, retention with hard deletion, per-venue isolation, consent signage, a data processing agreement.
- **It makes you a service operator** — queue, workers, auth, monitoring, result delivery. All currently out of scope (ADR-001).
- **Preferred variant:** put capture *and* T0 on a small dedicated box you control (~$100–200 mini PC or Pi) rather than the venue's PC. Cuts upload and cloud compute ~60%, keeps most footage in the building, and removes the variable hardware instead of routing around it.

---

## ADR-025 — Frame rate is fixed at 30 fps, and that also caps exposure

**Date:** 2026-07-30 · **Status:** **revised 2026-07-30** (see revision note)

**Context.** Earlier drafts required "1080p at 30 fps, set explicitly and verified," on the strength of a spec sheet reading *default 15 fps, max 30 fps*.

**Original decision.** Recorded that the C200 exposes no frame-rate control, that the camera chooses based on light, and that preflight should therefore measure rather than assert — with the pipeline branching on the observed rate.

### Revision — the rate is configurable and has been fixed at 30

The camera **does** expose the control. It is set to 30 fps and does not vary. The premise of the original entry was simply wrong.

**Revised decision.** 30 fps is a fixed property of the capture setup. Preflight **confirms it once** rather than branching on it, and the 15 fps degradation path is retired.

Two consequences follow, and the second is the interesting one:

**1. A fixed rate converts a timing failure into an image-quality failure.** If light is inadequate the camera can no longer drop to 15 fps; it must raise gain instead. That is a much better failure mode. Noise degrades detection gradually and is a detector problem. A varying frame rate silently corrupts every timestamp and is a *correctness* problem — the kind you discover weeks later when boundaries drift for no visible reason.

**2. Locking 30 fps puts a floor under the shutter speed.** A camera cannot expose longer than its frame interval, so the worst case is now 1/30 s rather than the 1/15 s that 15 fps would have permitted. This is a **partial mitigation of ADR-002** — it does not deliver the ~1/500 s that daylight ball tracking wants, but it bounds how bad the smear can get, and it does so without any shutter control. The frame-rate setting is an indirect exposure control.

**What survives from the original entry** — both are cheap and remain good practice regardless:

1. **Timestamps come from PTS, never `frame_index / fps`.** Costs nothing, and removes a whole class of silent drift.
2. **Temporal parameters are configured in seconds and converted at runtime.** Never hard-code frame counts. Prior art bakes in "0.6 s = 18 frames @ 30 fps," which breaks the moment anything about the capture changes.

**Consequences.**

- **Trajectory refinement is available again** if it is ever wanted (§5.3.2 ladder). At 30 fps the ball moves 2–3 ft per frame, which is tractable for velocity-predicted association. Not currently needed — trajectory is out of scope — but the door is open rather than closed by hardware.
- Compute is unchanged. Motion samples at 5 fps and players at 2 fps, so neither cares about the source rate; only trajectory needs every frame.
- Preflight keeps the PTS-delta histogram, but as a **one-time confirmation in Phase 0**, not a per-session gate. Confirm once, then stop thinking about it.
- The ADR-029 shopping-list line "stated, stable frame rate" is satisfied by the current camera. ADR-002's shutter problem is *mitigated but not solved* — lighting remains the binding constraint.

---

## ADR-026 — Detect dead time, not rallies

**Date:** 2026-07-30 · **Status:** accepted

**Context.** With audio demoted (ADR-004) and trajectory dropped, detection rests on video. The obvious approach is to score "rallyness" positively — high motion, players moving, ball around — and threshold it. Every one of those is a matter of degree, and thresholds on degrees are exactly what overfits to a single session (the standing high-likelihood risk).

Dead-time markers, by contrast, are **discrete and geometric**, and a calibrated fixed camera sees them cleanly.

**Decision.** Invert the logic. Detect dead-time events, union them into a mask, and take rallies as the complement filtered by minimum duration.

| Dead-time event | Why it is reliable |
|---|---|
| A player crosses the net line | Never happens during a point |
| A player leaves the court polygon | Ball retrieval, towel, drink |
| Ball held — ball box inside a player box > 0.5 s | A ball in play is never attached to a body |
| All players stationary > 1.5 s | Score discussion, waiting |
| Fewer than N players in court | Between games |

This is also how a person does it: you don't watch for a rally starting, you notice when play stops.

**Consequences.**

- The state machine's job changes from thresholding a fuzzy score to smoothing a mostly-binary mask. Far fewer parameters, far less to overfit.
- Detection quality now depends on **player detection and court calibration**, not on ball quality — which suits a fixed, hand-calibrated camera.
- **Validate before building** (`EXPERIMENTS.md`): measure how often each dead-time event fires *during* a labelled rally. Net crossings and court exits must be near zero. If detection noise or occlusion makes them fire, the inversion is unsound and positive scoring returns. One hour of work; do it before writing the segmenter.
- Near-player occlusion from a baseline camera will drop player counts spuriously, so the count test needs tolerance rather than strictness.

---

## ADR-027 — Where audio is used, gate it on video motion

**Date:** 2026-07-30 · **Status:** accepted

**Context.** Audio and video fail in opposite directions. Audio has excellent temporal precision — an impact transient is sharp to within tens of milliseconds — but no spatial selectivity. Video is spatially confined to the court but temporally smeared, especially when sampled at 2–5 fps.

**Decision.** Count an audio onset as a real impact only when there is simultaneous motion in the court ROI. Video decides *where*, audio decides *when*.

**Consequences.** Adjacent-court impacts are rejected because nothing moved on our court, which addresses the main objection in the ADR-004 revision. Costs a couple of lines on top of features that already exist. Audio's role becomes boundary refinement — the same role trajectory was going to play before it was dropped (ADR-022), so the pipeline has two independent ways to sharpen boundaries and needs neither.

---

## ADR-028 — Player geometry is the primary detector

**Date:** 2026-07-30 · **Status:** accepted

**Context.** ADR-004 removed audio from the lead role and ADR-026 changed what is being detected. The tiering needed to follow.

**Decision.**

```
T0'  motion energy only          → coarse pre-filter, skips dead stretches
T1'  player detection + geometry → dead-time events → segmentation   [PRIMARY]
T2'  ball presence               → refinement, optional
```

Two features carry most of the discrimination, and both are stronger than raw motion magnitude:

- **Direction-reversal rate of player velocity**, in court feet via the homography. Walking to retrieve a ball is smooth and unidirectional for seconds; rally movement reverses constantly — split-step, lateral, forward-back. Counting sign changes separates them, where raw motion magnitude conflates "playing hard" with "walking briskly."
- **Ball side-alternation.** Detected left of the net at *t*, right at *t+k* means play is in progress. A weak trajectory in the only dimension that matters, free on top of presence detection.

**Consequences.**

- Player detection now runs across the whole session rather than on candidates. At 2 fps that is ~14,400 frames for a 2-hour session, roughly 10–16 min on the ANE — still inside the runtime budget.
- **Boundary precision is what is lost.** Video at 2 fps gives ~500 ms granularity, making the 1.0 s target tight. Mitigated by re-running detection at full frame rate in ±3 s windows around boundaries — the same trick as ADR-015, transferred.
- **New systematic false positive: courtesy returns.** After a point, someone taps the ball back to the server, producing a net crossing, a side-alternation, and a motion burst. This happens after *every* point, so it is systematic rather than rare. Mitigation: require ≥ 2 ball side-alternations plus minimum duration — a real rally has several crossings, a courtesy return exactly one.
- Warm-up remains indistinguishable from play by every signal here. Accepted, not solved.

---

## ADR-029 — Camera selection criteria; standalone operation is the hard constraint

**Date:** 2026-07-30 · **Status:** accepted

**Context.** Two cameras have now been evaluated, and the criteria were re-derived from scratch both times. Given that the C200's shutter behaviour (ADR-002) and uncontrollable frame rate (ADR-025) are both unresolved, another camera evaluation is a matter of when, not if. Writing the checklist down once is cheaper than re-deriving it.

**Decision.** A camera must satisfy these to be viable for the prototype:

| Requirement | Why | Source |
|---|---|---|
| **Standalone operation** — no NAS, cloud, or hub in the recording path | Capture happens at courts with no network back to base. This is the hard filter. | CC400W evaluation |
| Local capture: microSD **or** direct RTSP to a laptop | Same | ADR-013 |
| **Fast minimum shutter, ideally controllable** | The actual cause of ball blur — not frame rate | ADR-002 |
| Stated, stable frame rate | The C200 chooses for you and won't say what it picked | ADR-025 |
| FOV matched to the intended mount distance | A very wide lens from a baseline mount compresses the far court badly | CC400W evaluation |
| Power available at the court | Battery or a reachable outlet | — |

**Not on the list: audio.** It would have been critical three revisions ago; ADR-004 removed it as a dependency. Its absence here is a small piece of evidence that the tiering is doing its job.

### Worked example — Synology CC400W, rejected for the prototype

Evaluated 2026-07-30. Strong on paper: 2560×1440 @ 30 fps, published shutter range 1/16000–1/30 s, F2.0, RTSP + ONVIF, built-in mic.

**Rejected because it operates only through Surveillance Station**, which fails the standalone requirement — there is no network path from a pickleball court to a NAS at home.

Two further findings worth keeping:

- **Resolution gains can be cancelled by field of view.** Its 2.12 mm lens gives 125° horizontal FOV. Mounted where the C200 sits, the court occupies less of the frame, and severe foreshortening from a baseline position could leave the far-baseline ball at ~3–4 px — *smaller* than on the 1080p C200. More megapixels do not help when the far half of the court is compressed into a narrow band. Judge cameras on **pixels-on-ball at the far baseline**, not sensor resolution.
- **A published shutter range is a checkable spec.** The CC400W states 1/16000–1/30 s; the C200 states nothing. When shopping against ADR-002, this is the line to look for.

**Consequences.** If Phase 0 shows the C200's shutter behaviour is fatal, this table is the shopping list and the far-baseline pixel calculation is the acceptance test. Separately, **CC400W + Surveillance Station is a good fit for venue deployment** (ADR-024) — fixed mount, wired power, continuous NAS recording, which is exactly the dedicated-capture-box shape that ADR describes. It is a "not for the prototype," not a "no."

---

## ADR-030 — Use wallclock timestamps, not camera RTP timestamps, for RTSP capture

**Date:** 2026-08-04 · **Status:** accepted

**Context.** RTSP capture testing over wifi showed intermittent frame drops — one test captured 113 of 900 expected frames. The TP-Link camera's RTP timestamps proved unreliable and non-monotonic, which compounds the problem of handling dropped frames downstream. Follow-up measurement (n=4 captures, 8–39 s, counting decoded frames) put *typical* delivery at 90–96% of expected @30fps — so the 113/900 (~12.5%) case is the intermittent worst run, not the norm. Loss is bursty (isolated stalls of ~1–4 s), not a steady low rate, and all four were short captures on a network measuring 6–11 ms ping / 0% loss at the time — congestion or a full 2-hour session could still be worse.

**Decision.** Pass `-use_wallclock_as_timestamps 1` to ffmpeg on capture, rather than trusting the camera's RTP timestamps.

**Consequences.** Timestamps reflect local receive time instead of camera-side timing, consistent with PTS already being the source of truth (ADR-025) and never `frame_index / fps`. Does not fix the underlying frame drops — that's ADR-032 — but stops bad timestamps from silently corrupting downstream analysis. **Caveat, observed live:** even with the flag set, ffmpeg still logged `Timestamps are unset in a packet for stream 0` while writing the MKV. The output probed cleanly (PTS present, gaps measurable) so it didn't bite, but the flag isn't fully overriding the muxer path this ADR assumes — verify before trusting it for a real session.

---

## ADR-031 — Clean-stop requirement for recordings

**Date:** 2026-08-04 · **Status:** accepted

**Context.** Hard-killing an ffmpeg capture process (e.g., via `timeout`/SIGKILL) risks corrupting the output container — observed with the pcm_alaw audio codec in an MKV wrapper.

**Decision.** Always stop recordings cleanly: use ffmpeg's own `-t <duration>` flag to end automatically, or send SIGINT and let ffmpeg finalize the file. Never externally hard-kill the process.

**Consequences.** Slightly less flexible for ad-hoc early stops — must send SIGINT, not SIGKILL. In exchange, output files are reliably valid and playable; an external hard kill was observed to corrupt the MKV container.

---

## ADR-032 — Prefer local microSD recording over wifi/RTSP capture, once available

**Date:** 2026-08-04 · **Status:** accepted

**Context.** Wifi RTSP capture testing showed intermittent, severe frame drops (113/900 frames in one test) — a network-reliability problem that timestamp handling (ADR-030) and clean stops (ADR-031) don't fix.

**Decision.** Once the camera has a card installed, prefer recording locally to microSD over pulling RTSP to the Mac. This removes the network-reliability dependency entirely.

**Consequences.** Requires a manual pull/export step after each session — this was previously rejected for the Tapo C200 (`TECH_SPEC.md` §1.2) for different reasons (no certainty about frame rate/audio actually written). The trade-off may differ for this camera; worth re-evaluating card size (PRD §9) and export path once hardware is in hand. Wifi RTSP remains the fallback where local recording isn't available.

---

## ADR-033 — Hybrid local/cloud split for future stats/identity features

**Date:** 2026-08-04 · **Status:** accepted (post-prototype; not built now)

**Context.** Any future score-tracking, player-tracking, or per-player-stats feature (PRD §10, deferred) will eventually raise the question of where data lives. The prototype's privacy stance (PRD §6) is local-only by default.

**Decision.** If these features are ever built: raw video and all detection/inference stay local, always. Only small, consented, non-video data — player profiles, aggregate stats — are candidates for cloud sync, and only with explicit opt-in.

**Consequences.** Keeps the highest-risk data — video of people who haven't consented — off the network categorically, rather than relying on per-feature judgment calls later. Non-video stats sync is deferred design, not a commitment; this just fixes the boundary in advance.

---

## ADR-034 — Check-in/opt-in identity linking over biometric re-identification

**Date:** 2026-08-04 · **Status:** accepted (post-prototype; not built now)

**Context.** Cross-session player identification, needed for any longitudinal stats, requires some form of re-identification. Biometric re-ID (face or gait recognition) is in direct tension with the "no face recognition ever" stance (PRD §6), which is intended to cover non-consented re-identification generally, not just literal facial recognition.

**Decision.** If cross-session identification is ever built, use an opt-in check-in mechanism — a QR code scan or name selection at session start — or a visual marker (wristband/pinnie) for within-session linking, instead of any biometric re-ID.

**Consequences.** Anonymous within-session tracking is unaffected (ADR-008) — it needs no identity linking at all. Cross-session identification becomes opt-in and revocable rather than automatic, at the cost of requiring active participation from players. No biometric data is ever collected.

---

## ADR-035 — Order-independent court calibration

**Date:** 2026-08-06 · **Status:** accepted

**Context.** `calibrate.py` required the 12 court points to be clicked in the tool's prompted sequence (corners → kitchen lines → centerline). A natural near→far clicking order silently mismatched clicks to labels and produced a garbage homography — **28.2 ft reprojection RMSE on correctly-placed clicks**. Click order is an error-prone constraint, and it gets worse anywhere a non-expert calibrates.

**Decision.** Make calibration order-independent. The tool fits a homography from convex-hull corner candidates (trying all orderings), matches the remaining clicks to court points by minimum reprojection error, then resolves the court's near/far and left/right symmetry using the behind-baseline framing (near baseline lower in the image; near-left left of near-right). Points may be clicked in any order.

**Consequences.** Removes an entire class of calibration error — the same 28-ft mis-ordered clicks now yield 0.36–0.42 ft. Assumes the four corners lie on the convex hull (true for any full-court view above the feet-visible elevation) and a standard, non-mirrored behind-baseline camera to fix left/right. A perfectly symmetric projection is ambiguous in principle, but real cameras break the symmetry. `compute_calibration` is split out of the GUI and covered by a synthetic round-trip test plus the real mis-ordered clicks as a fixture.

---

## ADR-036 — Detection runs in court coordinates; calibration absorbs camera pose, not occlusion

**Date:** 2026-08-06 · **Status:** accepted

**Context.** Different courts mount the camera at different heights and positions, so the court's image points differ court by court. Does that break a shared detection model across courts?

**Decision.** Run all detection logic in **court coordinates** (feet, top-down), never raw pixels. Detect players off-the-shelf in pixels, take the **foot point** (bottom-centre of the box), and project it to court coordinates via that court's calibration. Dead-time markers and all geometry are computed in court space.

**Consequences.** Per-court calibration absorbs camera elevation and position, so one model generalises across courts without retraining — "player at the kitchen line" is the same court coordinate everywhere. What calibration does **not** normalise: occlusion (a lower camera hides far players more) and, later, ball parallax (the ball is off the ground plane). So a minimum elevation must be enforced (PRD §6, ≥ 8 ft, feet visible); above it, elevation is a calibration detail, below it occlusion breaks detection regardless of the homography. Ties to the multi-venue architecture in `STRATEGY.md` §4 (universal model in court-normalised space + per-venue calibration).

---

## ADR-037 — Two-sided live/stopped evidence; no marker decides alone

**Date:** 2026-08-06 · **Status:** accepted

**Context.** ADR-026 detects dead time and takes rallies as the complement. But several of its dead-time markers are **context-ambiguous** — they also fire during *live* play. Chasing a lob or a wide shot trips "player left the court" mid-rally; a dink exchange trips "all players stationary" while the point is very much on. A single geometric marker cannot separate "walked off between points" from "sprinted off-court to return a lob."

**Decision.** Keep dead-time inversion as the backbone, but make it two-sided: maintain a **live-play marker list alongside the stopped-play list**, and have the segmenter **weigh live evidence against stopped evidence** per time window. No single marker flips the state; an ambiguous stopped-marker is overridden when live markers corroborate.

- *Stopped-play (dead time):* net-line crossing · ball held/stationary · casual low-energy walking · left the play envelope **and stayed** · players clustered facing each other · sustained stillness in relaxed posture.
- *Live-play (rally ongoing):* ball in fast flight / crossing the net · high player motion (sprint / lunge / backpedal / direction reversal) · athletic ready stance facing the net at kitchen/baseline · recent paddle swing · all four players engaged.

The two hard cases resolve by pairing: a **lob chase** fires "left court" (stopped) but high motion + ball-in-flight (live) win; a **dink** fires "stillness" (stopped) but engaged kitchen stance + ball-crossing (live) win.

**Consequences.** More robust than pure inversion, at the cost of more signals to combine (persistence + corroboration, not raw counting). The two hardest cases split on motion: **lobs are high-motion** (caught without the ball), **dinks are low-motion** — so the cleanest "still live" signal for a dink is the **ball**, which means ball presence may be needed earlier than "just a refinement" for the dink case specifically. Position/pose may suffice (kitchen ready stance ≠ relaxed dead-time posture) — Phase 0.6 must measure it, not assume it. This supersedes nothing in ADR-026; it promotes that ADR's §6.2 positive-scoring fallback to a first-class counter-signal. Validation is now two-directional (`EXPERIMENTS.md`): each stopped marker's fire-rate during rallies, and each live marker's during dead time.

---

## ADR-038 — Prove the ball signal in software (and lighting) before any hardware upgrade

**Date:** 2026-08-08 · **Status:** accepted

**Context.** The rally signal is pivoting toward ball net-crossings (EXPERIMENTS.md 2026-08-08). Ball tracking is the hard part — small, fast, and prone to an indoor "smear" (PRD §6) — which raises the question of whether a hardware upgrade (higher-fps/higher-res camera, or more compute) is needed. Jumping to hardware before proving the mechanism in software risks optimizing for an approach that hasn't been shown to work.

**Decision.** Before any hardware spend, prove the net-crossing count in software:
- **The requirement is coarser than full ball tracking** — count net-side↔far-side sign changes from intermittent/noisy detections, not a complete trajectory. Missing frames are tolerable if enough of the arc is caught.
- **Fix the free lever first — lighting.** Indoor smear (§6) is the root cause; test on daylight / well-lit *fixed* footage before buying anything.
- **Only if software + good lighting still fail, then hardware — and camera over compute.** Detection is capture-limited: a higher frame rate (60–120 fps), faster shutter, and higher resolution make a fast ball detectable far more than raw compute does. Dense per-frame ball-detection *compute* is a deployment-scale concern (STRATEGY), not a prototype blocker (it's just slow on the M2, not impossible).

**Consequences.** Avoids premature hardware optimization for an unproven mechanism and keeps the prototype cheap (current camera + better lighting). Records the hardware priority order if it does become necessary: **camera capture quality (fps/shutter/res) first, compute later.** If the target domain is indoor casual venues, camera spec becomes a real product-design lever — but informed by the prototype, not before it.

---

## ADR-039 — Frozen v0 (player) baseline + additive v1 (ball) challenger, compared by the harness

**Date:** 2026-08-09 · **Status:** accepted (v1 direction proposed, pending clean-footage validation)

**Context.** The 2026-08-08 real-footage read (confounded by camera zoom) suggested player activity can't separate casual rallies from active dead-time, pointing at **ball net-crossings** as the rally signal — which would invert ADR-026/028 (player-primary). But the player approach was never *fairly* tested (the footage was compromised), so it must not be discarded.

**Decision.** Keep two approaches side by side, compared by the eval harness against the same labels — non-destructive:
- **v0 (player, frozen baseline):** player detection → court coords → activity markers (`events.py` motion/kitchen) → `segment.py` → `rallies.json`. This *is* ADR-026/028. Left intact; not altered.
- **v1 (ball, additive challenger):** ball detection → net-crossing count → `segment.py` → `rallies.json`. New modules. Uses the **exchange-based rally definition** (a rally = a continuous ball-in-play exchange with ≥ N net crossings, ≥ min duration; the crossing count doubles as the ranking score).
- Both emit the **same `rallies.json` schema** and feed the **same signal-agnostic segmenter**; the harness scores both → a direct v0-vs-v1 number.

**Consequences.** ADR-026/028 are **not revoked** — they define v0. v1 is a proposed challenger; **clean-footage evidence decides primacy** — v1 may supersede v0, v0 may win on clean daylight competitive footage, or fusion may beat both (ADR-022). No work is thrown away. The full v0 loop (tracks → activity → `segment.py` → `rallies.json` → harness) is proven end-to-end. Firming v1 as primary would be an approach-level decision warranting adversarial review.

---

## ADR-040 — Fine-tuning path: yolov8n on own footage → Jetson TensorRT

**Date:** 2026-08-11 · **Status:** accepted (post-demo; not built now)

**Context.** The generic yolov8x "sports ball" detector works well enough for the demo but has two production blockers: (1) too slow for real-time on Jetson Orin (yolov8x ~1 TFLOP/frame); (2) occasional false positives (ceiling lights, heads at low confidence) that the tracker suppresses but doesn't eliminate. Alternative detectors surveyed (PikleYOLO, TrackNet badminton, AndrewDettor) all have blockers on macOS — see EXPERIMENTS.md 2026-08-11.

**Decision.** Fine-tune yolov8n (tiny model, 6 MB) on our own fixed-mount pickleball footage:
- **Dataset:** 1500–2000 labeled frames, sampled at 1 fps across 4–6 sessions. Variety (lighting, players, ball speed) matters more than quantity. Hard cases (ball near net, motion blur) must be included.
- **Labeling:** Roboflow (free tier covers initial runs; no footage upload required for on-premise alternative).
- **Training:** Roboflow Train (free, 3 credits) or RunPod (~$0.10–0.30/run on RTX 3090).
- **Export:** TensorRT `.engine` file exported on the Jetson Orin itself (not on the training machine — Ada GPU TensorRT ≠ Jetson TensorRT CUDA version).
- **Integration:** single `--weights best.pt` flag in `src/cut.py`; no other pipeline changes.

**Consequences.** Unlocks real-time inference on Jetson Orin and near-zero false positives on our specific court. The blocker is clean fixed-mount footage — handheld/zoomed footage produces a model that learns bad camera habits. Do not attempt until a permanent camera mount is installed. AndrewDettor TrackNet-Pickleball is worth re-testing on Jetson (CUDA available) before committing to a full labeling effort — it may already work.

---

## ADR-041 — Interactive net picker as default calibration; --net-y for reuse

**Date:** 2026-08-11 · **Status:** accepted

**Context.** The calibration JSON (`--calib`) approach requires running a separate calibration tool and clicking multiple court landmarks — overkill for a handheld demo. The Hough-line auto-detection (`detect_net_y`) finds the floor service line at ~52px error rather than the net, because the net mesh creates no strong horizontal edge (EXPERIMENTS.md 2026-08-11). A 52px error in a 1080-tall frame degrades crossing detection for shots near the net.

**Decision.** Default to `pick_net_y()`: on first run, show the first video frame in a window with a horizontal guide line that follows the mouse. One click on the net tape records the exact pixel y-coordinate and the pipeline proceeds. Subsequent runs reuse the known value via `--net-y 260` (no window). Modes in priority order:
1. `--net-y <value>` — explicit, fastest, for repeated use
2. `--calib <json>` — full court geometry, for permanent mounts
3. *(default)* — interactive picker, one click, zero setup
4. `--auto-detect` — headless Hough estimate, rough use / CI only

**Consequences.** One-time 5-second step per camera angle instead of a full calibration session. Net_y must be re-picked if the camera moves. The `--calib` path remains the right choice for a permanent fixed-mount production setup where calibration is done once and never repeated.

---

## ADR-042 — Band tuning for dink rallies; separate from fine-tuning

**Date:** 2026-08-11 · **Status:** accepted

**Context.** During a dink rally, both players are at the kitchen line and the ball stays just above the net. In image space the ball's y-position hovers within ±20px of `net_y`. With `band=0`, detection noise causes the ball to oscillate above/below `net_y` within a single shot, registering phantom crossings. If `net_y` is measured slightly low (ball never clearly crosses to the "far" side), the rally is missed entirely.

**Decision.** Tune `--band` empirically per camera angle; it is not a model parameter. Run the pipeline at band=0, 15, 30 on a known dink-heavy clip and compare crossing counts to ground truth. Pick the band that suppresses noise without dropping real crossings. Expected range: 15–30px for a behind-baseline 1080p view.

This is explicitly **not** a fine-tuning concern — even a perfect ball detector needs the right band, because band encodes court geometry (how much y-range the net zone occupies in pixels at this camera angle), not detection quality. Fine-tuning improves detection confidence; band corrects the geometry.

**Tuning order:** net_y → band → fine-tune model → recheck band (usually stable).

**Consequences.** Band is a per-venue, per-mount constant once tuned. Document it alongside `net_y` when a permanent mount is installed.

---

## ADR-043 — Cloud-hybrid architecture: N100 edge box + RunPod cloud GPU

**Date:** 2026-08-12 · **Status:** accepted (post-prototype; not built now)

**Context.** The laptop-only pipeline processes a 13-min clip in ~14–28 min (1.7× faster with CoreML). A venue-scale deployment needs to process a 2-hour session and deliver results within ~30–60 minutes of the session ending. A discussion evaluated: (1) all-local on Mac mini / Jetson, (2) N100 mini PC + cloud GPU for detection, (3) full cloud.

**Decision.** N100 edge + cloud GPU as the production POC shape:

- N100 mini PC (local, ~$150–300): captures full-res → encodes **720p 2 Mbps proxy** (~90 MB / 60 min) → uploads to RunPod serverless
- RunPod GPU worker (~$0.34/hr): runs yolov8x detection on proxy → returns timestamps JSON only
- N100: cuts full-res local footage using returned timestamps → uploads highlight to S3 → delivers via LINE Messaging API

The **proxy video trick** is the key: send 720p for detection instead of full-res (~750 MB / hr), cutting upload volume ~8×. Timestamps apply to the locally-held full-res copy for cutting.

**Consequences.** Raw footage never leaves the building (privacy preserved). Key risk: measure venue upstream bandwidth before committing — at 2 Mbps required upload, a 50 Mbps venue link supports ~25 courts in parallel. RunPod cost ≈ $0.011/session at prototype scale. For the current POC, the MacBook with CoreML (ADR-044) is used; N100+cloud is the production direction. Ties to ADR-012, ADR-024, ADR-013.

**Update (2026-08-26): the direct-upload-to-serverless mechanism above doesn't fit RunPod's real, documented limits — this was written in 2026-08-12 without checking the API constraints it depends on.** RunPod Serverless caps request payloads at **10MB for `/run` (async) and 20MB for `/runsync` (sync)** (RunPod docs: `serverless/endpoints/operation-reference`, `serverless/workers/handler-functions`, checked 2026-08-26). The ~90MB/60min proxy figure above is 4.5–9× over both limits — a direct single-payload upload of an hour's proxy was never going to work as specified, independent of whether delivery is batch or chunked (`ADR-066`). Even a single 10-minute rolling chunk at the same proxy bitrate (~15MB) is marginal — over `/run`'s limit, under `/runsync`'s — not a safe assumption without testing.

**The fix is to land the proxy in storage first and pass the worker a reference, not the file itself — twice-corrected same day on *which* storage.** Two independent things were being conflated:

1. **RunPod's own built-in S3-compatible gateway** (`docs.runpod.io/storage/s3-api`) is a platform feature scoped entirely to RunPod's own Network Volumes — it lets an S3-compatible client (`aws s3 cp`, boto3, etc.) read/write RunPod's *own* volume storage (mounted at `/runpod-volume` on the worker) using RunPod-issued credentials. It has **no connection to any external S3-compatible provider** — RunPod's docs never mention Cloudflare R2 and confirm no platform-level integration with one. Confirmed directly against RunPod's docs page, not assumed.
2. **That does not mean external S3-compatible storage (Cloudflare R2) can't be used — it means it isn't a RunPod platform feature, it's just normal outbound networking.** A RunPod Pod or Serverless worker is a container with outbound internet access; code running inside it (the worker's own Python handler) can call R2's standard S3 API directly — `boto3.client("s3", endpoint_url="https://<ACCOUNT_ID>.r2.cloudflarestorage.com", region_name="auto", ...)` — with R2's own credentials, no RunPod involvement or integration required. Confirmed against Cloudflare's own R2 API docs (`developers.cloudflare.com/r2/api/s3/api/`): that endpoint format and `region_name="auto"` are real, and R2's S3 API works from any server with outbound internet, no platform-specific requirement.

**Both are real, viable options for the input side — this is a design choice, not a "does it work" question:**

| | RunPod Network Volume | Cloudflare R2 (via boto3 in the worker) |
|---|---|---|
| Mechanism | Platform feature; file appears mounted at `/runpod-volume` | Worker code explicitly fetches the file over HTTPS at job start |
| Tied to RunPod infra/region | Yes — specific datacenters, RunPod pricing (~$0.07/GB/month) | No — independent Cloudflare account |
| Covers output/delivery too (highlight → end user) | No — Network Volumes only exist inside RunPod | Yes — same account, same zero-egress pricing, unifies input and output storage |

R2 is the more architecturally attractive of the two for this project specifically, since it solves both legs (proxy in, highlight out) from one account instead of splitting storage between RunPod's Network Volume and a separate delivery bucket (`ADR-043`'s original plan used plain S3 for that leg).

**Tested end-to-end, 2026-08-26: R2-via-boto3 works.** `boto3` `list_buckets`/`put_object`/`get_object` all succeeded against a real R2 bucket (`test-ingest-runpod`) with real credentials — not simulated. One real, previously-undocumented gotcha found in the process: **Cloudflare does not provision the account's S3-compatible endpoint (`https://<ACCOUNT_ID>.r2.cloudflarestorage.com`) until at least one bucket exists in the account.** With zero buckets, the endpoint fails at the TLS handshake stage — before credentials are even checked, so it looks like a broken account/credential/network problem rather than what it is. Confirmed by direct A/B: identical connection attempt failed consistently (TLS 1.2, TLS 1.3, with/without ALPN, `curl` and raw `openssl s_client` all failed identically) before a bucket existed, and succeeded immediately once one did. Worth remembering — this will look like a mysterious connectivity failure to anyone setting up R2 fresh.

**Second half tested, same day: confirmed from RunPod's actual network, not just the local dev machine.** Spun up a real RunPod pod (`runpod/pytorch` image, RTX 4090, EU-CZ-1 — a CPU-only pod was tried first and cheaper, but hit repeated "no instances available" capacity errors both resuming an old pod and creating a fresh one; the GPU pod succeeded on the first attempt), SSH'd in, installed `boto3`, and ran the identical `list_buckets`/`get_object` calls against the same R2 bucket and object created earlier from the local machine. **Both succeeded, confirming the full input-side path end-to-end: a worker running on RunPod's network can reach R2 directly, with no special network configuration needed.** Pod terminated immediately after (~5 min runtime, real cost ~$0.06). One implementation note for whoever builds this for real: a generic `ubuntu:22.04` image has no SSH daemon running by default — RunPod's own maintained images (like `runpod/pytorch:*`) bundle the startup script that reads `PUBLIC_KEY` and starts `sshd` automatically; a bare Docker Hub image needs that done manually via `dockerStartCmd`.

**Input-side POC is now fully validated, not just designed:** N100/capture device → R2 (tested from a local machine, standing in for the N100) → RunPod worker (tested on RunPod's real network) all confirmed working with real credentials, real network paths, real cloud resources. What's left for a real implementation, not tested here: actually compressing/chunking real footage into the proxy format, wiring this into `pod_infer.py`, and the output/delivery leg (finished highlight → end user).

**Full `cloud_pipeline` run end-to-end for real, 2026-08-26 — the last untested piece (`pod_infer.py` inference on a pod) is no longer untested.** Deliberately fresh test, no reused artifacts: a random 5-minute clip cut from raw, previously-untouched footage (`videos/raw/brickwall-SEMI.mp4`), a *live* calibration the operator clicked through in a real browser session (RMSE 0.166ft), then one real `run_cloud_job.py` invocation start to finish. **Exit code 0.** 13 candidate rally segments detected, both reels produced and playable (209.5s each), ranking scores in the same 0.011–0.850 range as every other scored video this project has produced. Top-ranked clip sent to the operator directly for a real playback check — this project's own rule that a numbers-only verdict isn't sufficient (`feedback_video_review_method`) still applies; mechanical success is confirmed, detection *quality* on this clip is not yet operator-confirmed.

One real, measured number worth recording honestly: **pod inference ran at 29.4fps, wall-clock ratio ~1.02× (essentially real-time)** — slower than the local RTX 2000 Ada's measured 36.2fps for the same masked config (`ADR-065`), despite being pinned to the identical GPU model specifically for consistency. Likely network/disk I/O overhead on the pod, not a GPU difference — not yet root-caused. Neither the local nor the cloud route currently clears `PRD.md`'s ≤0.5× wall-clock target; the cloud route is currently the slower of the two, not faster.

**Root-caused, 2026-08-26 (same day): it's the CPU-side preprocessing, not the GPU and not I/O.** Built a stage-by-stage profiler (`scripts/profile_pod_infer.py`) that times each of decode / preprocess (`cv2.resize` + numpy reshape) / GPU inference / postprocess (contour-finding) separately, over an identical 300-trio budget, run once locally and once on a real freshly-created pod (same GPU type, same weights, same calibration, same clip). Result:

| stage | local (ms/trio) | pod (ms/trio) | delta |
|---|---|---|---|
| decode | 5.53 | 3.33 | pod faster |
| preprocess | 37.25 | 53.29 | **pod +43% slower** |
| GPU infer | 38.28 | 37.76 | ~identical (−1.4%) |
| postprocess | 0.80 | 0.41 | pod faster |

Overall: local 36.6fps, pod 31.6fps on this run (close to the original 29.4fps; some run-to-run variance expected at n=300). **The earlier "likely network/disk I/O" guess was wrong** — decode is a small fraction of the loop on both sides (3–7%) and isn't the bottleneck either way. **GPU inference time is essentially identical**, which is exactly what pinning the pod to the same GPU model (`runpod_pod.py`'s `DEFAULT_GPU_TYPES`) was for — confirms that guarantee holds, not just in theory. The entire gap is in single-threaded CPU preprocessing being slower per-call on the pod, despite the pod nominally having far more vCPUs (48 vs. the local workstation's 16 — `nproc`/`free -h` queried live on the pod). vCPU *count* doesn't help here because `prep3()` runs on one core; what matters is per-core throughput, and RunPod's shared/virtualized hosts give a weaker single-core than a dedicated local workstation. Not investigated further (SIMD/AVX build flags in the `opencv-python-headless` pip wheel vs. local's install, specific host CPU model) — the mechanism is already clear enough to act on if the gap needs closing: the fix, if pursued, is parallelizing or GPU-offloading `prep3()`'s per-frame resize (real headroom exists — the pod's 47 idle vCPUs and the GPU's own idle time between calls), not chasing GPU/network explanations that this measurement rules out. Not pursued today — recorded so the wrong guess doesn't get re-derived.

**Fixed, same day: overlap decode+preprocess with GPU inference on a background thread.** `pod_infer.py`'s loop was fully serial — decode → resize → GPU infer → postprocess, one after another — even though the CPU sits idle during the GPU call and the GPU sits idle during resize. Added a producer thread that decodes+preprocesses the *next* trio into a small bounded queue (`maxsize=3`) while the main thread runs `infer()` on the *current* one; only the scheduling changed, not the per-frame arithmetic or read order. **Verified byte-identical output** against the pre-change version on a 730-frame clip (both locally and on a real pod — `diff` clean both times, including the non-multiple-of-3 tail-frame case), so this is a scheduling fix with zero detection-quality risk, not a numerical change.

**Measured result, real pod, same clip/weights/calib:** **29.4fps → 74.8fps**, a 2.5× win (local also improved, 36.4fps → 66.8fps). Both numbers came from real runs, not the profiler's stage-time arithmetic — the ~56fps ceiling projected from the profiler's separately-timed stages undersold it; some of that is likely the profiler's own per-stage `time.time()` calls adding overhead the real loop doesn't pay, some is ordinary pod-to-pod hardware variance (a different physical host than the profiling run, as usual on RunPod's shared fleet).

**Revisits the rolling-10-min-chunk cadence math from earlier today:** a real 10-min/18,000-frame chunk now takes 18000/74.8 ≈ 241s (~4 min) of inference instead of ~612s (~10.2 min) — comfortably under the 600s chunk budget even before subtracting the ~86s pod-setup tax, which remains unaddressed (still a separate, real question — see the pre-baked-image discussion, not yet built).

**The pre-baked pod image: cold start is real and bad, but caching turned out to be real too — corrected twice in one afternoon, both times by measuring rather than assuming.** Built `cloud_pipeline/Dockerfile` (base image plus `boto3`/`opencv-python-headless`/`tensorflow[and-cuda]==2.15.1`, matching `POD_SETUP_CMD` exactly), pushed to Docker Hub as `tonychu805/pic-vision-tracknet:tf215-cuda118`. The image came out to **17.7GB, with a 4.76GB new layer** (`tensorflow[and-cuda]`'s bundled NVIDIA CUDA wheels) on top of the base — bigger than assumed going in.

*First measurement (one cold pod):* pod-create → ready-to-run-python-imports took **113.4s** — worse than the ~79.6s baseline (13.1s boot + 66.5s `pip install`). Read initially as "reverted, doesn't work."

*Second measurement (5 more pods, created with ~20s gaps over ~10-15 minutes):* every single one beat the cold number, and four of five beat baseline outright: **70.1s, 20.4s, 39.5s, 75.9s, 57.7s — average ~52.7s, a real ~34% win over the ~79.6s baseline.** The image gets cached somewhere in RunPod's pool after the first pull (which physical host, or how broadly, wasn't determined), and subsequent pod creations benefit — this isn't same-host luck on one lucky draw, it held across 5 separate creations.

**Net read:** the ~86s tax is real and payable-once via this image, but the picture isn't fully closed — all 6 measurements happened within about 15 minutes of each other, so whether the cache survives the longer, more realistic gaps between real production jobs (hours, not minutes) is untested. `DEFAULT_IMAGE` has not been switched yet pending that check. Do not re-read the first (113.4s) number in isolation as "doesn't work" — and do not treat the second batch as proof it always works either; both were measured, and the honest state is "promising, gap-persistence unverified."

---

## ADR-044 — CoreML export of yolov8x at imgsz=1280 for Apple Neural Engine inference

**Date:** 2026-08-12 · **Status:** accepted

**Context.** PyTorch/Metal inference of yolov8x at imgsz=1280 measured ~365 ms/frame on the MacBook Air M2, making a 10-fps scan of a 13-min clip take ~70 min — too slow for iteration.

**Decision.** Export yolov8x to CoreML (`yolov8x.mlpackage`, 130.5 MB, in project root) at `imgsz=1280` for the Apple Neural Engine. Pass `--weights yolov8x.mlpackage` in pipeline calls.

**Measured result:** 216 ms/frame ANE vs 365 ms/frame CPU — **1.7× faster**. Export command: `YOLO("yolov8x.pt").export(format="coreml", imgsz=1280, nms=True)`. `imgsz` must match at export and inference (`RuntimeError` otherwise — re-export at 1280 if mismatched). Ties to ADR-023 (ONNX is still the cross-platform canonical format; CoreML is the Apple deployment target).

---

## ADR-045 — `max_ball_px` filter is mandatory; eliminates player-body false positives

**Date:** 2026-08-12 · **Status:** accepted

**Context.** With `conf=0.10` and no size filter, YOLO's `sports ball` class latched onto player bodies (heads/torsos score plausibly at low confidence). The tracker followed players instead of the ball, producing false rallies with no real net crossings. All "players walking, no ball" clips traced to this root cause.

**Decision.** Always set `--max-ball-px` to the measured ball pixel size for the camera geometry. For behind-baseline 1080p handheld footage: ball = 10–21 px; player bodies = 30–60 px → use `--max-ball-px 25`. Also raise `conf` to 0.25 (from 0.10) to suppress the worst player-body hits before the size filter.

**Best working params as of 2026-08-12** (IMG_7652.MOV, 13-min handheld test):
`--conf 0.25 --max-ball-px 25 --band 10 --max-jump 100 --gap-sec 2.0 --sample-fps 10 --weights yolov8x.mlpackage`

**Consequences.** `max_ball_px` is camera-geometry-specific — measure the ball in pixels at the expected distance before setting. `band=10` (±10 px around net_y) suppresses crossing noise from camera jitter; `max-jump=100` rejects position jumps from camera movement. Both work alongside `max_ball_px`. On clean fixed-mount footage with a closer camera, the ball appears larger — increase `max_ball_px` accordingly (e.g. 30–35 px).

---

## ADR-046 — Retire YOLO pipeline; TrackNet/RunPod is the active ball-detection path

**Date:** 2026-08-12 · **Status:** accepted

**Context.** On the rally #3 benchmark window (58–77.5s, IMG_7652.MOV) TrackNet with badminton-trained weights found 25 net-crossings vs YOLO's 5 (5×). On a full 9.4-minute video (IMG_7655.MOV, 36 labeled rallies), TrackNet found 7 matched segments with 5/7 usable after qualitative review. The 5× crossing-count gap on the same footage is too large to bridge with YOLO tuning. TrackNet is CUDA-only and cannot run on the Mac or N100, making RunPod GPU the natural backend — consistent with ADR-043.

**Decision.** Archive the YOLO ball-detection pipeline and make TrackNet/RunPod the default:
- `src/pipeline.py` (YOLO orchestration), `detect_ball`/`detect_candidates` from `src/ball.py` → `archive/`
- `src/tracknet.py` (new) — parses TrackNet `predictions.csv` → rally segments, using the same backend-agnostic `crossing_times`/`cluster_crossings` from `src/ball.py`
- `scripts/pod_infer.py` (new) — runs on the RunPod GPU pod; emits `predictions.csv`
- `scripts/process_footage.py` (new) — local orchestration: `predictions.csv` + video → clips
- `src/cut.py` updated to `cut_rallies_from_predictions`; CLI takes `--predictions`
- `Makefile` gains a `process` target: `make process VIDEO=... CSV=... NET_Y=... OUT=...`

**Consequences.** Inference requires a GPU pod (RunPod, ~$0.28/hr) — no longer runs entirely local. The proxy-video trick from ADR-043 applies: upload 720p for detection, cut full-res locally. The backend-agnostic signal functions (`crossing_times`, `cluster_crossings`, `net_line_y`) are unchanged; they feed TrackNet output the same way they fed YOLO output. The YOLO archive remains recoverable if a future local-inference path (fine-tuned yolov8n on Jetson, ADR-040) outperforms TrackNet on clean footage.

---

## ADR-047 — Ball-first (TrackNet on full video) is the primary segmentation path; player-tracking deferred

**Date:** 2026-08-13 · **Status:** accepted

**Context.** STRATEGY §3 proposed **player-tracking as the foundation, with the ball as a refinement that runs only on selected clips** — justified by two assumptions: ball detection is expensive at full-session scale, and the ball is untrackable in many conditions. Recent results overturn both for our setup: TrackNet on the full video found 25 crossings vs YOLO's 5 on the rally-3 window and 5/7 usable segments on the full 9.4-min IMG_7655 (ADR-046), and cloud GPU (ADR-043/046) makes full-video ball inference cheap enough (~$0.28/hr) that the throughput objection no longer binds. The **built pipeline already runs ball-first on the full video**; the code and STRATEGY §3 currently disagree. This ADR reconciles them.

**Decision.** Ball net-crossing detection (**TrackNet on the full video**) is the primary and current rally-segmentation signal. The v0 player-geometry path (ADR-039; `src/players.py`, `src/events.py`) stays **frozen** — not revoked, not the spine. Player-tracking is **deferred to a later phase**, to be revisited for: (a) movement-analytics second product (STRATEGY §7–8), (b) fusion to sharpen ball-derived boundaries, or (c) a fallback if ball detection proves unreliable on clean fixed-mount footage. STRATEGY §3's "player-first, ball-on-selected-clips" is **superseded as the near-term architecture** (the strategy doc's longer-term framing still stands as an option).

**Consequences.** Full-video ball inference requires a GPU (no local-only path; ties ADR-043/046). The movement-analytics second surface is deferred along with player tracking. The frozen v0 modules stay in-tree but out of the hot path. **Revisit if** the clean-footage benchmark shows ball recall is poor precisely where player geometry would have held, or if full-video ball inference proves impractical at venue scale. Does not unfreeze v0.

---

## ADR-048 — `min_crossings=6` is the one canonical default

**Date:** 2026-08-17 · **Status:** accepted

**Context.** `min_crossings` (the number of net crossings required before a candidate cluster counts as a rally) had drifted to four different values with no single one canonical: `TECH_SPEC.md`/ADR-028 said ≥2 (courtesy-return suppression, a design-intent estimate from before any clean-footage measurement existed); `PROGRESS.md` said ~5; `src/cut.py`'s CLI default was 3; `src/tracknet.py`'s docstring claimed 3 was "validated" (true only for the IMG_7655 run under a different, since-superseded gate). A fresh session reading any one of these first would ship a different rally definition than the last.

**Decision.** `min_crossings=6` is the one canonical default, set in both `src/cut.py` and `src/tracknet.py`. It is not a re-derivation of the ADR-028 courtesy-return estimate — it is the value the 2026-08-16 `court_wedge` sweep on the 33-label IMG_7743 benchmark actually found best: precision 0.29 at recall 20/33 (61%), versus 0.12 at the old default of 3 for the same recall (verified by direct re-run 2026-08-17). See `EXPERIMENTS.md` 2026-08-16 ("capped trapezoid gate works") for the full sweep.

**Consequences.** ADR-028's ≥2 estimate is left as written (append-only) — it recorded the reasoning available at the time, before any clean footage existed to measure against. `TECH_SPEC.md` §5.3.1 now points here instead of restating a number that will drift again. Future re-tuning (e.g. once `PIC-1`'s missed-rally diagnosis or `PIC-2`'s blob-confidence filter lands) should update the default in code first and treat this ADR, not the docstrings, as the place a new value gets recorded.

---

## ADR-049 — A mid-session camera bump invalidates calibration for the rest of the recording; detect it, don't just tune around it

**Date:** 2026-08-17 · **Status:** accepted

**Context.** PIC-1 asked why 13 of 33 labelled rallies on IMG_7743 were missed under every gate shape and threshold tried. Diagnosis (`EXPERIMENTS.md` 2026-08-17) found that 11 of the 13 are not a detection problem at all: **the camera was physically bumped at t≈2859s** (47 minutes into a 67-minute single continuous recording), shifting the net's image position by ~50px. TrackNet kept finding the ball just as well after the bump (41–62% visibility, normal for this footage) — but `net_y=552`, measured once at calibration time, was wrong for the rest of the session, so real net crossings fell short of the threshold and produced almost no crossings. Confirmed by: (1) the miss pattern is a hard boundary in time, not scattered or correlated with rally style/quality; (2) zoomed frames show the net tape sitting ~50px off the calibrated line only after the bump, never before; (3) far-wall signage doesn't move between early and late frames (rules out a tilt, which would move everything), while the near-field net does (the signature of a translation); (4) patching `net_y` for the tail alone recovers recall 0.61→0.85 on the full 33-label set, with no other change.

**Decision.** Treat mid-session camera movement as an expected failure mode to detect, not an edge case to discover after the fact:
- A single calibration is only valid until something bumps the camera. For a ~1 hour continuous recording on a portable mount (not a permanently fixed installation), this is not a rare event.
- Any future capture/processing tooling should include a **calibration-drift check**: periodically (e.g. every few minutes) compare a fixed reference region (the net line, a court corner) against its calibrated position, and flag or auto-split the session when it moves beyond a small tolerance. This is the same category of tooling as the existing frame-count/decode-integrity check in `pod_infer.py` (ADR from the HEVC-corruption fix) — a cheap sanity check that turns a silent, catastrophic failure into a loud, cheap one.
- Until that tooling exists, treat **precision and recall numbers from any session as suspect if the camera might have been bumped** — check for a hard time-boundary in the miss pattern (as done here) before concluding a detection/gating parameter is the problem.

**Consequences.** This reframes the current PIC-1 recall ceiling: it is mostly a **capture robustness problem**, not a model or gating problem — no amount of `min_crossings`/`band`/`court_wedge` tuning on the existing pipeline can fix a wrong `net_y`. The recommended fix (split the session at the detected bump and re-derive calibration for each piece) is not yet built — this ADR records the decision to pursue that direction rather than continuing to tune thresholds against a partially-invalid calibration. A physically stiffer/more secure mount is also worth it independent of software, since one bump silently cost 11 of 33 rallies on this session. Does not change anything about the two remaining pre-shift misses (label#3/#19), which are the unrelated, already-known `gap_sec` boundary tradeoff.

---

## ADR-050 — A precision number is not admissible until its false positives have been reviewed at playback speed

**Date:** 2026-08-18 · **Status:** accepted

**Context.** As of 2026-08-17 the project's headline finding was that precision sat in a tight 0.25–0.29 band across three independent cameras and venues while recall varied widely (0.60–0.86), and the conclusion drawn was that precision must therefore be a property of the pipeline's gating logic rather than of any camera or calibration. That conclusion set the project's direction: stop calibrating, go fix gating.

It does not survive review. On 2026-08-18 the false positives of two videos were cut into clips and judged at real playback speed (`EXPERIMENTS.md`, 2026-08-18 entries). On `pb_draft_cup`, 8 of 15 dead-time "false positives" were real rallies the labels never recorded; the operator marked 11 more, taking the file from 7 to 18 labels. With no change to the predictions, the calibration, the config, or the scoring code, **precision moved 0.27 → 0.59**. On `brickwall` the same review moved precision 0.59 → 0.64 and revealed that 10 of its 18 false positives were *fragments sitting inside real rallies* — the detector had found the rally and split it, so each such rally was charged twice, once as a miss and once as a false positive.

Neither correction involved improving the detector. Both were corrections to how it was being measured.

**Decision.**
- **A precision figure may not be cited as evidence about the detector until the false positives behind it have been reviewed at playback speed.** Until then it is a measurement of the labels as much as of the pipeline. This extends the existing rule that a rally-vs-dead-time call requires playback (`EXPERIMENTS.md`, IMG_7744 review) from individual verdicts to aggregate metrics.
- **Detection metrics are scored against all real play, never a curated subset.** `PRD.md` §5 already required this ("measured on the complete rally list"); the 2026-08-09 habit of curating labels down to "competitive" rallies violated it and is what produced the artefact. Grade ordinary play 2 — never delete it.
- **Report false positives by kind, not as one number.** The three observed kinds have unrelated causes and unrelated fixes: *fragments* of a real rally (clustering parameter), *unlabelled real play* (labelling process), and *genuine junk* — itself two distinct things, phantom crossings from a tossed ball whose image-y crosses `net_y` without the ball crossing the net, and courtesy returns where the ball really does cross during dead time. Aggregating them hides which problem is actually being measured.
- **Raw precision is not comparable across videos of different rally density.** Use the chance-adjusted lift (`EXPERIMENTS.md`, 2026-08-18) when comparing.

**Consequences.** The "precision is pinned at 0.25–0.29" finding is withdrawn as evidence of a pipeline ceiling; both re-measured videos now sit near 0.6. IMG_7743 (0.29) and IMG_7744 (0.25) have **not** been re-reviewed and must not be cited as support for a ceiling until they have — that review is the top priority in `PROGRESS.md`. This does not claim the pipeline is good enough: 7 confirmed junk segments on pb_draft_cup and 2 on brickwall are real errors, and the two junk mechanisms above remain unfixed, with the courtesy return being the same problem named as a risk in `PRD.md` §0.6 and still open as PIC-31. **This ADR records a conclusion reached within a single session, from one operator's relabelling pass, and has not been through adversarial review** — the direction it reverses was itself held with confidence one day earlier.

---


## ADR-051 — ADR-050's label-artefact finding is confirmed on all four scored cameras; treat the pre-2026-08-18 precision ceiling as fully retracted

**Date:** 2026-08-19 · **Status:** accepted

**Context.** ADR-050 (2026-08-18) withdrew the "precision pinned at 0.25–0.29 across cameras" finding after playback review moved `pb_draft_cup` 0.27→0.59 and `brickwall` 0.59→0.64, but explicitly left `IMG_7743` (0.29) and `IMG_7744` (0.25) unreviewed — "the last two data points holding up the ceiling claim" — and named re-reviewing them the top priority in `PROGRESS.md`.

That review is now done (`EXPERIMENTS.md`, 2026-08-19). All 78 outstanding detector-only candidates across IMG_7743 pre-bump, IMG_7743 post-bump, and IMG_7744 were graded at playback speed; labels grew from 33→53 (IMG_7743) and 10→20 (IMG_7744). Rescoring at the shipped config moved precision 0.29→0.44 (IMG_7743 combined) and 0.25→0.54 (IMG_7744) — same direction, same order of magnitude, as the two videos ADR-050 already covered. No exception showed up on a fourth camera the way it might have if the earlier finding had been specific to `pb_draft_cup`/`brickwall`'s rally density or format.

**Decision.** The pre-2026-08-18 "precision ceiling" reading is fully retracted, not just withdrawn pending more evidence — it has now been checked on every camera this project has scored, and failed to hold on every one of them. Future work should not treat 0.25–0.29 as any kind of floor or reference point for this pipeline's precision; the actual, still-open precision numbers are the post-review ones in `CHECKLIST.md`'s four-camera table (0.44–0.64 as of this ADR).

This does not mean precision is solved. ADR-050's three separated failure modes (fragmentation, label incompleteness, genuine junk) still apply, and only `brickwall` has had its false positives broken down by kind. Citing today's 0.44/0.54 figures as clean detector-quality numbers would repeat the same mistake ADR-050 corrected, one level down — a fraction of the remaining false positives on IMG_7743/7744/pb_draft_cup are very likely fragments of rallies the same review pass just recovered, not new junk. That anatomy is unbuilt and is the next thing to do before treating these numbers as a ceiling either.

**Consequences.** ADR-050's follow-up #1 (re-review IMG_7743/IMG_7744) is closed. Follow-up #2 (chance-adjusted lift recompute for `pb_draft_cup`) and follow-up #3 (adversarial review of the label-artefact conclusion) remain open, and #3 now covers a conclusion reached across four videos and two sessions rather than one. `label_web.py` gained a reusable capability from this work — in-place boundary correction in GRADE mode, preserving the original detector timestamp as `detector_start`/`detector_end` — that should be the default tool for any future gap-review pass, not just this one.

---

## ADR-052 — Eval-set roles are locked; IMG_7743 is `eval` and may never again be used to pick a parameter

**Date:** 2026-08-19 · **Status:** accepted

**Context.** `LABELING.md` has documented a `dev`/`eval` session-role system since early in the project, and `TECH_SPEC.md`'s repo layout has referenced a `sessions.jsonl` file to hold the assignments — but `sessions.jsonl` was never actually created, and no session ever received a role. PIC-17 (filed 2026-08-16) named the consequence directly: every parameter this project has tuned — `min_crossings=6`, `gap_sec=3.0`, `court_wedge`'s cap/spread constants, and, before this ADR, PIC-33's adaptive-`gap_sec` search — was tuned and evaluated on the same labelled footage. The Phase 0 gate flagged this as a prerequisite before any tuning run; tuning happened anyway, including a 156-parameter sweep the day the issue was filed, and roughly 100 more parameter combinations in this session's own `gap_sec`/duration-threshold work before this was caught.

**Decision.** `sessions.jsonl` now exists and is populated. `IMG_7743` is `eval` — locked. No future sweep, threshold search, or parameter fit may use its labels to choose a value; it may only be used to report a final number, at most once per phase, per the rule already written (but unenforced) in `LABELING.md`. `brickwall`, `pb_draft_cup`, and `IMG_7744` are `dev` — each is the only labelled example of its rally-length/format regime (tournament doubles, singles, casual doubles-with-adjacent-court-noise), so none of them can be spared for `eval` without losing coverage of that regime entirely; `IMG_7743`'s regime (casual doubles) is the one already duplicated by `IMG_7744`, which is why it is the video that can be locked.

**Consequences.** This is enforced by convention, not by code — there is no technical barrier stopping a future session from scoring against IMG_7743 mid-sweep, only the rule now written in `LABELING.md` and `sessions.jsonl`. The currently shipped `min_crossings`, `gap_sec`, and `court_wedge` constants were tuned against IMG_7743 before this lock existed and cannot be retroactively cleaned; they carry a real, unquantified amount of overfitting to the video that just became `eval`. Re-deriving them against `dev` only is tracked as PIC-43 and is the actual test of whether this project's headline numbers survive honest validation — this ADR fixes the process, not the numbers. The one existing example of a parameter search already following this discipline by construction (PIC-33's `adaptive_gap`, tuned on `dev`, checked flat on what is now `eval`) is recorded in `EXPERIMENTS.md` as the template for what PIC-43 and any future tuning work should look like.

---

## ADR-053 — ADR-051's replacement precision figures are provisional; the retraction stands, the numbers don't

**Date:** 2026-08-20 · **Status:** accepted

**Context.** PIC-39 ran a formal adversarial review (skeptic, red-team, simplifier — three independent agents, majority-survives rule) against ADR-050/051's conclusion that the 2026-08-17 "0.25–0.29 precision ceiling" was a label-completeness artefact, confirmed by relabelling passes moving precision to 0.44/0.54/0.59/0.64 across the four scored videos. **Result: 0/3 survived.** All three lenses independently converged on the same structural problem, verified against the actual repo and label files, not just argued abstractly:

- `scripts/review_gaps.py`'s extract→grade→merge process seeds every candidate from the detector's own false positives and only ever *adds* labels. Precision under this process is mathematically guaranteed to rise regardless of whether the added labels are truly complete — it can convert a false positive into a true positive, never the reverse, and can never discover a rally the detector missed entirely.
- Measured directly: precision on IMG_7743 pre-bump moves 0.290 (independent labels) → 0.449 (human boundary-corrected while watching the detector's own clip) → 0.536 (raw detector boundaries) — a clean anchoring gradient. Boundaries drawn while watching a looping clip the detector proposed drift toward the detector's own guess.
- The project's own required chance-adjusted-lift check (ADR-050's fourth decision bullet, left undone until this review) goes the *wrong direction* on 2 of 3 videos when actually run — the detector's power relative to chance did not improve.
- The one label set on this project made independently of detector output (PIC-6's blind pass, 2026-08-20) scores the shipped detector *worse* (0.14) on its window than the retracted 0.25–0.29 band it was meant to move past — the opposite of what ADR-051 predicts.
- A label file is already silently corrupted (duplicate/nested ground truth on IMG_7744, `merge`'s IoU≥0.3 dedup missed a nested interval), and `review_gaps.py merge` writes over committed ground truth in place with no backup, temp file, or guard against an empty/mistyped `--gaps` argument.

**What survives.** The *retraction* half of ADR-050 — "0.25–0.29 must not be cited as a hard property of the detector" — holds independently of any of the above: the 2026-08-09 curated-label habit is separately documented and violates `PRD.md` §5, and brickwall's fragment finding (false positives sitting inside already-labelled rallies) is provable from existing labels with zero relabelling. What does **not** survive is treating 0.44/0.54/0.59/0.64 as established detector-quality numbers, or treating four relabelled videos as four independent confirmations — all four passes were made by one labeller whose own standard for "what counts as a rally" was still settling during this exact window (PIC-6's correction), so they are closer to one observation counted four times than four independent checks.

**Decision.** ADR-051's replacement precision figures are downgraded from confirmed to **provisional**. `CHECKLIST.md` and `PROGRESS.md` are annotated accordingly. Everything scored against these labels since — PIC-37's false-positive anatomy, PIC-33's `adaptive_gap` selection, PIC-43's `min_crossings` re-derivation — inherits this uncertainty; their *relative* comparisons (dev vs. eval, config A vs. config B) are on firmer ground than their absolute precision figures, since both sides of each comparison share the same contaminated labels, but none of it should be cited as settled.

**Consequences.** Further detection-precision tuning (the remaining pieces of PIC-40, PIC-43, PIC-38) is deprioritized pending real revalidation — a blind relabel of a video *not* already contaminated by multiple review passes (brickwall or pb_draft_cup, not IMG_7743, which ADR-052 already locked and PIC-6/PIC-44 have since touched twice more), made without seeing any detector output, is the concrete next check named by the reviewers and not yet done. Separately, and more fundamentally: this reopens the question of what the project should actually be optimizing. Detection precision was never the product goal — a highlight reel is — and the project has no written definition of "highlight-worthy" at all, only a `quality` grade assigned by feel. That gap (PIC-7, and a new consistency check on quality grading itself, mirroring PIC-6) is now higher priority than further detection-precision cleanup.

---

## ADR-054 — Raw net-crossing count is not a valid shot-count/intensity/ranking proxy; only crossing *bursts* remain trustworthy

**Date:** 2026-08-21 · **Status:** accepted

**Context.** `EXPERIMENTS.md`'s "Kitchen dinks double-count net crossings" entry (2026-08-21) found that `crossing_times` (`src/ball.py`) — a 1D signal comparing the ball's image-y to one pixel row, `net_y` — cannot distinguish two separately hit shots from one shot's rise over the net and fall into the kitchen on the same pass. Checked against real TrackNetV3-tracked data from two brickwall rallies: 13% of the 193 consecutive-crossing gaps were under 150ms, not achievable as two independently hit shots, with another 18% in a band a fast dink exchange could equally explain. This surfaced while building a highlight reel that ranked candidate segments by raw crossing count (`src/cut.py`'s only existing proxy score) — the reel's top picks turned out to be two extended kitchen-dink exchanges rather than a spread of rally types, consistent with the count being structurally inflated by kitchen-heavy play.

A fixed-time debounce (merging crossings within some short window into one) was considered and rejected: a real fast exchange with a floor bounce before the return can legitimately produce genuine crossings faster than any safe debounce window allows, so a timing-only merge would just trade one systematic miscount (kitchen double-counting) for another (undercounting genuinely fast real exchanges).

**Decision.** Raw net-crossing count is not to be used, on its own, as a proxy for shot count, rally intensity/duration, or a ranking signal — this affects `PIC-46`'s classifier (`crossing_rate` feature), `PIC-14`'s stalled ranking-signal question, and any future crossing-count-based selection, including the ad hoc ranking used in the 2026-08-21 TrackNetV3 highlight reel. Crossing **bursts** (a dense cluster of crossings) remain a valid real-activity signal — `cluster_crossings`'s existing role as a rally-presence detector is unaffected — the count *within* a burst is what's unreliable.

**Consequences.** This is a property of the `crossing_times`/`cluster_crossings` pipeline's definition itself — any detector feeding it (k14, TrackNetV3, or a future replacement) inherits the same defect, so switching detectors cannot fix it. No fix has been attempted; the plausible direction is a trajectory-shape check (does the ball's arc actually go back over net height on the second crossing, vs. stay low — a same-shot double-crossing signature) rather than any timing threshold. Filed as Linear PIC-48, cross-referenced from PIC-42 (signals beyond ball-crossing), PIC-46 (classifier features), PIC-14 (ranking signals), and PIC-31/PIC-34 (the two other, previously-documented crossing-signal failure modes this one is distinct from — dead-time crossings and phantom crossings, respectively). Sample is single-video, two-rally (both brickwall, both TrackNetV3) — worth confirming the same gap-clustering shows up on a non-kitchen-heavy rally and on k14 predictions before treating the *magnitude* (not just the mechanism) as general.

---

## ADR-055 — Near-team pre-serve stillness (brickwall-derived) does not transfer to IMG_7743; not adopted as a `PIC-31` signal in its current fixed-threshold form

**Date:** 2026-08-23 · **Status:** accepted

**Context.** `EXPERIMENTS.md`'s 2026-08-22 stillness entry found near-team ankle speed drops to 7–19% of the surrounding dead-time baseline in the last second before serve, on all 3 checkable `brickwall_30fps.mp4` boundaries — proposed as a `PIC-31` fusion signal (stillness-dip gates a crossing burst) precisely because it's independent of the ball-crossing signal every prior `PIC-31` candidate was derived from. The entry's own stated next step — check this ratio at `PIC-37`'s already-known, unambiguous real dead-time-crossing false positives (`IMG_7743` post-bump, all 12 confirmed by trajectory-plot read) — was run today (`EXPERIMENTS.md`, 2026-08-23) using a new reusable script, `scripts/pose_stillness.py`.

**Decision.** The raw stillness ratio, with a brickwall-derived threshold (real serves <0.2), is **not adopted** as a `PIC-31` signal in that form. Two results, together, are why this is a rejection and not just an inconclusive data point: (1) IMG_7743's *own real rally starts* (n=6) don't show the dip either — mean ratio 1.36, none under 0.2 — so a brickwall-calibrated cutoff would reject 100% of real rallies on this video before precision is even measured; (2) IMG_7743's 12 confirmed dead-time false positives (n=11 valid) don't separate from IMG_7743's real rallies either — mean 0.94 vs. 1.36, medians 0.67 vs. 1.42, same range, wrong direction if anything. The brickwall dip is real (script reimplementation reproduced it: 0.10/0.19/0.15 vs. the original 0.08/0.17/0.07) but is evidently a property of that footage or format — long-rally tournament doubles with a formal serve pause — not a general pre-serve behavior.

**Consequences.** `PIC-31` stays open; this closes out the simplest form of candidate #3 (raw near-team stillness, fixed threshold) the same way ADR from 2026-08-19 closed out candidate #1 (duration/rate threshold) — a real, promising-looking signal that did not survive its first real test against known false positives, rather than something to keep assuming true in later work. Two things are explicitly *not* ruled out by this: a self-calibrated per-video version of the same ratio (the `adaptive_gap_sec` playbook — untested), and the sibling position/timing signals from the 2026-08-22 "baseline vs. kitchen-line" entry, which have not yet been checked against these same false positives. Whether IMG_7743's rallies genuinely lack a ritual pre-serve pause, or the label `start` timestamp lands after it, is unresolved — needs real playback of 2–3 IMG_7743 serves, not more tracking data, to settle (`CLAUDE.md`'s video-review-method rule). Recommend recording this against Linear `PIC-31`. **Superseded in part by ADR-056** — two of the false positives this ADR's negative-class sample rests on turned out, on real playback, not to be dead time at all.

---

## ADR-056 — PIC-37's "confirmed by trajectory-plot read" false-positive list is not verified ground truth; ADR-055's confidence is downgraded pending playback re-check

**Date:** 2026-08-23 · **Status:** accepted

**Context.** While setting up real playback of IMG_7743 real-rally starts (ADR-055's own unresolved follow-up), two of PIC-37's 12 "confirmed by trajectory-plot read, no ambiguity" `IMG_7743` post-bump dead-time false positives (107.73s, 199.40s) were also watched directly. Both are real plays, not dead time (`EXPERIMENTS.md`, 2026-08-23 later entry) — 2 of 2 checked so far have flipped. `CLAUDE.md`'s video-review-method rule already retired stills-based verdicts for this project after one went wrong (the IMG_7744 false-positive review); a trajectory-plot read is a different still/aggregate proxy for the same underlying question and has now failed the same way.

**Decision.** PIC-37's 12-item "confirmed" FP list is downgraded from ground truth to **unverified pending playback re-check** — none of it should be cited as settled until re-watched. ADR-055's "no separation" conclusion, which used that list (n=11) as its negative-class sample, is downgraded from accepted to **provisional**: a contaminated negative class (real plays counted as dead time) would suppress any real separation regardless of whether the underlying stillness signal works, so ADR-055's rejection of the signal cannot yet be trusted at face value. Notably, the two reclassified points point toward the signal working better than ADR-055 found, not worse (199.40s — the one "FP" with a real-serve-like dip — turns out to be a real play), which is exactly the kind of directional hint that would be lost by not re-checking.

**Consequences.** `PIC-31` stays open. Before any further conclusion is drawn from PIC-37's FP list (including re-testing the stillness signal, the two untested sibling signals from 2026-08-22, or citing the 48%-real-dead-time-crossings figure from the 2026-08-19 FP-anatomy entry), the remaining 10 of 12 post-bump FPs need the same playback check. This is the same failure mode CLAUDE.md already documents once (stills-based verdicts) recurring in a different guise (trajectory-plot-based verdicts) — worth generalizing the rule: no aggregate or single-frame proxy for motion is trustworthy for a rally/dead-time call on this project without playback confirmation, full stop. **Superseded by ADR-057** — the remaining 10 were checked; all are real plays too.

---

## ADR-057 — PIC-37's "IMG_7743 post-bump is 12/12 real dead-time crossings" finding is retracted; it's 12/12 unlabeled real plays. This is a labeling-completeness bug, not a `PIC-31` finding.

**Date:** 2026-08-23 · **Status:** accepted

**Context.** ADR-056 flagged 2 of PIC-37's 12 "confirmed by trajectory-plot read" `IMG_7743` post-bump false positives as real plays on playback, and downgraded (not yet retracted) PIC-37's finding pending the other 10. All 10 have now been playback-checked (`EXPERIMENTS.md`, 2026-08-23 final entry): every one is a real play. User's verdict, verbatim: "all of them have actual actions in them, just a variety of different duration of start time and end time. none of them are dead time." 12 of 12 checked, 12 of 12 real.

**Decision.** PIC-37's claim that "post-bump in particular is entirely real dead-time crossings (12/12) — nothing there is a detector flaw at all" is **retracted, fully inverted.** The detector was correct on all 12 crossings; `eval/labels/IMG_7743_postbump_2900s-end.jsonl` is missing 12 real rallies. This is the project's already-named failure mode #2 (label incompleteness, `PROGRESS.md`'s three-failure-modes table), not a new `PIC-31` (dead-time signal) finding and not a `PIC-34` (phantom-crossing geometry) finding — the trajectory-plot method that drove PIC-37's classification produced a confident, wrong answer at 100% (12/12) on this video-half, the same failure class `CLAUDE.md` already retired stills-based verdicts for.

**Consequences.**
1. **IMG_7743 post-bump's true precision is higher than every figure computed against its current labels** — 12 real detections are being scored as false positives.
2. **PIC-31's 2026-08-19 duration/rate-threshold rejection partially rests on this same false premise** — its "sanity check first" table's `dead-time junk (n=12)` row is retracted; the table's broader unsupervised-check conclusion (scored against the full label set, not this specific list) likely still stands but wasn't independently re-verified here.
3. **ADR-055/ADR-056's "no separation" test never had a valid negative-class example in it.** Not "provisional" — invalid as run. `PIC-31` has not yet been tested against any confirmed genuine dead-time example on `IMG_7743`.
4. **PIC-37's pre-bump numbers (14 "real dead-time crossing," 10 "noise/hallucinated," same trajectory-plot method, zero playback-checked) are now suspect** and should not be cited until spot-checked the same way — the method just failed 12/12 on the one segment where it *was* checked.
5. **Fix is a relabeling task, not a code change.** `IMG_7743_postbump_2900s-end.jsonl` needs a proper exhaustive re-label pass (`LABELING.md`'s two-layer presence pass — see [[feedback_two_layer_labeling]]) adding the 12 missing rallies with real start/end boundaries. Only after that would this video-half have genuine dead-time examples to test any `PIC-31` candidate signal against. Recommend filing this against Linear `PIC-37` (reopen) and `PIC-31`. **Done — see ADR-058: labels went 6→53, not just +12, and the actual bottleneck this segment has turns out to be recall, not dead-time false positives at all.**

---

## ADR-058 — IMG_7743 post-bump, fully relabeled: false positives are gone (all were boundary fragments), recall is the real remaining problem, and it's a `min_crossings` ceiling

**Date:** 2026-08-23 · **Status:** accepted

**Context.** ADR-057 called for an exhaustive relabel of `IMG_7743_postbump_2900s-end`. Done: 6 → 53 labels (`EXPERIMENTS.md`, 2026-08-23 postscript), far more than the 12 known gaps — confirming the false-positive list could never have surfaced rallies the detector missed with zero output. Re-scored against shipped defaults: precision 0.818, recall 0.340 (18 matched / 22 predicted / 53 labels) at IoU≥0.5.

**Decision.** Two separate findings, not one:

1. **Precision is effectively perfect — no genuine junk remains.** All 4 residual "false positives" are boundary near-misses (IoU 0.31–0.47) on real, now-labelled rallies, not hallucinated detections. This closes the false-positive side of IMG_7743 post-bump entirely; `PIC-31` (dead-time discrimination) has nothing left to solve on this video-half.
2. **Recall (0.340) is the real, previously-invisible problem, and it is mechanically explained**: 30 of 35 misses have fewer than `min_crossings=6` raw net crossings in their window, so `cluster_crossings` never emits a segment — these rallies were invisible to every prior false-positive-based analysis on this video, by construction. A diagnostic-only sweep (not a parameter pick — `IMG_7743` is `eval`, locked, ADR-052) shows recall plateaus at 0.453 regardless of how low `min_crossings` goes, while precision collapses (0.818→0.267) as it drops — this is not simply a mistuned constant; some short rallies (1–2 net crossings) are below what any crossing-count threshold could ever assemble, and a lower threshold mainly admits noise, not more real rallies.

**Consequences.**
- For the current phase-1 deliverable (highlight reel): the practical impact is much smaller than 0.340 suggests — 4 of 5 `quality:1` (highlight-worthy) rallies were matched; 34 of the 35 misses are `quality:2` ordinary short exchanges.
- `min_crossings=6` was picked on IMG_7743 itself (ADR-048) and re-derived on `dev`-only videos (`PIC-43`) landing on the same value — if `dev` (brickwall, pb_draft_cup, IMG_7744) has the same kind of label-completeness gap IMG_7743 just had, PIC-43's re-derivation carries the same untested blind spot. Not yet checked.
- Whether the recall ceiling needs a different mechanism entirely (detecting a serve event, not accumulating crossings) rather than further threshold tuning is open.
- Recommend two new Linear issues rather than reusing `PIC-31` (about dead-time FPs, now near-moot on this video) or `PIC-49` (relabeling, now done): one for re-checking `dev`'s label completeness, one for the `min_crossings` recall ceiling itself. **Corrected same day — see ADR-059: the "recall ceiling" was measured against the wrong target.**

---

## ADR-060 — All four scored videos relabeled and re-checked; `min_crossings=6` confirmed across all of them; `PIC-31`'s dead-time-discrimination problem is, project-wide, almost entirely a labeling artifact

**Date:** 2026-08-23 · **Status:** accepted

**Context.** ADR-057/058/059 found and corrected IMG_7743 post-bump's label-completeness gap; `PIC-51` found the same on IMG_7744. Deprioritizing `brickwall`/`pb_draft_cup` at that point rested on a circular check (their live-play % matched a `PROGRESS.md` reference table computed from those same labels) — caught when asked directly what the plan was for those two. Relabeled both properly.

**Decision.** All four of the project's scored videos have now been exhaustively relabeled and re-checked in one day: IMG_7743 post-bump (6→53), IMG_7744 (20→75), brickwall (35→49), pb_draft_cup (18→34). Every one had a real, previously unmeasured gap. Re-scored, quality-split (per ADR-059's correction): `quality:1` recall is **flat regardless of `min_crossings`** on all four (brickwall 12/13, pb_draft_cup 7/10, IMG_7743 4/5, IMG_7744 2/3) — `min_crossings=6` is confirmed adequate for what the product actually needs, now checked against honest ground truth on the full scored set, not just IMG_7743-derived or `dev`-derived-but-untested numbers. Residual false positives are, project-wide, almost entirely boundary fragments (16 of 18 checked across brickwall/pb_draft_cup/IMG_7743, IoU 0.18–0.47 on real rallies) rather than genuine junk — only 2 (both on IMG_7744, `PIC-52`) remain unexplained.

**Consequences.**
- `PIC-31`'s founding problem statement — find a signal to separate real rallies from dead-time/junk crossings — turns out, once every video's labels are honest, to have almost nothing left to solve. What looked like a detection-quality ceiling across this whole project (ADR-050/051/053's precision-artifact thread, PIC-37's FP anatomy, this session's stillness-signal work) was, to a very large degree, an artifact of labels that silently under-counted short/ordinary real rallies — not a property of the detector.
- `PIC-43`'s `min_crossings=6` choice is now the most-validated constant in the project: derived on `dev`, and independently confirmed adequate against honestly-relabeled ground truth on all four videos including the previously-locked `eval` video.
- `PROGRESS.md`'s rally-length/live-play density table is finalized with real numbers, no longer provisional.
- **General lesson, worth carrying forward explicitly:** a "this number matches what we already expected" check is not validation if the expectation was itself derived from the same data being checked. Before treating agreement with a reference figure as evidence a dataset is fine, trace where that reference figure came from.
- Remaining open threads: `PIC-52` (2 unexplained IMG_7744 segments, low priority); whether `PIC-33`'s adaptive-`gap_sec` or a fragment-aware scoring approach should now be revisited given fragments are the dominant remaining false-positive mechanism everywhere; `PIC-31` itself should probably be closed or substantially re-scoped given this finding.

---

## ADR-061 — `PIC-31` candidate #1 (duration threshold), reversed in part: duration has real signal on honest labels; the 2026-08-19 rejection was measuring label contamination, not the signal

**Date:** 2026-08-23 · **Status:** accepted

**Context.** The 2026-08-19 rejection of a duration/crossing-rate threshold (`EXPERIMENTS.md`, "yet later" entry) partly rested on IMG_7743 post-bump's since-retracted "confirmed dead-time" false positives (ADR-057), and scored its broader check against all four videos' old, incomplete labels. ADR-060 found every one of those labels missed a large share of real rallies, in exactly the way (short rallies undercounted) that would make a duration signal look weaker than it is.

**Decision.** Re-ran the same candidate generation (raw crossing bursts, `min_crossings=1`) against today's honestly relabeled ground truth on the four confirmed videos. **Duration alone separates real from junk far more cleanly than 2026-08-19 found** — median real/junk duration ratios of 6–15x (vs. ~2x before), and a `duration≥3.0s` cutoff gives 97% recall at ~60% precision pooled (vs. ~23% base rate) — nowhere near the "misclassifies 24–50% of real rallies" the original rejection reported. **Crossing rate shows no such improvement and remains an unreliable feature** (very short junk clusters inflate rate by dividing by a near-zero duration); the original candidate bundled duration and rate together, which understated duration's real value.

**This does not change the shipped default.** Checked whether a duration filter would further clean up `min_crossings=6`'s current residual false positives (all boundary fragments per ADR-060): almost none are short enough to be caught by any reasonable duration cutoff — the signal is largely redundant with what `min_crossings` already provides at the current operating point, not additive on top of it.

**Consequences.** `PIC-31` candidate #1 should no longer be cited as "tried and failed" — it wasn't a fair test. It remains not worth shipping *in addition to* `min_crossings=6` (redundant), but would be a reasonable candidate if the project ever needs an alternative or independent gate to crossing-count clustering (e.g. if a future detector's crossing signal changes shape). This diagnostic pooled `IMG_7743` (`eval`) with `dev` for the threshold sweep — any real adoption would need a proper `dev`-only derivation per ADR-052, not the numbers reported here. Filed as `PIC-53`.

---

## ADR-062 — `start` is not literally serve contact; it's an intentional, variable lead-in for viewers. `LABELING.md` v4 codifies this; the eval harness does not yet account for it.

**Date:** 2026-08-23 · **Status:** accepted

**Context.** While digging into whether the pre-serve stillness dip marks the true rally start (a localization test against brickwall's now-honest labels, 17 rally starts spread across the full video, not just the previously-checked opening minutes): the dip's minimum lands a median of 1.07s *before* the labeled `start`, with a ~1.3s spread. Asked directly, the operator confirmed today's relabeling pass (`PIC-49`/`PIC-51`) intentionally set `start` a few seconds before actual serve contact — "for the sake of viewers" — varying by feel per rally (roughly 0–3s), not a fixed or consciously-tracked offset. `LABELING.md` as written defines `start` as literal serve contact.

**Decision.** Codify the lead-in as the documented rule (`LABELING.md` v4) rather than re-tightening to literal contact — a highlight reel benefiting from a few seconds of viewer context before a point starts is plausibly correct product behavior, not a labeling defect. `end` is untouched (still ball-dead, no lead-out padding). This is deliberately **not** resolved as "therefore re-fix the labels" — today's relabel stays as-is.

**Consequences, several threads to pull, not yet done:**
1. **`eval/harness.py`'s IoU matching (`TECH_SPEC.md` §11) now compares predicted segments against a label boundary that moves by an unspecified 0–3s per rally, not a fixed physical event.** This wasn't designed for that. No fix implemented here — needs a real design decision (e.g. a start-tolerant matching mode, or a documented acceptable-offset band) before being trusted for boundary-sensitive comparisons going forward.
2. **This confounds, doesn't necessarily invalidate, today's earlier boundary-fragment characterization (ADR-060).** The 30 residual false positives scored as boundary near-misses (IoU 0.18–0.49 against real rallies) could be partly explained by this lead-in offset dragging IoU down, on top of (or instead of) genuine `gap_sec`-clustering imprecision (`PIC-33`'s territory). The two explanations aren't yet disentangled — a detector segment starting at the true first crossing, compared against a label padded 0–3s earlier, would show reduced IoU for a reason that has nothing to do with fragmentation.
3. **The stillness-localization finding itself likely overstated the dip's imprecision** — much or all of the measured 1.07s median / 1.3s spread offset from `label start` may be lead-in-padding variance, not the dip itself wandering relative to true serve contact. The dip may track true contact considerably more tightly than that number suggests; not yet re-measured with this understanding.
4. **Today's precision/recall numbers for all four relabeled videos (ADR-058/059/060) technically used a boundary convention the eval harness wasn't built around.** Given `IoU≥0.5` is a fairly generous threshold relative to a 0–3s shift on multi-second rallies, this is unlikely to overturn any of today's headline conclusions, but hasn't been quantified.

**Recommend filing as a new Linear issue**: decide and implement how `eval/harness.py` should handle an intentionally-variable `start` lead-in (a tolerance band on the start edge specifically, distinct from `end`, rather than symmetric IoU slack), then re-run today's boundary-fragment and stillness-localization checks with it.

---

## ADR-059 — Correction to ADR-058: the recall "ceiling" was measuring the wrong target. `min_crossings=6` requires no change; recall should be scored per-`quality`, not blended.

**Date:** 2026-08-23 · **Status:** accepted

**Context.** ADR-058 reported IMG_7743 postbump recall of 0.340 against all 53 relabeled rallies, plateauing at 0.453 even as `min_crossings` dropped to 2, and framed this as a structural ceiling needing a new mechanism. The user pointed out the flaw directly: the presence-pass labels were correctly exhaustive (including single-point failed-return-of-serve rallies, which do count per `LABELING.md`), but the *product goal* is a highlight reel, not a complete inventory of every point — scoring recall against every trivial point, then concluding the pipeline needs to catch more of them, was optimizing for the wrong thing.

**Decision.** Re-scored recall split by the `quality` grade already captured during labeling. `quality:1` (highlight-worthy, n=5) recall is **flat at 4/5 (0.800) for every `min_crossings` value from 6 down to 1** — lowering the threshold recovers zero additional good rallies, it only admits `quality:2`/noise (predictions 22→132, precision 0.818→0.182). **`min_crossings=6` is already at ceiling on the metric that matters and needs no change.** The one missed `quality:1` rally traced to a ~9-second stretch with zero detected net crossings mid-rally — a tracking/occlusion gap, not a clustering-threshold problem; no `min_crossings` value could have caught it.

**Consequences.**
- `PIC-50` (filed under ADR-058's now-superseded framing, "needs a different recall mechanism") should be corrected or closed — the data no longer supports it as scoped. The one real open item is investigating the single tracking gap at 894–905s, a much narrower, lower-priority question.
- `PIC-51` (checking `dev` for the same label-completeness gap) still stands — that question is independent of this correction.
- **General methodological point for this project going forward:** presence-pass labels must stay exhaustive and honest (don't curate at label time — `[[feedback_two_layer_labeling]]`), but *evaluation* of anything recall-related should report `quality:1`-specific numbers alongside the blended one, not the blended number alone. A blended recall figure across all labeled points, most of which are `quality:2` filler, is not a reliable guide to whether the pipeline serves the product's actual goal.

---

## ADR-063 — Reel ranking formula locked in: duration + peak crossing rate + spike count, not flat averages

**Date:** 2026-08-23 · **Status:** accepted

**Context.** `TECH_SPEC.md` §7.2's ranking formula (`n_impacts`/`peak_motion`) belonged to the pre-`ADR-046` player-signal design and was never actually implemented against the TrackNet pipeline — every reel built since (`scripts/make_brickwall_tv3_highlight.py`, 2026-08-21) used an ad hoc single-feature score (raw crossing count), which ADR-054 already found structurally favors long kitchen-heavy dink exchanges over a real spread of rally types.

A first attempt this session at a duration-normalized fix (`crossing_rate` + `velocity_spike_rate`, both crossings/spikes ÷ duration, averaged 50/50) tested clean against the ADR-054 problem — the single highest-raw-crossing rally ranked 19th instead of 1st — but introduced the opposite bias: **rate metrics with a small denominator are noisy and skew toward short clips**. Measured directly: duration correlated -0.34 with crossing rate and -0.53 with spike rate across `brickwall-SEMI`'s 31 candidates. A 5-minute reel built on it was real-time-reviewed by the operator and judged fine, but the operator then asked directly to favor genuinely long rallies that also contain a fast/intense moment, rather than reward brevity.

**Decision.** Switched to three signals, live-tuned against `brickwall-SEMI` playback until the operator called the result "genuinely great": `duration` (used directly, not as a denominator), `peak_crossing_rate` (highest crossings/sec in any 3s sliding window inside the segment — a real burst, not diluted by slower stretches elsewhere in a long rally), and `n_spikes` (raw count of top-decile ball speeds in the segment, not a rate — more chances in a longer clip is a feature here, not a bug). Equal weights (1/3 each). Re-measured: duration now correlates **+0.82** with the combined score. Implemented as `src/select.py`'s `rank_segments` (8 new tests, `tests/test_select.py`), wired into `config.yaml`'s `selection.weights`, and `TECH_SPEC.md` §7.2 updated to match (the `n_impacts`/`peak_motion` version marked superseded rather than deleted, for history).

**Consequences.**
- Raw crossing count remains excluded as a ranking signal, per ADR-054 — this ADR doesn't reopen that, it replaces the flat-rate signals that came after it.
- ~~Not yet validated against `quality:1`/`quality:2` hand grades...~~ **Resolved 2026-08-24.** `scripts/validate_ranking.py` ran the shipped formula against all four graded videos (`brickwall_30fps`, `pb_draft_cup`, `IMG_7744`, `brickwall-SEMI`) — the combined score is higher for `quality:1` than `quality:2` on all four, no exceptions (88 matched rallies total). `duration` is the strongest single component (right on all 4 independently); `peak_crossing_rate`/`n_spikes` are each right on 3 of 4 individually, but the combined score stays consistent everywhere even where one component wobbles — exactly the intended benefit of combining three signals. Full numbers: `EXPERIMENTS.md`, 2026-08-24 "ranking formula validated" entry. No change to the shipped weights (still 1/3 each) — this confirms the existing formula, it doesn't suggest a different one.
- The original worry here ("might not transfer to a singles/short-rally video") is specifically resolved — `pb_draft_cup` is a singles match (per `project_key_pivots`/`EXPERIMENTS.md`) and validated cleanly above. Still untested on any footage from a genuinely new venue or play style beyond these four, same caution that applies to every other tuned constant in this project (`gap_sec`, `min_crossings`).

---

## ADR-064 — Fix `pod_infer.py`'s single-ratio coordinate scale-back (silently wrong on non-16:9 video)

**Date:** 2026-08-24 · **Status:** accepted

**Context.** `scripts/pod_infer.py` resizes every frame to TrackNet's fixed input shape (512×288, `prep3`) without preserving aspect ratio, then scales predicted coordinates back to source pixels using one ratio, `img1.shape[0] / HEIGHT` (height only), applied to both x and y. That's only correct when the source video is exactly 16:9 (512:288's own ratio) — every video this project had processed before (`brickwall_30fps`: 1280×720, `brickwall_semi`/`IMG_7744`/`pb_draft_cup`: 1920×1080) happens to be exactly 16:9, so the bug was invisible until `brickwall_mid_atlantic` (1280×640, a 2:1 crop) became the first non-16:9 video run through the pipeline. Found by the operator noticing a tracked-ball marker sitting adjacent to, not on, the ball in a diagnostic overlay video — not a targeted bug search.

**Decision.** Use separate `x_ratio`/`y_ratio` (`img1.shape[1]/WIDTH`, `img1.shape[0]/HEIGHT`) for scaling predicted x and y respectively. Also dropped `prep3`'s `ratio` parameter, unused dead code noticed while fixing this, unrelated to the bug itself.

Verified rather than assumed correct: re-ran inference on `brickwall_mid_atlantic` with the fix and measured the actual before/after shift — 11,020 common-frame detections, mean dx 76.5px, max |dx| 142.0px (exact match to the predicted worst-case math), dy exactly 0 throughout, `correlation(old_x, dx) = +1.000` (a pure linear scale error, confirming the diagnosis precisely, not approximately).

**Consequences.**
- Re-ran detection on the corrected predictions: 51 of 56 candidates identical; the 5 that changed all trace cleanly to a couple of crossings near the `court_wedge`'s x-boundary flipping in/out — one false candidate (that only existed because a bug-inflated crossing hit `min_crossings=6`) disappeared, one real candidate split after losing two crossings that only existed under the bug. Both are the fix correctly exposing something real, not new breakage. Full detail: `EXPERIMENTS.md`, 2026-08-24 "a real coordinate bug" entry.
- Rebuilt `brickwall_mid_atlantic`'s reel on the corrected data: 10 of 12 clips unchanged, 2 swapped for verified-genuine replacements.
- **Only affects x-dependent logic** (`court_wedge` gating, any future x-based signal) — net-crossing detection is y-only and was never affected, so this bug did not change *when* rallies were detected on any video to date, only spatial gating precision, and only on non-16:9 source video (none existed before this session).
- Every prior video's predictions CSV remains valid as-is (their source aspect ratio made the buggy and correct ratios identical). Only re-run inference for a video if it's non-16:9, or if x-precision specifically is being investigated.
- The bug was found through ordinary use of a diagnostic tool built for an unrelated purpose (visualizing signals), not a dedicated audit — worth remembering as a case for building visual diagnostics even when not specifically hunting for bugs.

## ADR-065 — Local GPU inference throughput: the bottleneck is `model.predict()` overhead, not GPU compute or batch size

**Date:** 2026-08-25 · **Status:** accepted, adopted in `scripts/pod_infer.py`

**Context.** The web UI (`PIC-57`) made inference wait time directly visible to a waiting operator for the first time, surfacing a real regression: a 16.3-minute video took 21.4 minutes of TrackNet inference (23fps, slower than the 30fps source) — 2.5× slower than the 58fps benchmark recorded on the same GPU (`EXPERIMENTS.md`, 2026-08-16), continuing a downward drift across several runs in between (58 → 57.3 → 30.6 → 27.3 → 23fps) that had been noted once before as unexplained and not investigated.

**Decision.** The bottleneck is Keras's high-level `model.predict()` API, called once per 3-frame group in a loop — it carries fixed per-call framework overhead (dataset/iterator setup, retracing checks) that doesn't shrink with more data per call, confirmed by profiling (`.predict()` is ~87% of wall time in isolation) and by directly testing the alternative: a `@tf.function`-wrapped direct model call, traced once, recovers the historical throughput (56.7fps unmasked / 36.2fps with court masking, vs. today's 29.2fps / 22.1fps) with byte-identical CSV output. Two other explanations were tested and ruled out first: thermal throttling (GPU stayed 33-46°C, no throttle flags) and GPU clock/power state (correctly boosts to ~2490MHz under load). **Batching (grouping multiple frame-trios into one `.predict()` call) was also tested and rejected** — it made things slower (25.6fps vs. 29.2fps), which is what actually revealed `.predict()` itself as the cost rather than per-call dispatch overhead scaling with call count.

**Consequences.**
- The fix was small: swapped `model.predict(x, batch_size=1)` for a `@tf.function`-wrapped `model(x, training=False)` call directly in `scripts/pod_infer.py` (traced once up front, outside the timed loop). No batching, no CPU/GPU pipelining rearchitecture — the bigger fix originally proposed for the (wrong) CPU-bound-preprocessing theory was unnecessary. `webapp/pipeline.py` needed no change — it already calls `pod_infer.py` by path via subprocess, so the fix is live there automatically.
- **Verified on the full real session that surfaced this**, not just the probe clip: 29,418 frames in 13.6 min at 36.2fps (vs. the original 21.4 min / 23fps), output byte-identical to the pre-fix CSV. Closes the "full-length confirmation" item this ADR originally left open.
- **Batching re-tested with the fix in place, still rejected**: 56.5fps at `batch_size=1` degrading steadily to 38.4fps at `batch_size=32` — confirms `batch_size=1` is genuinely optimal for this model/GPU, not an artifact of the `.predict()` overhead. Settled, not just deferred.
- **A second optimization was tried and explicitly rejected**: applying the court mask after resizing to the model's small input resolution (instead of before, on the full-res frame) recovers nearly all the masking-related slowdown (56.5fps vs. 36.2fps) but is NOT safe — diffed against the current approach, 124/603 frames (~20%) differ, including 5-7 frames with large position swings (up to 1184px) and one flipped detection. Root cause: resizing the *raw* frame first blends real background content into pixels near the court boundary before the (separately, coarsely resized) mask ever gets applied, letting clutter partially survive right at the edge — the opposite of what `court_mask` exists to prevent (`EXPERIMENTS.md` 2026-08-16). Mask-before-resize (today's order) stays as-is; this is not a bug to patch, it's a structural property of doing it in the other order at all.
- `archive/pod_infer_batched.py` holds the rejected batching experiment as a documented negative result (`archive/README.md`); the verified-fix script (`pod_infer_tffunc.py`) was deleted once its logic was merged into `pod_infer.py` directly, to avoid a redundant, drift-prone duplicate. Full detail and exact numbers: `EXPERIMENTS.md`, 2026-08-25 entries.
- Closes the loop on the 2026-08-16 note ("30.6 fps vs 58 fps inference speed gap is unexplained") and the similar unexplained-slowdown flag in the `brickwall_pro_series_finals` entry — same mechanism, not a per-video mystery.

---

## ADR-066 — Rolling 10-min-chunk cloud architecture: accept chunk-boundary rally loss (~1.28/hour) rather than build overlap handling now

**Date:** 2026-08-25 · **Status:** accepted (directional, post-prototype — same status as the `STRATEGY.md` §5 architecture it refines; not built)

**Context.** Exploring `STRATEGY.md` §5's "Option B, rolling delivery" concretely: analyze each 10-minute capture segment (reusing the same segments `TECH_SPEC.md` §1.2 already produces for crash-safety) as it lands during recording, instead of batching the whole session after capture finishes — keeps the GPU busy throughout the session rather than idle for ~2 hours then bursting all the work at the end. This makes each chunk its own independent detector invocation, with no visibility into neighboring chunks.

**The risk.** `crossing_times`/`cluster_crossings` needs `min_crossings=6` within one continuous window. A real rally whose crossings straddle a chunk boundary gets split across two unaware detector runs — best case, truncated to a fragment; worst case, both halves fall under `min_crossings=6` and the rally is never detected at all.

**Decision.** Measured the actual cost against real labels rather than estimate it (291 rallies, 6 videos, 2.34 hours, `EXPERIMENTS.md` same date): **2.13 rallies/hour straddle a 10-min boundary; of those, 1.28/hour are full misses** (both halves under `min_crossings=6`), the rest survive as truncated fragments. **Operator accepted this as a known cost of the architecture rather than building the overlap-and-dedupe fix now** (give each chunk a small overlap margin with its neighbors, de-duplicate matching detections when merging timestamps across chunks — the fix is well-understood, just not built).

**Consequences.**
- If this architecture is picked up for real, ~1 real rally will be fully missed roughly every 45 minutes of session time, plus a comparable rate of truncated (not lost, but incomplete) rallies — a real, non-zero cost, not a rounding error, but small relative to the throughput benefit motivating the architecture (continuous GPU utilization vs. idle-then-burst).
- The overlap/dedupe fix remains available and well-scoped if this cost turns out to matter more in practice than expected here — this ADR is what to revisit, not re-derive, if that happens.
- This decision is specific to the 10-minute chunk size. A different chunk size would change both rates (`EXPERIMENTS.md`'s method reproduces easily for a different `CHUNK` value if that's ever reconsidered).
- Directly reinforced by `ADR-065`: this architecture pays the per-invocation detector setup cost once per chunk, not once per session — the `tf.function` fix (setup cost ~1.7s vs. the pre-fix ~4-7 min) is what makes a 10-minute chunk size viable at all without the setup overhead itself dominating.

---

## ADR-067 — Formal prototype-gate assessment: recall (corrected) and the subjective gate pass; false-positive rate, boundary error, and budget utilization do not

**Date:** 2026-08-26 · **Status:** accepted (measurement record; supersedes the framing in `PRD.md` §5's 2026-08-26 status notes added earlier the same day, which checked only recall and the subjective gate)

**Context.** Asked directly whether `PRD.md`'s prototype gate has been cleared. Earlier the same day, `PRD.md` §5 was given status notes covering only the two criteria already known to look good (quality-split recall, the subjective playback gate) — an incomplete check, not a formal gate assessment. This entry is the complete one: every metric in `PRD.md` §5, checked against real current numbers, not just the ones already believed to pass.

**Method.** Ran the shipped k14 config (`court_wedge`, `gap_sec=3.0`, `min_crossings=6`, IoU≥0.5) through `eval.harness.detection_metrics` against current honest labels on all 5 labeled video/segments — `IMG_7743` postbump (`eval`, locked), `brickwall_30fps`, `pb_draft_cup`, `IMG_7744`, `brickwall-SEMI`. Separately read the four already-built reels' `manifest.json` files for the Selection targets, and used the confirmed post-`ADR-065` wall-clock number from the operator's real full session (`EXPERIMENTS.md`, 2026-08-25).

**Results.**

| Metric | Target | `IMG_7743`(eval) | `brickwall_30fps` | `pb_draft_cup` | `IMG_7744` | `brickwall-SEMI` |
|---|---|---|---|---|---|---|
| Recall (all labels, PRD's literal metric) | ≥0.90 | 0.340 | 0.633 | 0.559 | 0.187 | 0.605 |
| Recall (`quality:1`, the corrected standard, ADR-059/060) | — | 0.80 (4/5) | 0.923 (12/13) | 0.700 (7/10) | 0.667 (2/3) | ungraded |
| FP / 10min | ≤1.0 | 2.11 | 5.15 | 2.88 | 2.57 | 5.33 |
| Boundary error (median) | ≤1.0s | 1.43s | 1.42s | 1.62s | 1.21s | 1.47s |

Wall clock: **0.83×** (13.5 min inference / 16.34 min source, operator's real full session, local GPU, post-`ADR-065`), against a ≤0.5× target.

| Reel (`clips/*/manifest.json`) | Rally count ≥12 | Utilization vs. PRD's 600s budget (≥0.85) | Utilization vs. the 300s the reel script actually defaults to |
|---|---|---|---|
| `IMG_7743_reel_5min` | 17 ✓ | 0.33 | 0.66 |
| `IMG_7744_reel_5min` | 23 ✓ | 0.26 | 0.53 |
| `brickwall_pro_series_finals_reel_5min` | 8 ✗ | 0.41 | 0.82 |
| `brickwall_mid_atlantic_reel_5min_fixed` | 12 ✓ | 0.38 | 0.76 |

All four reels comply with the 600s hard budget. The subjective gate passes cleanly, arguably exceeded (4 reels confirmed good by direct playback 2026-08-25, vs. `PRD.md`'s 3-session/2-of-3 minimum).

**Read — not all failures are equally meaningful.**

1. **Recall-all "failing" is not new news.** Already corrected: `quality:1` is the right standard (ADR-059/060), and scored that way recall is genuinely solid and flat everywhere (0.67–0.92). A target-definition fix already made, not an open gap.
2. **FP rate and boundary error are real, open, and already understood — this just puts a number on a known problem.** ADR-060 found 16/18 checked "false positives" are boundary fragments on real rallies (IoU 0.18–0.47), not hallucinated junk. Both metrics trace to the same two still-open, unfixed items: `gap_sec`-clustering fragmentation (`PIC-33`) and the `LABELING.md` v4 intentional start lead-in the eval harness doesn't account for (`PIC-55`). `PROGRESS.md` already carried the qualitative note ("boundary precision, not detection correctness") — this is the first time it's been checked against PRD's actual numeric bar, and it doesn't clear it.
3. **Budget utilization is a real, previously-unexamined gap.** Even scored against the 300s the reel script actually targets — not PRD's stated 600s — 3 of 4 reels land at 0.53–0.82, still short of ≥0.85. Not diagnosed: could be overly conservative selection, or a real ceiling on available `quality:1` material in some sessions. New open item, not previously checked.
4. **A small, previously-undocumented discrepancy:** `scripts/rank_and_reel.py --target-sec` defaults to 300s, not `PRD.md`'s stated 600s "hard budget." Every reel built so far used the 300s default; whether the intended reel length is 5 or 10 minutes has never been explicitly decided.
5. **Wall clock, even after `ADR-065`'s major fix (23fps → 36fps), is 0.83× — not ≤0.5×.** Measured on local GPU only; `PRD.md` G4 names RunPod GPU as the actual production platform, unmeasured against this bar.

**Decision.** The prototype gate is **not cleanly met**. The two bars that matter most for `PRD.md` §2's original question — does the pipeline find the highlight-worthy rallies, and is the resulting reel something worth watching — are both genuinely solid. But three of `PRD.md`'s own explicit numeric targets (FP rate, boundary error, budget utilization) fail consistently across every scored video, and wall clock fails on the one platform measured. None of this is a surprise discovery about detection quality — `PIC-31`/detector-tuning work is already known (ADR-060) not to be the lever here.

**Consequences.** Do not declare the prototype gate formally passed on this evidence — correcting the framing in `PRD.md` §5's earlier-same-day status notes, which checked only the two passing criteria. The concrete path to actually closing the gate is narrower than continuing detector work: (1) `PIC-33`/`PIC-55`'s boundary-fragmentation fix, which would plausibly move both FP-rate and boundary-error into range — the single highest-leverage remaining item; (2) explicitly decide the real target reel length (5 vs. 10 minutes) and diagnose whether utilization is a selection-tuning problem or a content-availability ceiling; (3) get one real wall-clock number on the actual RunPod production path. Recommend this list as the next deliberate technical direction, ahead of the trained-classifier question (`PIC-46`/`PIC-42`).

---

## ADR-068 — Correction to ADR-067: `PRD.md`'s numeric targets are provisional, not binding gates; the subjective gate is the real objective, and it has been met

**Date:** 2026-08-26 · **Status:** accepted (same-day correction)

**Context.** ADR-067 treated `PRD.md` §5's numeric targets (recall ≥0.90, FP ≤1.0/10min, boundary error ≤1.0s, wall clock ≤0.5×, utilization ≥0.85) as binding gates and concluded the prototype gate was "not cleanly met" because three of them fail. The operator corrected this directly: `PRD.md` was drafted 2026-07-30, before any real footage had been collected, calibrated, labeled, or scored — its numeric targets are hypothetical placeholders, not measurements calibrated against real data. The actual objective, `PRD.md` §2's own framing, is narrower and more concrete: "is the resulting reel something I actually watch?" — the subjective gate, not the numeric scaffolding underneath it.

**Decision.** Re-read ADR-067's findings under this correction, not re-measured — the numbers stand, the verdict built on them does not. The subjective gate, the actual objective, has been passed, arguably exceeded (4 reels confirmed good by direct playback 2026-08-25, vs. `PRD.md`'s 3-session minimum). ADR-067's numeric findings (FP rate, boundary error, wall clock, utilization all short of target) are retained as real, correctly-measured **diagnostic** signals — they correctly locate a real, understood rough edge (`PIC-33`/`PIC-55` boundary fragmentation) worth fixing — but are not gates the prototype needed to clear. **The prototype's core question, as `PRD.md` §2 states it, is answered: yes.**

**Consequences.** Withdraw ADR-067's "not cleanly met" headline verdict. `PRD.md` §1's stated next step ("a production PRD follows, written with real numbers instead of guesses") is a live decision again, not foreclosed by unmet numeric targets that were never real gates. `PIC-33`/`PIC-55`'s boundary-fragmentation work remains genuinely worth doing — a real, fixable rough edge, and the numbers it would move are useful signals of reel quality even if not gates — but as ordinary next-iteration work, not a blocker on treating the prototype as successful. This correction is itself a durable lesson worth generalizing: a spec document's numbers are not automatically ground truth just because they're written down — check when and against what they were set before treating them as binding.

---

## ADR-069 — Upload a 720p proxy to R2/RunPod instead of full resolution; keep the final cut full-res and local

**Date:** 2026-08-27 · **Status:** accepted

**Context.** The cloud route (`cloud_pipeline/run_cloud_job.py`) uploads the full-resolution CFR-converted video to R2 and to the pod — for a 22-minute session, that was a ~1GB transfer each way. Operator asked to shrink this by sending only a 720p proxy for detection, matching `ADR-043`'s original (never-built) "proxy video trick: cut from local full-res" design.

**The risk found before writing any code.** `calib.json`'s `homography`/`image_points` are absolute pixel coordinates with no resolution recorded anywhere — `court_mask()` (`scripts/pod_infer.py`) builds its mask by projecting that homography into pixel space and indexing it directly against whatever frame it's given, assuming the two are the same resolution. They always have been, until now. Feeding `pod_infer.py` a 720p proxy while `calib.json` was calibrated at native resolution would silently misplace the court mask — the same class of bug as `ADR-064`'s coordinate mismatch, but corrupting *what the detector sees* rather than just a reported coordinate.

**Decision.** Record the calibration frame's resolution in `calib.json` (`calibration_resolution: [w, h]`) at every site that writes one (`calibrate.py`, `calibrate_web.py`, `webapp/app.py`'s two save routes). `court_mask()` now builds the mask at the *calibration's* resolution (where the homography is actually valid) and resizes the finished boolean mask to the frame actually being processed via `cv2.resize(..., interpolation=cv2.INTER_NEAREST)`, rather than hand-scaling the intermediate row/column arithmetic — deliberately the simpler, lower-risk option given `ADR-064` was exactly that kind of per-axis scaling mistake. `pod_infer.py`'s output coordinates (`x_ratio`/`y_ratio`) are likewise computed against `calibration_resolution` when present, so predictions.csv always lands in the *calibration's* pixel space regardless of what resolution was actually processed — meaning `build_reel()`, `track_ball`, `crossing_times`, and every other downstream consumer needs zero changes; the proxy is invisible to them. `run_cloud_job.py` uploads a 720p downscale (`ffmpeg -vf scale=-2:720`) instead of the full-res CFR video, but `build_reel()` still cuts the final reel from the untouched full-res local copy. **Old `calib.json` files without `calibration_resolution` fall back to today's exact behavior** (treat the input frame as the calibration resolution) — confirmed byte-identical in testing, not just assumed — and `run_cloud_job.py` refuses to use the 720p proxy for a venue calibrated before this field existed, uploading full-res instead rather than risk a silent scale mismatch.

**Verified, not just reasoned through.** Backward compatibility: ran the pre-change and post-change `pod_infer.py` against the same clip with an old-format `calib.json` — byte-identical output. New behavior: added `calibration_resolution` to a real calib.json, ran `pod_infer.py` once on the native 1920×1080 clip and once on a genuine 720p downscale of the same clip — `x_ratio`/`y_ratio` and the court-mask coverage percentage matched exactly between the two runs, and of 70 frames both runs detected a ball, the mean position distance was 1.8px (max 39.8px, one outlier) *in native-resolution pixel space* — small, expected differences from the lower-res encoding losing fine detail, not a systematic scale mismatch (which would show large, position-dependent errors, not this).

**Consequences.** Detection-accuracy impact of running on 720p versus native resolution is still not measured against real labels — this ADR verifies the coordinate *mechanism* is correct, not that recall/precision hold up at 720p. That's the next thing to check before trusting this in place of full-res for a real scored session. Any venue wanting the bandwidth savings needs to be (re)calibrated after this change to get `calibration_resolution` written; venues calibrated earlier keep working exactly as before, just without the proxy.

**Update, 2026-08-28 (`EXPERIMENTS.md`):** measured against real labels on `pb_draft_cup_30fps` (native 1920×1080, 34 labels). 720p showed no accuracy degradation — precision/recall were marginally *better* than native (0.773/0.500 vs. 0.714/0.441), and the one `quality:1` rally that scored as a miss at 720p turned out to be a boundary-threshold artifact (IoU 0.491 vs. native's 0.602 on an otherwise identically-detected rally), not a real missed detection. Caveat: single video, and this session also surfaced real run-to-run non-determinism in `pod_infer.py` (~7% of frames land a different position on a rerun with identical inputs) that this one comparison can't fully separate from a genuine resolution effect. Good enough to keep shipping the 720p proxy; not exhaustive enough to call the resolution question permanently closed.

---

## ADR-070 — Consistent logging across both pipelines: extend the working per-job pattern, don't add `logging.Logger` as a second system

**Date:** 2026-08-27 · **Status:** accepted

**Context.** Three uncoordinated logging conventions existed: (1) `webapp/pipeline.py`'s per-job `log.txt`/`status.json` pattern, shared by both routes, working well but untimestamped; (2) `cloud_pipeline/run_cloud_job.py`'s bare CLI path, pure `print()`, nothing persisted; (3) `webapp.py` itself, zero logging configuration. (3) caused a real incident the same day: the process was started directly in a terminal, that terminal closed, the process died via SIGHUP with zero trace anywhere (`dmesg`/`journalctl` both empty) — it had to be restarted by hand with an ad hoc `nohup ... > webapp/webapp.log`. Operator asked for "a solid and consistent logging practice across the board."

**Decision.** Don't introduce Python's `logging` module as a second, parallel job-logging system — extend the pattern that already works. A new shared helper, `src/job_log.py`'s `append(job_dir, msg)`, adds a `[HH:MM:SS]` prefix and is the single implementation both `webapp/pipeline.py`'s `_log()` (now a one-line delegate) and `cloud_pipeline/run_cloud_job.py`'s CLI `main()` (via a `_cli_log` closure reusing the existing `log_fn` mechanism, not a new path) call — every `log.txt` line looks identical regardless of which route or entry point produced it, and no caller above `_log()`/`log_fn` needed to change.

`webapp.py` is the one place `logging`'s handler machinery *is* the right tool, not a second system: Werkzeug's request logging and Flask's own error logging already flow through `logging.getLogger('werkzeug')`/`app.logger`, which propagate to root by default, so a `RotatingFileHandler` (5MB × 3 backups) attached to root captures them for free. Also added SIGHUP/SIGTERM/SIGINT handling that logs the signal before exiting — directly closes the "zero trace anywhere" gap the incident exposed. Full `%Y-%m-%d %H:%M:%S` timestamps here (vs. `job_log.append`'s bare `HH:MM:SS`) — deliberate, since this one file spans many days and restarts, unlike a job-scoped log.

**Explicit non-goals:** the five `src/*.py` files' scattered `logging.getLogger`/`basicConfig` usage (different, interactive context, low value to unify, real risk touching detection code for cosmetic benefit); process supervision (nohup/systemd) — this makes a death visible in the log, it doesn't prevent one, confirmed as a separate follow-up with the operator.

**Consequences.** Verified live, not just reasoned through: real startup/request/SIGTERM sequence produced exactly the expected log lines (`2026-08-27 12:27:02 WARNING [webapp] received SIGTERM, shutting down` as the last line before the process died); rotation mechanics confirmed with a small `maxBytes` in isolation; the CLI closure and `webapp/pipeline.py`'s patched `_log()` both confirmed producing matching `[HH:MM:SS]`-prefixed output. Full test suite: 130/130 pass. One pre-existing asymmetry surfaced, not introduced or fixed here: the local route's per-frame inference progress bypasses `_log()` entirely (a raw subprocess-stdout passthrough) while the cloud route's per-frame lines go through `log()`→`_log`, so cloud per-frame lines will carry timestamps and local ones won't — noted so it isn't mistaken for an oversight later.

---

## ADR-071 — Split the venue-side system: a thin local agent (LAN-bound work only) vs. a cloud web app (everything that's just data)

**Date:** 2026-09-02 · **Status:** accepted (architecture only — nothing in this ADR is built yet)

**Context.** `STRATEGY.md` §5 originally scoped the desktop client (`desktop/`) to own the *entire* venue-side pipeline: camera discovery/management, local stream/footage management, local encode, sending to the cloud, receiving cloud output back, and CDN delivery. Two days of building `desktop/` (camera discovery, calibration-adjacent flows, manual recording — `PIC-64`/`PIC-66`) made clear that most of that scope doesn't actually need to run at the venue. The forcing constraint: ONVIF discovery is UDP multicast and a venue's cameras sit on a private LAN with no port-forwarding, so camera-facing work (discovery, RTSP connect/capture) can only run on a machine physically at the venue — that part isn't optional. But scheduling, court/venue management records, footage review, and multi-venue admin are just data, and don't need to be anywhere near the venue at all. Operator: "I was expecting heavy lifting on the web app (including camera management, etc)... schedulers, other court management tasks remain on the web app on the cloud."

No hosted, multi-venue, authenticated web app exists anywhere in this repo today — `webapp/` (Flask) is a single-operator local tool (upload footage, calibrate, run the pipeline, download a reel), not venue-facing or cloud-hosted. This ADR fixes the target shape both existing pieces should grow toward, before either grows further in the wrong direction.

**Decision.**

**Local agent keeps** (LAN-bound or needs the actual local file on disk — can't move):
- Camera discovery/management (`electron/cameras/*`, built)
- Recording/capture (`electron/capture.js`, built)
- Court calibration — currently `setup_venue_calibration.py`, a standalone script never folded into `desktop/`; belongs there, not in the web app, since it needs a live/local frame to click points on and is invalidated by camera movement (ADR-049)
- Transcoding (CFR conversion) — currently ffmpeg calls inside `cloud_pipeline/run_cloud_job.py`/`webapp/pipeline.py`, NVIDIA-only (`PIC-67`), not yet invoked by `desktop/` at all
- Uploading to R2 — currently `cloud_pipeline/r2_storage.py`, real and working, not yet invoked by `desktop/`
- Receiving cloud-pipeline output and cutting the final reel from local full-res footage — per ADR-043's own privacy-driven reasoning (full-res video stays local), this step has to run wherever the full-res file is, i.e. the local agent, not the web app, regardless of how everything else splits

**Cloud web app takes** (pure data/orchestration, no LAN dependency):
- Scheduling — today's `ScheduleOverviewPage`/`ScheduleEditorPage` + `electron/schedule.js`, built in `desktop/` this session, migrates wholesale (data and UI both) once the web app exists. Today's implementation isn't wasted work: it's the real interim mechanism and the reference design for the migrated version, but `desktop/` is not its permanent home.
- Court/venue management records, footage review, multi-venue admin, delivery to players — all new, none of it built yet.

**Reuse, don't reimplement:** the local agent's transcode/upload/calibration work already exists as real, working Python (`cloud_pipeline/r2_storage.py`, the ffmpeg CFR calls, `setup_venue_calibration.py`). The Node/Electron agent should invoke these as subprocesses — the same pattern `capture.js` already uses for `ffmpeg` directly — not port R2 upload or calibration math into JavaScript from scratch. This was already `PIC-68`'s scoped plan; this ADR just confirms it's still the right call under the wider split.

**Connectivity: local agent is outbound-only.** It polls (or maintains a lightweight persistent connection to) a cloud backend for pending commands and reports status back — it never needs an inbound port opened on the venue's router. This was chosen, not defaulted to, because the operator explicitly located the web app "on the cloud" (ruling out a local-only web UI serving the same box), and an outbound-only model needs zero network configuration at the venue, consistent with the project's standing "any camera, no vendor-specific setup" stance extended to networking too. Polling over a persistent WebSocket for the *first* version — camera management, calibration, transcode, and schedule sync are none of them latency-sensitive the way a live video feed would be; a persistent channel is a reasonable later upgrade if command latency becomes a real problem, not a day-one requirement.

**The schedule-ownership/local-trigger split, made explicit:** scheduling *data and UI* move to the cloud, but *actually starting/stopping a recording on time* still has to execute locally (`PIC-72`). The local agent closes that gap by polling/caching the schedule for its own cameras over the same outbound connectivity channel above — not a separate mechanism.

**Consequences.** Nothing here is built — this is the target shape for `PIC-68` (wire capture to `cloud_pipeline`), `PIC-72` (schedule → capture trigger), and the not-yet-created web-app work, not a new implementation task itself. Concretely still missing, now with a fixed target instead of an open question: a local-agent API surface (nothing external can drive `desktop/`'s Node backend today — only its own Electron renderer can, via IPC), the outbound connectivity/relay mechanism itself, a real multi-tenant database and auth system (today everything is flat JSON — `electron-store` locally, R2 objects for footage — with zero user accounts anywhere), and per-venue scoped cloud credentials (`PIC-71`, a hard prerequisite for the web app to trigger any venue's pipeline safely). `desktop/`'s Schedule UI, built earlier this session, is explicitly interim — a future session moving scheduling to the web app should treat it as the reference design to port, not a mystery to re-derive, but should also actually remove it from `desktop/` once the migration lands rather than maintaining the same feature in two places.

---

## ADR-072 — `track_ball` re-acquisition checks a velocity-predicted position too, not radius-widening

**Date:** 2026-09-04 · **Status:** accepted

**Context.** Real footage (`brickwall-SEMI` rally_id 1) exposed a fragmentation mechanism a flat `max_jump` re-check can't handle: near-net dink exchanges have short raw-detection dropouts (likely occlusion/small apparent size), and by the time detection resumes the ball's real elapsed distance from `last` has grown past `max_jump`, even though it's the same ball continuing along its path. See `EXPERIMENTS.md`, 2026-09-04.

**Decision.** `track_ball`'s re-check now accepts a candidate within `max_jump` of *either* the last confirmed position *or* a position predicted from the last confirmed position plus a two-point velocity estimate (no smoothing) times elapsed frames — not a wider flat radius. A radius-scaling alternative (`max_jump * scale_fn(elapsed)`, several scale functions swept) was tried first, recovered `brickwall-SEMI` as well or better, but silently dropped a real `quality:1` rally on `pb_draft_cup_30fps` (rally_id 9) — a wider radius can't distinguish "the ball, further along its real path" from "background clutter merely within range," and clutter inside the widened radius anchors `last` onto itself, after which the real ball falls outside the (now wrongly anchored) radius for good. Prediction avoids this because it uses direction, not just distance: real ball motion continues near its established trajectory through a short gap, and clutter doesn't line up with it. Velocity is unavailable (falls back to last-position-only) for one point after a cold start or reset, since a direction needs two points.

**Consequences.** Re-verified against the full locked dev set (`IMG_7744`/`brickwall_30fps`/`pb_draft_cup_30fps`) and `pb_draft_cup_30fps` rally_id 9/27 specifically — no regressions, one net gain on `IMG_7744` (14→15/75 matched, fp/10min 2.57→2.06). `brickwall-SEMI` rally_id 1 improves (best-overlap 9.8s→14.57s of a 20.02s label window) but is not fully recovered — the remaining gap stays open under `PIC-33`, distinct from the label lead-in issue tracked as `PIC-55`. The post-reset re-acquisition confirmation path (separate from this main-track re-check) still does no prediction — it only ever has one point before a candidate is confirmed, so there's nothing to predict from yet.

---

## ADR-073 — Cloud job API is vendor-neutral; RunPod and R2 are invisible on both sides of the product

**Date:** 2026-09-04 · **Status:** accepted (design only — nothing in this ADR is built yet)

**Context.** `PIC-71` flagged that `cloud_pipeline/r2_storage.py` and `cloud_pipeline/runpod_pod.py` authenticate with the operator's own raw account-level `RUNPOD_API_KEY`/`CLOUDFLARE_R2_*` keys, loaded from a local `.env` — fine for the operator's own CLI, not something that can be embedded in a desktop client distributed to external venues (anyone could extract full account access from the installed app). `pic-vision-cloud-console` already has the missing per-device credential primitive: a per-agent bearer token (`agents.api_token_hash`, issued once via a pairing code, checked on every `/api/agents/heartbeat` call) — real, working, in production. The design question was how to extend that existing mechanism to also cover job execution, without reintroducing raw account keys on the client.

**Decision.**

1. **A new vendor-neutral job API on the cloud console**, authenticated the same way as `/heartbeat` (`Authorization: Bearer <agent's apiToken>`): `POST /api/agents/jobs` → `{job_id}`, `GET /api/agents/jobs/:id` → `{status, output_url}`. The desktop client only ever talks to this contract.
2. **R2 access is via short-lived presigned S3 URLs**, minted server-side by the job API using the real R2 keys (env vars on the Next.js deployment, never shipped to any client), scoped to that agent's own `venue_id` prefix (`venues/<venue_id>/jobs/<job_id>/...`). The desktop client uploads/downloads directly against the presigned URL — no raw R2 credential ever touches it, and a compromised client leaks at most one job's worth of access. **The prefix scoping is a server-side discipline, not an R2-enforced guarantee** — R2 doesn't know or care what prefix a presigned URL points to; the security boundary is entirely the job-API route correctly deriving the prefix from the authenticated agent's own `venue_id` before signing. A bug there defeats the whole point, so this needs a test that asserts an agent can never get a presigned URL outside its own venue's prefix.
3. **RunPod is fully hidden inside the job API's own fulfillment logic** — never named, never exposed, anywhere in the desktop-client-facing or venue-owner-facing surface. Unlike R2, RunPod has no equivalent to a scoped/short-lived presigned URL, so there's no way to hand a venue-scoped credential to the client at all; the only safe shape is the console proxying the whole RunPod interaction server-side, holding the real `RUNPOD_API_KEY` itself. This also means the fulfillment vendor is swappable later without ever touching the desktop-facing contract.
4. **Local GPU inference never touches this API at all.** Whether a venue's box runs detection locally or needs the cloud fallback is a decision the desktop client makes entirely on its own (does this machine have a usable GPU?); the job API exists purely for the cloud-fallback case.
5. **Product-level principle, both surfaces:** a venue owner's mental model, whether they're looking at the desktop client or the cloud console, is "manage my cameras" and "watch my clips" — full stop. Cloudflare, RunPod, R2, presigned URLs, job IDs — none of it is ever visible to them. This is the processing-side extension of the project's existing "any camera, no vendor-specific setup" stance (`ADR-071`). Concretely: the desktop UI shows something like "processing your last session" → "ready to view," not a job-status screen full of infra jargon; the cloud console's Reels tab (already scaffolded, currently mock data) is where a venue owner actually sees output.

**Consequences.** Nothing here is built — this is the target shape for `PIC-71` and a real prerequisite for `PIC-68` (cloud_pipeline wiring) ever running against anything but the operator's own footage. Explicitly out of scope for this ADR, flagged as a related-but-separate follow-up: **per-venue usage/cost limits.** The moment any paired venue can trigger a billed RunPod job through this proxy, "how much spend can one compromised or just-buggy desktop client generate" becomes a real question that this design doesn't answer — rate limits or a budget cap belong in the job API's fulfillment logic, but need their own design pass. Also flagged, not designed here: **an internal operator tool to manage multiple venues/agent instances** (view all paired venues, their job/usage history, revoke a compromised agent's token) — the cloud console built so far is entirely venue-owner-facing; nothing exists yet for the operator's own cross-venue view. Tracked as a new issue rather than folded into this one.

---

## ADR-074 — Cut the final reel cloud-side, from a 1080p proxy, not locally from full-res

**Date:** 2026-09-04 · **Status:** accepted (amends `ADR-043`/`ADR-071`; not yet implemented)

**Context.** The shipped pipeline (`cloud_pipeline/run_cloud_job.py`) uploads a 720p proxy for RunPod inference only, downloads back a small `predictions.csv`, and cuts the actual highlight reel locally from the untouched full-resolution original — a design `ADR-071` explicitly attributed to `ADR-043`'s privacy reasoning ("full-res video stays local"), and listed as a reason the local agent has to keep this step. Two things reopened it: the actual delivery target is social sharing (Instagram), where 720p is below Meta's own recommended 1080p baseline — verified live, not assumed (Instagram compresses everything toward a 1080p target, not from a 720p floor, so a 720p source stays visibly softer after their re-encode); and once that's true, keeping the cut local stops being free — it exists only to avoid re-uploading full-res, which was never the actual privacy line. `ADR-043`'s real rule is narrower than "no video leaves the venue": it's "full-resolution original stays local." A 720p (or 1080p) proxy already leaves for inference either way, so cutting the final reel from that same already-uploaded proxy exposes nothing new.

Checked before deciding, not assumed: `predictions.csv` timestamps are seconds, not pixels — rally detection/ranking/cutting is resolution-independent, so cutting from a proxy instead of full-res changes nothing about which segments get chosen. Also measured on real footage (`IMG_7893_930-1110s`, native 1080p): GPU inference throughput is barely affected by proxy resolution (65.4fps at 1080p vs 71.8fps at 720p, ~9%) because `pod_infer.py` resizes every frame to a fixed 512x288 before the model sees it regardless of source resolution — the real cost of 1080p over 720p is upload bandwidth (~2.4x the data), not compute.

**Decision.**

1. **Upload a 1080p proxy** (not 720p) — for a camera whose native resolution is already ≤1080p (true of every camera in this system so far), this is just the CFR-converted file as-is, no separate downscale step. A higher-res source (4K) still gets downscaled to 1080p, same mechanism as the old 720p step.
2. **Cut the reel on the RunPod pod itself, right after inference, from the uploaded 1080p proxy** — `build_reel()`'s detection/ranking/cutting logic is pure CPU/ffmpeg work with no GPU dependency, so it runs on the same pod before it terminates, not as a separate local step.
3. **Upload the finished reel files (`highlight.mp4`/`highlight_by_rank.mp4`) to R2**, not `predictions.csv` — the desktop client never downloads detection data or runs a local cut again. It polls until the job is done and gets a reference to where the finished reel lives.
4. **The cloud console's Reels tab reads the finished reel directly from that R2 reference** — no separate delivery mechanism needed beyond what the job pipeline already produces.
5. **Superseded from `ADR-071`:** "cutting the final reel from local full-res footage" is no longer something the local agent does. The full-res original still never leaves the venue — that part of `ADR-043` is untouched — but the *finished, shareable* reel is now a 1080p cloud-side artifact, not a full-res local one.

**Consequences.** A venue that later wants a true full-resolution cut of a specific rally (a paying member request, archival, etc.) isn't served by this — the full-res original stays local and untouched, so that's still possible in principle, but nothing in this pipeline produces it automatically anymore. Not designed here, flagged as a future need if it comes up. This also strengthens `ADR-073`'s job-API design (its `output_url` now points at an actual finished reel, not something the client still has to act on) and shrinks `PIC-69`'s scope considerably (per a stale-ticket check the same day, its original scope — "cut from local full-res" — already existed in the code before this ADR; what's left of it after this ADR is much smaller: receive a finished-reel reference, not raw detection output). R2 storage cost grows with reel count now (finished reels persist in R2 for delivery, not just transient job scratch data) — worth watching now that the bucket was just found at 89% of its free tier before a cleanup (see `progress/09.04 progress overview.md`).

---

## ADR-075 — Reel videos served from a stable Cloudflare-fronted CDN URL, not a presigned one; R2 key is the reel's own UUID

**Date:** 2026-09-04 · **Status:** accepted, implemented and deployed

**Context.** The public reel-share page (`reel-page/`, new this session) and the cloud console's authenticated reel-video route both served the finished reel via a short-lived presigned R2 URL (`lib/r2.ts`'s `presignedReelUrl`, mirroring `cloud_pipeline/r2_storage.py`). That made sense for a page requiring its own access check, but neither actually does: the public share page's whole security boundary is already "know the reelId" (the `reels` table's public-SELECT RLS policy, added this session), and the console route's real check happens one step earlier, in its own RLS-scoped `select()` — the presigned URL was solving a problem neither page has. It also actively worked against this page's purpose: a uniquely-signed query string on every request defeats both browser and CDN caching, on a page whose entire point is getting reshared and reopened repeatedly (that's what the "Repost it"/"Send to" sections exist for).

Real timing measurements first, not assumed (see progress notes, same day): presigned-origin fetch showed ~285-337ms TTFB; the R2 object's own `Content-Type`/`ContentLength` were already correct (ruled out as a cause of an unrelated share-sheet icon question the same day). Once `cdn.picvisionai.com` was live as an R2 custom domain with a Cloudflare cache rule, repeat fetches confirmed `cf-cache-status: HIT` — but a controlled comparison from one dev machine (Singapore PoP) showed no clear win over the origin path from that specific vantage point (both ~1-1.3s for the same 8.35MB file) — logged plainly rather than oversold, since R2 itself already rides Cloudflare's network and this dev box's path to both was already short.

**Decision.**

1. **`cloud_pipeline/run_cloud_job.py` mints the reel's UUID before uploading**, not after — `reel_id = str(uuid.uuid4())`, and the R2 object key becomes `reels/<reel_id>.mp4` (previously `jobs/<session_id>/highlight_by_rank.mp4`). Once presigning is gone, the object key *is* the entire access boundary, so it has to be exactly as unguessable as the reelId the share page is already gated on — a job/session-based key would let someone enumerate other venues' reels by guessing court/session names.
2. **That same id is threaded through unchanged**: `webapp/pipeline.py`'s `run_cloud_job` status wrapper carries `reel_id` into `status.json`; `cloud_pipeline/run_desktop_job.py`'s `_report_reel()` sends it as `id` in the `POST /api/agents/reels` body; the console's route accepts an optional client-supplied `id` and uses it as the row's own primary key instead of letting Postgres mint an unrelated one, falling back to the default when omitted (keeps the route working for anything still reporting the old way).
3. **`cdn.picvisionai.com`** is a Cloudflare custom domain bound to the `test-ingest-runpod` R2 bucket, with a Cache Rule (cache eligible, ignore query string, edge TTL). `reel-page/lib/r2.ts` and `pic-vision-cloud-console/lib/r2.ts` both replaced `presignedReelUrl()` with a plain `reelVideoUrl(bucket, key)` → `https://cdn.picvisionai.com/${key}`, no signing, no expiry, no SDK client. (`bucket` is unused inside the function for now — kept in the signature since only one bucket is bound to this domain today, not because a second is imminent.)
4. Both `lib/r2.ts` files still exist as separate per-repo copies (not shared across the repo boundary — an existing, deliberate choice, not new here).

**Consequences.** Verified end-to-end after deploy: `cf-cache-status` flips MISS→HIT on repeat fetch, CORS (`access-control-allow-origin: *`, set on the bucket earlier this session) carries over to the custom domain without extra config, and both `reel-page` and the console's video-redirect route serve the real reel through it. The Cloudflare-side setup (R2 custom domain attach, the cache rule, and both `console.picvisionai.com`/`share.picvisionai.com` DNS records for the same-day Netlify deploy) all had to be done by hand in the dashboard — every write attempted through the Cloudflare API in-session was blocked, either by Claude Code's own auto-mode classifier (the R2 domain attach) or by the API token's own read-only zone-write scope (the cache rule, the DNS records). A reel can no longer be "taken down" by revoking a signed URL's expiry (there wasn't a meaningful revocation story before this either, just a shorter unintentional window — deleting the `reels` row 404s the share page either way, but the R2 object itself was always fetchable by anyone holding a live presigned URL for up to its 1-hour window; a stable URL just removes that cap). Deliberately not addressed here: multiple buckets sharing one CDN domain, if that's ever needed.

---

## ADR-076 — A session can produce two reels (full + burst-moments); one shared page groups them via a new `share_id`, not either reel's own id

**Date:** 2026-09-04 · **Status:** accepted, implemented, not yet run against a real pod job

**Context.** Operator: "provide two forms of content, one is the one we have, the other only includes burst moments." `scripts/burst_moment_reel.py` already existed as exactly this — cutting each top-ranked rally's own peak-intensity window (`src/select.py`'s `peak_window`) instead of the whole rally, weights already tuned to not reward length (`0, 0.5, 0.5`) — but it was dev-only tooling, never wired into `cloud_pipeline/pod_cut.py`, the console, or the share page.

Two decisions were needed before touching code: (1) whether the burst reel should be a fully separate shareable artifact (own row, own page) or a second video bolted onto the existing single-reel-per-row shape — decided **separate row** (`kind` column, `'full'`/`'burst'`), since that's the shape `ADR-074`'s same-day "ranked-only reels" change had just simplified *to*, and every existing consumer's "one video per reel row" assumption stays true. (2) Where it runs — decided **cloud pipeline only** (`pod_cut.py`), not the local Flask webapp's route, since that's the actual product surface and the path already being tested end-to-end.

A third question came from the operator wanting the *share page* itself to show both as one page: "one session id, one share page... hero section as a soft carousel." The obvious candidate for grouping them — the existing `session_id` field — turned out unsafe to expose publicly: `desktop/electron/main.js` builds it from the camera label plus the recording's own timestamp (`"Court_4-2026-09-04T13-01-09-341Z"`), which is guessable, not random — using it as the share page's sole access gate would have quietly undone `ADR-075`'s entire point ("the id has to be as unguessable as it already was"). Confirmed the `reels` table's public read policy is `USING (true)` (fully open, gated only by the app already knowing a value to query on) — so grouping by a *fresh*, separately-minted random UUID needs no RLS change, only a new column.

**Decision.**

1. **`reels` gets two new columns**: `kind text not null default 'full'` (check constraint `in ('full','burst')`) and `share_id uuid not null` (backfilled to each existing row's own `id`, so every pre-existing single-reel share link keeps working unchanged). Indexed for the grouped lookup.
2. **`cloud_pipeline/run_cloud_job.py` mints a third UUID, `share_id`**, alongside the two reel ids (`reel_id` for full, a new `burst_reel_id`) — not reused from either reel's own id (that would make the page's identity depend on which kind happens to exist) and not `session_id` (unsafe, above).
3. **`pod_cut.py` runs both `build_reel()` (full) and `build_burst_reel()` (burst) on the pod**, independently — each recomputes its own detection pass rather than sharing intermediate state with the other; cheap CPU work, not worth coupling two already-separately-reviewed scripts for. Burst's own target duration is fixed at 30s (started at 60s, `burst_moment_reel.py`'s own CLI default, then shortened same-day after seeing real output), not the caller's full-reel `--target-sec` — a 300s target would mean 50+ five-second clips. `reel/stats.json` becomes `{"full": {...}, "burst": {...} | null}` — `null` when burst's candidate pool (identical detection to full) comes up empty, in which case there's no `burst/highlight.mp4` to upload at all.
4. **`run_desktop_job.py`'s `_report_reels()` (renamed from `_report_reel`) POSTs once per reel** in the result (1 or 2), all carrying the same `shareId`. The console's `/api/agents/reels` route accepts `shareId`/`kind`, falling back to `shareId = this reel's own id` and `kind = 'full'` when omitted (older callers).
5. **`share.picvisionai.com/r/[shareId]`** (renamed from `[reelId]`) queries every `reels` row with that `share_id`, oldest-first (full is always reported before burst, so it's always the first slide when both exist), and renders them as a horizontal scroll-snap carousel — a small badge per slide ("Full reel"/"Quick hits"), dot indicators, an `IntersectionObserver`-driven `activeIndex`. The Instagram/TikTok/Download tiles retarget to whichever slide is centered; Facebook/X/Threads/WhatsApp/etc and **Copy link** are unaffected (they all carry the one page URL, not a specific video). A new **Download all** button (after Copy link, per the operator's placement) shares every slide's video at once via a multi-file `navigator.share()`, falling back to sequential plain downloads if the browser doesn't support that.
6. Every slide's video is prefetched as a Blob **eagerly on mount, not lazily per-slide** — at most two short clips, cheap enough, and a lazy per-slide fetch would reintroduce the exact "awaited fetch mid-gesture misses Safari's activation window" bug this page's single-video version already hit and fixed the same day.
7. The console's Reels tab groups rows by `share_id` into one card per session (was one card per row) — a session's full/burst stats both show, but one "Open reel page" link now, since it's one page.

**Consequences.** Schema migration and all code changes (pipeline, console, share page) are in; `python3 -m pytest -q` (132 passed) and both Next.js apps' `tsc --noEmit`/`next build` are clean. **Not yet verified against a real pod run** — the next real cloud-pipeline test (sample-clip upload → calibrate → run) is what will confirm this end-to-end, including whether a real session's burst pool ever legitimately comes up empty in practice. `webapp/app.py`'s local dashboard preview route is deliberately untouched (still only ever shows the "full" reel) per the cloud-only scope decision above.

---

## ADR-077 — First real cloud→agent command channel: piggybacked on the existing heartbeat poll, not a new connection

**Date:** 2026-09-05 · **Status:** accepted, implemented; recording verified against a real camera the same day (see progress notes); the calibration line below is superseded by `ADR-080` the same day.

**Context.** `ADR-071` (2026-09-02) flagged this as the biggest concrete gap in the local-agent/cloud-console split: "nothing external can drive `desktop/`'s Node backend today — only its own Electron renderer can, via IPC." Everything built since (heartbeat, camera sync, reel reporting) is agent→cloud only. Operator, today: "the desktop client only allows to add/remove cameras/sample clip, everything else (calibrate, recording, etc) should be on the console." That's a partial reversal of `ADR-071`'s own "local agent keeps... recording... court calibration... can't move" list — worth being explicit about why part of that reasoning no longer holds: `ADR-071` said calibration "needs a live/local frame to click points on," but `PIC-75` (built the very next day) changed the flow to grab a snapshot first and click points on that static image — only the snapshot *grab* is LAN-bound now, not the point-clicking UI. Recording is a genuine split, not fully movable either way: the capture itself (ffmpeg pulling RTSP) can never leave the venue machine, but the start/stop *trigger* has no such constraint.

**Decision.** Built the recording half first (calibration's command types are a designed, not-yet-built follow-on — needs a second round-trip, see below).

1. **New table `agent_commands`** (`id`, `agent_id`, `camera_id`, `type` — `'start_recording'`/`'stop_recording'` for now, `status` — `'pending'`/`'done'`/`'error'`, `result` jsonb, timestamps). RLS: venue owners get `select`+`insert` scoped through the same `agents`→`venues.owner_user_id` chain every other agent-owned table uses; the agent side always goes through the admin/service-role client, same as `heartbeat`/`reels`.
2. **`POST /api/commands`** (venue-owner session) creates a command — looks up the camera's `agent_id` via `cameras`' own "venue owner reads own cameras" RLS (a camera_id belonging to someone else 404s naturally, no separate ownership check needed), inserts through the session client so `agent_commands`' own insert policy re-validates the same chain.
3. **`GET /api/agents/commands`** (bearer token) returns an agent's `pending` rows. **`POST /api/agents/commands/[id]`** (bearer token) reports `done`/`error` + a result, checked against the calling agent's own id (the admin client bypasses RLS, so this route enforces that by hand).
4. **No new connection or timer** — `desktop/electron/cloud.js`'s existing 30s heartbeat loop also calls `GET /api/agents/commands` on the same tick, executes anything pending by calling the *same* `capture.js` `startRecording`/`stopRecording` functions the desktop app's own button already calls, then reports the result. Consistent with `ADR-071`'s explicit "polling is fine, none of this is latency-sensitive like live video" call — not revisited here.
5. **Console UI**: the Cameras page's detail sheet gets a Start/Stop button (disabled for `sampleClip` cameras, which have no live stream). It just posts a command and waits for `is_recording` to flip on the camera's own next heartbeat sync — no separate faster poll invented just for this button.

**Consequences.** `python3 -m pytest -q` unaffected (no Python touched); both Next.js apps' `tsc --noEmit`/`next build` clean. Verified against a real camera the same day (see progress notes): clicking Start on a live camera from the console started real `ffmpeg` on the desktop agent within one heartbeat cycle. The desktop app's own recording button came out of `desktop/` the same day too, per `ADR-080` — not kept in both places.

**Calibration stays on the desktop app, operator's call (2026-09-05), not migrated** — **superseded the same day by `ADR-080`**, once the operator revisited this specific call and asked for calibration to move too. The two-round-trip `grab_calibration_snapshot`/`apply_calibration` design sketched above is exactly what `ADR-080` built.

---

## ADR-078 — Desktop app gains a mandatory account sign-in gate, separate from (not replacing) device pairing

**Date:** 2026-09-05 · **Status:** superseded by `ADR-079` the same day — point 3 ("pairing is untouched") turned out to be unnecessary, not just imperfect; the rest of this ADR (sign-in itself, `getBrand()`, the render gate) still stands as built.

**Context.** `desktop/` has never had any concept of a user account — `ADR-071` explicitly flagged "a real multi-tenant database and auth system... zero user accounts anywhere" as an open gap, and the only identity mechanism built since (`electron/cloud.js`) is a short-lived pairing code that links one specific machine to a brand's `agents` row, with no credential ever entered on the desktop app itself. Operator asked for a sign-in page on launch that "pulls the relevant data associated to each attribute" once authenticated. Raised and resolved before building: what happens for a brand with multiple locations, each running its own desktop agent? `brands.owner_user_id` is unique (one brand per account, confirmed via the live schema), while `agents.brand_id` is one-to-many — multiple agents per brand is already the multi-location model, driven entirely by pairing (each location's machine gets its own pairing code from the console, its own `agents` row). Sign-in and pairing answer different questions: sign-in is "who is operating this machine," pairing is "which location is this machine." Conflating them (e.g., auto-creating an agent row straight from sign-in with no pairing step) would have broken that story — two machines signed into the same brand account would need some other way to stay distinct locations.

**Decision.**
1. **`electron/auth.js`** signs in directly against the same Supabase project `pic-vision-cloud-console` uses (its public project URL/anon key, already committed in that repo's `.env.local.example` — safe, not a secret), via the plain Auth REST password grant (`POST /auth/v1/token?grant_type=password`) — no `supabase-js` dependency added, consistent with `cloud.js`'s existing plain-`fetch` style. Session (access/refresh token, user id/email) is stored locally via `electron-store`, refreshed 60s ahead of expiry on demand, and never returned to the renderer in full — only `{user, expiresAt}` crosses the IPC boundary.
2. **`src/pages/SignInPage.jsx`** gates `App.jsx`'s entire render (below the title bar, which stays interactive so the frameless window can still be closed pre-auth) — no session, no app, full stop.
3. **Pairing is untouched** — `CloudPage.jsx`'s existing pairing-code flow still runs after sign-in, for exactly the same reason it existed before: it's what makes this specific machine one distinct, nameable agent/location under the signed-in account's brand, and what a second venue's machine would do differently (same account sign-in, its own separate pairing code).
4. **What sign-in actually newly unlocks**: `getBrand()` reads the signed-in user's own `brands` row directly (RLS policy `auth.uid() = owner_user_id`, confirmed live against the schema), letting the sidebar show the real brand name even before this device is paired — previously that name only ever came from `cloud.js`'s post-pairing heartbeat, so a fresh, unpaired install showed nothing. Camera data itself is untouched: still local-only (discovery/manual-add/sample-clip), still pushed to the cloud via the existing per-agent heartbeat — deliberately not fetched from the cloud on sign-in, since a camera's connection details are LAN-bound and agent-scoped by design (`ADR-071`), and pulling a brand-wide camera list would leak one location's cameras into another's UI.

**Consequences.** A brand with N locations means the same account credentials get typed into N desktop installs, each still separately paired — unchanged operationally from today, just gated behind a login first. Nothing here touches `cameras`/`agents` RLS or schema. Known gap, same class already flagged for camera passwords (`cameras/store.js`): the session is stored in plain `electron-store` JSON, not OS-keychain-backed — acceptable for this POC, not for a real multi-operator rollout.

---

## ADR-079 — Device registration happens automatically on sign-in; the pairing-code flow is removed, not just supplemented

**Date:** 2026-09-05 · **Status:** accepted, implemented, verified end-to-end against real infra

**Context.** Same day as `ADR-078`, operator asked directly: "do i even need a log in? the idea is that once i log in, after adding the cameras, the backend knows what to display on the cloud console." That's a fair challenge to `ADR-078` point 3's "pairing is untouched" call — walking through it exposed that the pairing code wasn't actually proving anything sign-in doesn't already prove. `brands.owner_user_id` is unique (one brand per account), so the moment a device signs in, the backend already knows exactly which brand it belongs to. The pairing code's only remaining job was minting *this device's own* `agents` row — and that's a mechanical step (find-or-create by `device_id` under the caller's own brand), not something that needs a human to generate a code on one screen and retype it on another.

**Decision.**
1. **New route `pic-vision-cloud-console/app/api/agents/register`**, authenticated by a raw Supabase access-token bearer header (not a cookie session — the caller is the desktop app) via a new `lib/supabase/bearer.ts` client. Deliberately *not* the service-role admin client, matching `lib/supabase/admin.ts`'s own header warning against using it for a request that's really a signed-in owner acting on their own data — RLS (`auth.uid() = owner_user_id` / `brand_id in (owner's brands)`) is the real access boundary here, same as every cookie-authenticated console route.
2. **Same find-or-create-by-`device_id` reclaim logic `/api/agents/pair` had**, just keyed off the authenticated user's own brand instead of a pairing-code lookup: an unrecognized `device_id` gets a new `agents` row, a known one gets its token rotated (the old plaintext can't be recovered from its stored hash to hand back unchanged, and if the caller lost track of it, nothing else could still be relying on it).
3. **`electron/auth.js`'s `signIn()` calls this automatically** right after a successful password grant, but only if `getCloudConnection()` is currently null — re-signing in on an already-registered machine doesn't rotate its token or touch its `agents` row. A `registerDevice()` retry also runs at app startup (`main.js`) for a device that's signed in but never successfully registered (e.g. the console was unreachable at sign-in time), and `CloudPage.jsx` offers the same retry by hand.
4. **The pairing-code mechanism is deleted, not deprecated-in-place**: `/api/agents/pair` and `/api/agents/pairing-code` routes, `generatePairingCode()`, and the Settings page's "Pairing code" utility tab are all removed — `desktop/electron/cloud.js`'s `pairAgent` is gone too, replaced by `registerAgent(accessToken)`.

**Multi-location, addressed explicitly (this is what the operator's question was really asking):** a brand with two venues still ends up with two distinct `agents` rows — nothing about that changes. What changes is *how* each one gets created: the operator signs in with the same account on each location's machine, and each machine's own locally-generated `device_id` is what keeps them distinct, not a manually-relayed code. Verified directly, not just reasoned through: registering two different `device_id`s under one signed-in session produced two separate `agents` rows under the same brand; re-registering the same `device_id` reused its existing row and only rotated its token.

**Verification.** Ran the full flow against real infra before calling this done, not just read the code: a throwaway, pre-confirmed Supabase user was created via the admin API, signed in through the actual password-grant endpoint, and used to call the new route against a local `next dev` server three times — create, reclaim (same `agentId`, rotated `apiToken`), and a second `device_id` (distinct `agentId`, same brand). All three passed. Test user, brand, and both agent rows were deleted afterward — nothing left behind in the shared project. Separately, the real already-running desktop app (signed in as the actual operator account, already connected from a pre-ADR-078 pairing) surfaced one real regression: `CloudPage.jsx` was renamed to read `connection.connectedAt`, but that operator's already-stored local connection JSON still had the old field name (`pairedAt`), so it rendered "Registered Invalid Date." Fixed with a fallback (`connection.connectedAt ?? connection.pairedAt`) rather than a migration step, since this is local, disposable POC state.

**Consequences.** `desktop/README.md` and `ADR-078`'s own status line updated to point here. No pairing code exists anywhere in the system anymore — a device that can't reach the console at sign-in time has no manual fallback beyond CloudPage's retry button (calling the same automatic path again), which is judged sufficient for this POC's scale (one operator, few venues) but wouldn't be if pairing needed to happen without ever unlocking the full app (e.g. a kiosk-mode install) — not a currently real requirement.

---

## ADR-080 — Recording and calibration controls move to the cloud console; desktop keeps only the LAN-bound halves

**Date:** 2026-09-05 · **Status:** accepted, implemented, verified end-to-end against real infra (not a real camera — see Verification)

**Context.** Operator: "i dont think i want users to calibrate and record on desktop client. they should be performing those tasks on cloud console." Recording already had a console-side control path (`ADR-077`, built and verified against a real camera earlier the same day) — the desktop's own local Start/Stop button was a redundant second way to do the same thing, and `ADR-077`'s own "Consequences" section had already flagged removing it as the next step. Calibration was a real reversal: `ADR-077` explicitly scoped it *out* the same day ("scoped out, not just deferred... the permanent home for it"), reasoning that clicking 14 points needs no LAN access (`PIC-75` already made it snapshot-first) but that a second command round-trip wasn't worth building yet. The operator's new request superseded that call.

Checked before building, not assumed: `save_calibration.py` (the homography fit) needs the snapshot file on local disk to run, and `pipeline.js` requires a real local file path (`--calib <path>`, `existsSync`-checked) to invoke a job — so the finished `calib.json` can't be R2-only, confirmed directly with the operator when they asked "can the calibration file be sent directly onto R2?" The snapshot travels desktop→R2→console; the math still runs on the desktop (unchanged Python); the finished file gets an *additional* R2 backup for durability, but the local copy stays authoritative.

**Decision.**
1. **Recording**: `desktop/src/pages/CameraDetailPage.jsx`'s `RecordingControl` becomes read-only (still polls and shows elapsed time/save path, no Start/Stop buttons). `captureAPI.start`/`stop`, their IPC handlers, and the now-unused `startRecording`/`stopRecording` imports in `main.js` are removed outright, not left as dead code. The console's existing Start/Stop control (`ADR-077`) is untouched.
2. **Calibration — schema**: one migration on `agent_commands` — widened the `type` CHECK to add `grab_calibration_snapshot`/`apply_calibration`, and added a `params jsonb` column (console→agent command input; the existing `result` column is agent→console output only, and had no home for the 14 clicked points `apply_calibration` needs to send down).
3. **New `cloud_pipeline/upload_calibration_snapshot.py`**: a thin CLI wrapping the already-generic `r2_storage.upload_file` — no Node/boto3-equivalent client written, same "invoke the existing Python as a subprocess" convention `calibration.js` already follows for `save_calibration.py`. Snapshot keys are random UUIDs (`calibration-snapshots/<uuid>.png` — ADR-075's "the object key is the entire access boundary," and a calibration snapshot has no reason to be guessable the way a shareable reel does); the backup key is stable per camera (`calibration-backups/<camera_id>.json`, meant to be overwritten each recalibration).
4. **`desktop/electron/calibration.js`** gains `grabAndUploadSnapshot(camera)` (grabs + uploads, tracks the still-needed local snapshot file in a module-level `Map` keyed by camera id instead of discarding it immediately — the gap until the operator finishes clicking on the console is now human-paced, not modal-lifetime-paced, with a 15-minute sweep for abandoned attempts) and `applyPendingCalibration(camera, points)` (calls the **unmodified** `saveCalibration`, then best-effort backs the result up to R2). `desktop/electron/cloud.js`'s `runCommand` gets two new branches following its existing flat-dispatch shape; the sample-clip recording guard moved to only gate the two recording command types, since a sample clip can absolutely be calibrated (`takeCalibrationSnapshot` already seeks into the file for that case).
5. **Console**: `/api/commands` accepts the two new types plus an optional `params` field (validated as exactly 14 `[x,y]` pairs for `apply_calibration`); `/api/agents/commands` now selects `params` too. A new `CalibrationModal` in `cameras-client.tsx` is a direct port of the desktop original's click-scaling math and SVG point overlay, polling `agent_commands` directly (browser client, already RLS-readable) instead of using IPC. `.dialog*` CSS classes, present in desktop's "Nocturne" system but never ported to the console's, were added verbatim (same precedent as `.btn`/`.field`/`.input`/`.radio`).
6. **Desktop keeps** `CalibrationControl`'s "Import file…" fallback (`pickCalibFile`) — a local-filesystem recovery path, not "performing calibration" the interactive way, and it needs to stay local since it reads a file the console has no access to. `CalibrationModal` (the 14-point clicking flow) and its trigger button are removed from desktop entirely.

**Verification.** `python3 -m pytest -q tests/` (132 passed, unaffected — no Python logic changed beyond the new thin upload script and an unmodified `save_calibration.py`/`saveCalibration` call site); `npx tsc --noEmit` clean in `pic-vision-cloud-console/`. Live-infra checks, all using synthetic/throwaway data, never a real camera (per the standing "no live camera snapshot testing" rule — neither configured real camera is confirmed pointed at an actual court): (1) `upload_calibration_snapshot.py` against a synthetic test image, round-tripped through the real R2 bucket and `cdn.picvisionai.com`, confirmed byte-identical and correctly `image/png`; (2) `save_calibration.py` invoked directly with synthetic points against that same image, confirming the exact stdin/CLI contract `applyPendingCalibration` uses; (3) a full browser-driven UI run (throwaway Supabase test account, a fake registered agent/camera, a script standing in for the desktop's heartbeat loop but running the *real* Python scripts) — signed in, opened the fake camera, clicked Calibrate, watched a real snapshot load from R2 in the browser, placed 14 real mouse clicks, saved, and got a real reprojection-error result back, all through the actual `/api/commands`/`/api/agents/commands` routes and the real `agent_commands` table. All test rows/objects/auth users deleted afterward. **Not verified**: the real Electron-integrated code path in `desktop/electron/calibration.js`/`cloud.js` (the Map-based pending-snapshot tracking, the real heartbeat dispatch) — deliberately not run against the operator's actual live app in this session, since that would have required either redirecting their real, currently-connected desktop agent away from production or deploying this to production first; both are real next steps, not yet done.

**Consequences.** `TECH_SPEC.md` §12 and `desktop/README.md` need updating in this same change per repo convention (see next entries). Calibrating now costs two command round-trips (up to ~30s agent heartbeat + a few seconds of console polling, each) instead of an instant local modal — the same latency trade-off `ADR-077`'s recording control already established and the operator already accepted there. Nothing here has been deployed: the console changes are local/uncommitted, and the operator's live desktop app is still running pre-`ADR-080` code until both sides are shipped and it's restarted.

---

## ADR-081 — Desktop app's remaining mock pages resolved: Credentials removed, Alerts replaced by a real Log, Scan settings made real

**Date:** 2026-09-05 · **Status:** accepted, implemented, verified against the operator's real running app

**Context.** Same session as `ADR-080`, continuing the theme of the desktop app doing only what's real. Three separate operator requests, handled one at a time but sharing one throughline: "credentials" as a page never corresponded to anything (no stored-credential-set feature exists or was asked for), "alerts" was pure Claude Design mockup with zero backend, and "scan settings" was mostly mockup too but — checked directly before assuming — two of its four panels actually mapped onto real, already-existing parameters (`networkSweep.js`'s `sweepNetwork` already took an arbitrary `cidr` and a `timeoutMs`; only a single auto-detected range and a hardcoded `400` were ever passed in).

**Decision.**
1. **Credentials removed entirely** — `CredentialsPage.jsx`, its nav entry, and `MOCK_CREDENTIALS` deleted outright, not left disabled. The Cameras page's bulk-select dialog (which referenced "the Credentials page's stored credential sets") now says plainly that no such feature exists.
2. **Alerts replaced by a real "Log"** — new `electron/activityLog.js` (capped-200, `electron-store`-backed, same per-concern convention as `cameras.json`/`cloud.json`/`auth.json`), with `logEvent()` calls added at the real signal each event type already represents: camera online/offline transitions (`cloud.js`'s existing 30s `cameraStatuses()` poll, previously discarded every tick), recording started/stopped/failed (`capture.js`), calibration completed/failed with the real reprojection error (`calibration.js`), cloud pipeline jobs started/finished/failed (`pipeline.js`, logged directly in the job process's own `exit` handler rather than a separate poll — simpler and more immediate than the originally planned "check on the next heartbeat tick"), cloud console connect/disconnect (`cloud.js`), and sign-in/out (`auth.js`). Went through the mockup's original 5 sample alerts one by one before deciding scope: 2 mapped onto a real signal, 1 depended on the just-removed Credentials feature, 1 needed a per-vendor firmware-update-check capability nothing here has or could get generically, and 1 named a real but *different* existing concept (`scripts/check_drift.py` detects camera-mount movement, not the mockup's NTP clock-sync idea) — automating that script is real new scope, left out of this pass. Pipeline logging deliberately reports only start/finish, not every intermediate stage (confirmed with the operator) — that detail already lives in `CameraDetailPage.jsx`'s live `CloudJobRow` progress row; repeating it in a history log would be noise.
3. **Scan settings made real, narrower than the mockup** — new `electron/scanSettings.js` persists extra RTSP-sweep ranges and the per-address timeout; `cameras:sweep`'s handler now sweeps the auto-detected primary range plus every saved extra range, merging hits and treating a bad/oversized extra range as best-effort (logged and skipped, not allowed to fail the whole scan). Two mockup panels dropped entirely rather than left disabled: the protocol checkboxes (4 of 7 don't exist in code — mDNS/Bonjour, SSDP/UPnP, vendor probes, RTSP stream probe — and the 3 real ones already run unconditionally with nothing to toggle) and the scan-cadence radios (auto-scan-on-launch was already explicitly removed once, 2026-09-03, "operator's call" — rebuilding it as a setting would quietly reopen that decision). Extra ranges only ever extend the RTSP sweep, never ONVIF WS-Discovery, which is multicast and can't reach a different subnet regardless of configuration — the UI says so directly rather than implying otherwise.
4. **`mockData.js` and `PreviewBanner.jsx` deleted** — once Settings' real panels replaced its mock ones, nothing left imported either.

**Verification.** All three changes restarted and checked against the operator's real, currently-running desktop app (still signed in, real cameras, real cloud console connection) — not just unit-level: triggered a real calibration on Court 3 through the console and confirmed the resulting "Calibrated Court 3 — reprojection error X ft" entry appeared in the real Log tab (then cleared via the real "Clear log" button and the camera's real `calib.json` restored from backup, since the test used synthetic points); added/removed a real extra scan range and changed the real timeout, then ran an actual "Scan" and confirmed it swept both ranges together without error (then removed the test range and restored the default timeout).

**Consequences.** `TECH_SPEC.md` §12 and `desktop/README.md` updated in the same change. The desktop app's page set is now fully real or fully gone — no illustrative/mock page remains (Alerts/Credentials/Settings were the last three). Not yet deployed/committed at time of writing this entry.

---

## Template

```markdown
## ADR-NNN — <short imperative title>

**Date:** YYYY-MM-DD · **Status:** accepted

**Context.** What situation forced a choice? Include the number or observation that mattered.

**Decision.** What was chosen.

**Consequences.** What this costs, what it rules out, and what would make us revisit.
```
