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

## Template

```markdown
## ADR-NNN — <short imperative title>

**Date:** YYYY-MM-DD · **Status:** accepted

**Context.** What situation forced a choice? Include the number or observation that mattered.

**Decision.** What was chosen.

**Consequences.** What this costs, what it rules out, and what would make us revisit.
```
