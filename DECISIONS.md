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

R2 is the more architecturally attractive of the two for this project specifically, since it solves both legs (proxy in, highlight out) from one account instead of splitting storage between RunPod's Network Volume and a separate delivery bucket (`ADR-043`'s original plan used plain S3 for that leg). Not yet built or tested either way — this note exists so the next attempt starts from the real, now fully-checked mechanism instead of re-discovering (or re-mis-discovering) it a third time.

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

## Template

```markdown
## ADR-NNN — <short imperative title>

**Date:** YYYY-MM-DD · **Status:** accepted

**Context.** What situation forced a choice? Include the number or observation that mattered.

**Decision.** What was chosen.

**Consequences.** What this costs, what it rules out, and what would make us revisit.
```
