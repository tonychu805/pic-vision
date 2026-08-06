# Experiment Log

Append-only. Newest at the bottom. One entry per run that produced a number or changed a conclusion.

The point is to stop re-learning things. If a weight sweep or a threshold change didn't help, that fact is worth more written down than remembered.

**Rules**

- Record the number even when it's bad. Especially when it's bad.
- Record what you *expected*, before the result. A surprise is the useful signal.
- One entry per change. Two changes at once means you learn nothing from either.
- If an entry produces a durable decision, add an ADR to `DECISIONS.md` and link it here.

**Template**

```markdown
## YYYY-MM-DD — <what changed>

**Hypothesis.** What I expected and why.
**Setup.** Dataset, config, commit.
**Result.**

| Metric | Before | After |
|---|---|---|
| Rally recall | | |
| FP / 10 min | | |
| Boundary err | | |

**Conclusion.** Kept / reverted, and what it means.
**Follow-up.** Next thing to try, or ADR filed.
```

---

## Pending — Phase 0 baseline measurements

Nothing recorded yet. These are the first numbers to produce, in order. The first one gates the project (see `PRD.md` §9 Q1).

| # | Measurement | Why it matters | Target |
|---|---|---|---|
| 1 | **Stopped-marker purity.** For each *stopped-play* marker (ADR-026 / ADR-037), count how often it fires *during* a labelled rally on `dev-set-B`, broken out by the known confounders: **lob / wide-shot retrieval** (trips "left the court"), **dinking** (trips "all stationary"), **courtesy returns**. | **The gating experiment** (ADR-026, evolved by ADR-037). Single markers are context-ambiguous; this measures how ambiguous each is. | Net crossing: < 1% of rally samples (trustworthy alone). "Left court" / "all stationary": measured — a high rate means the marker needs live-marker corroboration, not that the design is dead. |
| 1b | **Live-marker purity + coverage.** For each *live-play* marker (ADR-037): how often it fires during a rally (want high) vs. during dead time (want low). Key sub-question: can the **ball-free** live markers (motion, kitchen ready-stance, pose) separate a **dink** from dead time? | A two-sided model only works if the live markers actually discriminate the hard cases. Dinks are low-motion, so the ball may be the only clean live signal. | Live markers fire in > 80% of rally samples, < 10% of dead time. If dinks can't be separated without the ball, ball presence moves earlier than Phase 2. |
| 1c | **Is the recording's audio usable?** Onset density during a labelled dead-time stretch, plus a spectrogram of a known rally by eye. | Determines whether Phase 2.5 happens. **No longer gates the project** (ADR-004) — audio contributes boundary precision only. | Visible transients at impact; near-zero onsets during dead time. Contamination → weight 0. |
| 2 | **Confirm 30 fps CFR once.** Record a 30 s probe, check `nb_read_frames / duration` and the PTS-delta histogram. | The camera is set to a fixed 30 fps (ADR-025). This is a one-time confirmation, not a per-session gate — but worth doing once, since a setting is a request and this camera has surprised us before. | ~30 fps, uniform ~0.0333 s deltas. Then settled. |
| 2b | Audio codec, sample rate, channels from the same recording | Prerequisite for the optional audio path only (§5.1b) | Present, ≥ 16 kHz |
| 3 | VideoToolbox decode throughput, 1080p → 480×270 @ 5 fps sampling | The dominant T0 cost. Validates or breaks the `TECH_SPEC.md` §9 estimate of 4–7 min. | < 10 min per 2 h session |
| 4 | YOLOv8n throughput, CoreML/ANE vs Metal, ROI crop at ~1280 px | Decides whether T1 stays local. The 2–4× CoreML advantage is an assumption. | ≥ 15 fps effective |
| 5 | Sustained-load thermal behaviour over a full session | Fanless machine; the 20–40% throttle allowance is a guess | Documented, not exceeded |
| 6 | End-to-end T0 wall clock on `eval-set-A` | The headline runtime claim | ≤ 0.5× source |

Once these land, replace the `TECH_SPEC.md` §9 table with measured values and note the delta here.

---

## Pending — Phase 0.5 prior-art benchmark

Per ADR-021. Prior art is catalogued in `TECH_SPEC.md` §2. **None of these projects publishes an accuracy number**, so every claim below is currently unverified — that's the point of measuring.

| # | Measurement | Why it matters | Decision it drives |
|---|---|---|---|
| 7 | **vinod-polinati scored on `eval-set-A`** — recall, FP/10 min, boundary error | It implements roughly Phases 1–2 already. Its README reports "87 rallies found" with no ground truth. | Do we improve it, replace it, or adopt it? |
| 8 | Its wall clock on the M2 | YOLOv8x every frame is ~1 TFLOP/frame — expected to be hours, not minutes | Whether the approach is viable locally at all, or needs a smaller model |
| 9 | Same, with YOLOv8**n** or **s** substituted at `imgsz=1280` | Isolates how much of its performance comes from model size versus resolution | Model size for §5.3.1 |
| 10 | **Ball-presence-only recall** — binary "ball visible" as a rally signal, no trajectory | Tests ADR-022 directly | Whether Phase 3 is needed at all |
| 11 | Detection rate at `imgsz` 640 vs 960 vs 1280 on our own footage | Tolone reports 60% → 100%; does it replicate on a C200 at our mount? | Confirms or breaks the ADR-005 revision |
| 12 | **Roboflow dataset assessment** — image count, class list, licence, and above all camera angles | A domain-mismatched dataset is worse than none | Whether Phase 3 labelling can be skipped |

Measurements 7 and 10 are the high-value pair. If prior art already clears the PRD targets, the remaining work is selection and ranking — which nobody else has built.

---

## Pending — signal ablation

Run once the Phase 1 pipeline exists. Settles by measurement what has so far been settled by argument.

| # | Measurement | Why it matters | Decision it drives |
|---|---|---|---|
| 13 | **Three-way ablation on `eval-set-A`:** video-only, audio-only, fused | The relative value of each modality is currently an assumption. Audio was demoted on a structural argument about spatial selectivity (ADR-004), not on data. | Whether audio earns Phase 2.5 at all |
| 14 | Feature ablation — drop each §5.2.2 feature in turn, remeasure | Direction-reversal rate and bilateral coupling are hypotheses. Some may contribute nothing. | What to delete. Dead features in a pipeline are a liability. |
| 15 | **Courtesy-return false-positive rate**, before and after the ≥ 2 side-alternation rule | Systematic, not rare — one after every point (ADR-028) | Whether that single rule is sufficient |
| 16 | Boundary error from each route independently: dense-sampling windows, ball side-alternation, gated audio | Three independent routes to precision; the system needs none of them individually | Which to keep. Possibly only one is needed. |
| 17 | Warm-up misclassification rate | Indistinguishable from play by every available signal. Accepted, not solved — but the size of the problem is unknown. | Whether to trim opening minutes by default |

Measurement 13 is the one to run first. If video-only already clears the targets, audio can be deleted from the codebase entirely rather than carried as optional complexity.

---

## 2026-08-06 — Preliminary marker read on a broadcast clip (dev-scaffold, NOT eval)

**Not an eval result.** One 53 s clip from a PPA broadcast (`austin_rally2`, the fixed "deep court" cam), 3 hand-labelled rallies, pro doubles. Domain-mismatched to the target rig — numbers are directional only, and the pipeline itself is the point, not the accuracy.

**Hypothesis.** Player *motion* separates rallies from dead time; where motion is low (expected: dinks), a *kitchen-formation* position marker rescues them.

**Setup.** YOLOv8n person detection @5 fps → foot point → court coords (calibration RMSE 0.123 ft) → on-court filter (89% of frames = exactly 4 players). Markers: tracking-free mean player motion; players near the NVZ lines. Scored against the labels. Commit `947966b` (branch `feat/detection`).

**Result.**

| Signal | Rally | Dead | Separation |
|---|---|---|---|
| Motion (ft/s) | median 4.2 | median 3.0 | heavy overlap; no clean threshold (th=4 → 53% rallies / 32% dead called live) |
| Players at kitchen | mean 1.61 | mean 0.39 | present but weak |

The low-motion rally frames (n=25) turned out **not to be dinks** — players sit *behind the baselines* (y ≈ −3 and ≈ 50): serve/return setups. The kitchen marker rescued only 4% of them.

**Conclusion.** Single position/motion markers are weak, and the hard rally moments on this clip are **serves**, which are positionally near-identical to dead time (players still, near the baseline). Consistent with ADR-037 (no marker decides alone) and hints the **ball/pose may be needed earlier than Phase 2** for the still moments. Not a verdict — tiny non-domain sample; stopped here to avoid overfitting to one clip.

**Follow-up.** The real read is measurements 1/1b on raw single-camera footage. Carry "does the ball need to move earlier?" as a live hypothesis.
