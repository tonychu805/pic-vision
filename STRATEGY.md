# STRATEGY — Beyond the Prototype

**Status:** Exploratory · **Owner:** Tony · **Last updated:** 2026-08-12

**Nothing in this document is committed.** It records the direction and the open questions from a design conversation about what a multi-venue product *could* look like, so the thinking isn't lost. The prototype ([`PRD.md`](./PRD.md)) gates all of it — specifically the Phase 0.6 result. If the core detection signal doesn't hold on one mount, most of this is moot. Venue deployment is "a different product, not a port" (`PRD.md` §10), and this document does not change prototype scope.

Companion documents: [`PRD.md`](./PRD.md) · [`TECH_SPEC.md`](./TECH_SPEC.md) · [`DECISIONS.md`](./DECISIONS.md)

---

## 1. Thesis

The thing being built is, in substance, a **pickleball video-annotation pipeline**. The sellable outputs — highlight reels first, player movement analytics later — ride on top of a library of labeled footage. Detection is table stakes; the durable asset is the data and the judgment baked into it.

This reframes where effort and defensibility live, and most of the sections below follow from it.

---

## 2. The moat (open question)

**Assumption to challenge:** the detection *model* is not the moat. Person detection is off-the-shelf and generalizes across venues unchanged; mapping camera pixels to court coordinates is commodity geometry. A technical reviewer reproduces both quickly.

Candidates for what is actually defensible:

- **The multi-venue labeled corpus** — rally boundaries, and eventually "was this rally good to watch," across many venues and angles. Slow and expensive to build; everything trainable is downstream of it.
- **The highlight-ranking / watchability model** — deciding which rallies are worth watching. `PRD.md` §10 already notes this is the part "nobody else has done."

**Open question:** which of these is the real moat, and is it worth building the company around the annotation pipeline that produces it? This is the central strategic question and it is not yet answered.

---

## 3. Detection foundation

**Superseded 2026-08-13 by [`DECISIONS.md`](./DECISIONS.md) ADR-047** — the direction below was overtaken by results: full-video TrackNet ball detection is now the primary and current segmentation signal, and player-tracking is deferred (frozen, not the foundation). ADR-047 exists specifically to reconcile this doc with the code; that reconciliation happened there, not here, so the paragraphs immediately below are kept as the historical rationale for the *original* direction, not the current one. See §8 for what player-tracking still unlocks once revisited.

**Original direction (superseded):** player-tracking is the foundation; the ball is a *refinement*, not a dependency.

- Rally *segmentation* runs on player signals (position relative to court, motion, and — where reliable — pose). The ball is untrackable in many conditions and expensive at scale.
- The ball, when used, sharpens boundaries and cuts false positives, and it only needs to run on the **selected clips** (~10 min), never the full session. This removes ball tracking from the throughput-critical path.

**The two gating confounders** (pickleball-specific, and the reason this is not a solved problem):

- **Dink rallies** — slow kitchen exchanges where players barely move, so a motion-based "play has stopped" marker misreads live play as dead time.
- **Courtesy returns** — the tap-back after a point looks like a short rally; the false positive the detector most needs to reject.

Both are exactly what Phase 0.6 now measures explicitly. If player-only markers can't separate these at real camera geometry, no amount of pose models or learned sequence models rescues the approach.

**Maturity note:** a hand-built state machine over position/motion (no training data) is the *starting* form. A learned temporal sequence model over player features is the *later* form, and it depends on the labeled corpus in §2. Don't skip to the learned model before the data exists.

---

## 4. Multi-venue architecture (directional)

**Shape:** one universal segmentation model operating in **court-normalized coordinates**, plus **per-venue calibration**. Calibration absorbs each camera's geometry; the model learns the venue-invariant behavior of a rally.

**What calibration does *not* normalize** — and therefore what still causes domain shift venue to venue:

- Lighting (indoor vs. outdoor — the daylight requirement doesn't go away)
- Occlusion geometry (camera height/angle differ even after the court is mapped)
- Ball visibility
- Audio

So "universal" is honest for court-plane player *positions* and a fiction for appearance, occlusion, ball, and sound.

**Court calibration at a new venue:** auto-detect the court lines to propose an outline, then **a human confirms or nudges** — never blind auto. Because calibration is once-per-mount and everything downstream depends on it, the asymmetry (catastrophic-if-silently-wrong vs. 30-second confirm) argues against full automation until customers self-serve. A court is the same shape everywhere, so a single court-detector is the one place "universal model" cleanly applies. Auto-detection's better first job may be the **per-session drift check** ("has the camera moved since calibration?").

**Angle generalization (progressive):** start by *insisting* on the behind-baseline mount. Expand support **one angle category at a time** (behind-baseline → elevated-corner → side-on …) as labeled footage for each category accumulates. "Any angle" is really "enough coverage of the common angle categories." Collecting other-angle footage can begin before support ships — capture now, label later, enable when a category has enough data.

**Open questions:** does player-only segmentation survive non-baseline angles at all? How much labeled data does a new angle category need before it works?

**Side-on/courtside note (2026-08-24, business interest flagged, no footage yet):** a courtside-at-midcourt mount is plausibly *easier* to sell into venues than the current behind-baseline one (no equipment behind the baseline in the ball's path, more of a "watching the match" viewer perspective for the eventual product) and, encouragingly, looks like the cheaper of the two non-baseline angles to actually support. The current ball-crossing signal (`src/ball.py`) is hard-coded to a behind-baseline assumption (net-crossing is a comparison against a roughly constant image-*y*); a side-on view rotates that 90° — net-crossing becomes an image-*x* comparison instead, the same math with an axis swap, not the full court-space rewrite an elevated-corner angle would need. Calibration should be unaffected (a courtside view sees the full court outline at least as well as behind-baseline). The real unknown is ball *occlusion*: a side-on view looks at players edge-on rather than face-on, so a player's body sits between the camera and the ball far more often during net exchanges — untested, needs real footage to check before this angle can be trusted, same as any other new angle category above.

---

## 5. Deployment (directional)

**Batch, not live.** One highlight produced per booking (~2 hours), per court, delivered within ~30–60 minutes of the booking ending.

**Hardware options, ordered by cost vs complexity:**

| Shape | Hardware | Cost | Cloud bill | Notes |
|---|---|---|---|---|
| **N100 + cloud GPU** (preferred POC) | N100 mini PC, ~$150–300 | Low | ~$0.011/session | Proxy video trick: 720p to cloud, cut from local full-res. See ADR-043. |
| **All-local, Jetson** | Jetson Orin NX/AGX | ~$500–800 | None | TensorRT inference; fleet management (OTA) is the ops burden |
| **All-local, Mac mini** | Apple Silicon Mac mini | ~$600–800 | None | Zero-port from prototype; CoreML ANE; same pipeline, no code changes |

**One box per court** (resilience, simple wiring, natural per-court output). SwingVision runs this class of analysis on a phone — compute is not the constraint. This class of single-camera analysis runs on-device, which keeps footage local, consistent with the privacy stance.

**The 30-minute question decides the architecture:**

- The prototype's own budget (≤0.5× source) processes a 2-hour session in ~1 hour — so *post-hoc* processing **misses a 30-minute target by ~2×**.
- **Option A (post-hoc, ~1 hr delivery):** simplest; existing pipeline unchanged; cheapest box. Fine if "within the hour" is acceptable.
- **Option B (rolling, <30 min delivery):** run player-only detection *during* the game so only selection + ball-refinement + cut remain at the whistle. Requires: **recording kept sacred and fully decoupled from analysis** (if analysis crashes, the video survives and you fall back to Option A), progress checkpointed, and detection tags aligned to the recording's PTS. Worth the extra engineering *only* if 30 minutes is a firm, differentiating promise.

**Go/no-go benchmark:** can one candidate box hold real-time player tracking on one stream (Option B), or process a 2-hour file fast enough (Option A), on *real* footage? Ball tracking on the full stream is deliberately avoided; ball runs post-hoc on ~10 min of selected clips.

**Cost shape:** local = low, linear per-court hardware + a **fleet-operations burden** (monitoring, updates, remote debugging across venues). Cloud = low hardware but a recurring GPU bill plus the data-processing/privacy relationship the privacy stance exists to avoid. Batch + privacy + single-camera all point local/on-device.

**Option B, made concrete (2026-08-25, exploratory): a rolling 10-minute-chunk variant.** Instead of only player-only detection running during the game, analyze each 10-min capture segment (the same segments already produced for crash-safety, `§1.2` in `TECH_SPEC.md`) as it lands, aggregate detected timestamps across chunks, cut the final reel from the full-res recording afterward — keeps the GPU busy through the session instead of idle-then-burst. Real cost, measured against labels rather than estimated: **~1.28 real rallies/hour fully missed at chunk boundaries** (plus a similar rate truncated, not lost), because a rally straddling a boundary is invisible to `crossing_times`/`cluster_crossings` running independently on each side. **Operator's call: accept this cost rather than build overlap/dedupe handling now** — see `DECISIONS.md` ADR-066 for the fix (well-scoped, not built) and `EXPERIMENTS.md` for the measurement. This variant also depends on `ADR-065`'s inference-throughput fix more than a single-batch-per-session design would: every chunk pays its own detector-invocation setup cost, so it was only cheap to consider at all once that fix landed (~1.7s/chunk vs. the pre-fix ~4-7 min/chunk).

---

## 6. Annotation as the core activity

Three kinds of annotation, distinguished by *which dimension of the video* they mark:

| Type | Marks | Example | Cost |
|---|---|---|---|
| **Temporal** | a span/instant in time | rally boundaries, warm-up, "was this rally good" | cheap (a few clicks) |
| **Spatial** | a location in one frame | court corners, a ball in one frame | cheap if one-off |
| **Spatiotemporal** | a location tracked across frames | player tracks, ball trajectory | expensive (per-frame) |

Principles that keep the load honest:

- **Only hand-label what a human uniquely judges** (where a rally starts/ends; "this is a courtesy return"). Derive the rest (net-crossings, "player left court") from positions + geometry — never annotate what arithmetic can compute.
- **Spend on the hard negatives**, not more clean positives. The confusing 10% (dinks, courtesy returns, faults) teaches the detector; the obvious 90% doesn't.
- **Consistency is the ceiling** (`LABELING.md`): an inconsistent labeler caps every metric forever.

**Cost curve:** starts ~100% human (mark from scratch) → model-assisted pre-labeling (human *corrects* the model's guesses; `label.py` already resumes from a file) → spot-check / active learning (human time goes only where the model is unsure). Never zero — and that accumulated human judgment is precisely what makes the corpus a moat.

**Highest-value future annotation:** "was this rally good to watch." No tool produces it, it can't be derived, and it feeds the ranking model in §2.

---

## 7. Delivery & identity

Personalized per-court highlights require linking **court → the people who played there**. Use an **opt-in check-in** (QR scan or name selection at session start) or a within-session visual marker — **not** biometric re-identification (consistent with the privacy stance and `DECISIONS.md` ADR-034).

**Free second product surface:** anonymous within-session movement analytics — kitchen-line presence, distance covered, court coverage, partner spacing / stacking — fall out of the *same player tracking*, need *no ball*, and require *no cross-session identity* — so no privacy conflict (the anonymous-vs-cross-session distinction is drawn in `DECISIONS.md` ADR-034; ADR-008 keeps player *tracking itself* out of the prototype, making this a later-stage capability). A movement-analytics product rides the same foundation as highlights.

---

## 8. What player-only tracking unlocks — and can't do

| Capability | Player-only? | Note |
|---|---|---|
| Dead-time trimming / highlight reels | Yes | The core product |
| Kitchen-line presence, court coverage | Yes | Movement analytics |
| Player workload, distance, sprint speed | Yes | Anonymous, within-session |
| Partner positioning / stacking patterns | Yes | Reuses position data |
| Estimated rally duration | Yes (approx.) | Boundary precision is the Phase 1.5 problem |
| **Automated line calls** | **No** | Needs ball localization — ruled out (`PRD.md` N8) |
| **Ball speed / spin** | **No** | Needs ball tracking |
| **Bounce detection** (kitchen, net tape) | **No** | Needs ball tracking |
| **Definitive error attribution** | **No** | Needs paddle-contact + ball trajectory |

The "No" rows all require the ball and align with the prototype's non-goals.

---

## 9. Business model & monetization (directional)

From a business-model exploration (2026-08-10). Distilled here because it's sound thinking, but **gated on the same thing as everything else: the clipper reliably producing good highlights.** As of 2026-08-10 that is not yet proven — see the caveat at the end, which is the most important part of this section.

**Shape — B2B2C.** The **venue is the buyer**, the **players are the consumers**. The venue installs the system to make its courts more attractive and command a premium; players pay for keepsake clips.

- **Venue side (recurring):** two ways to price the box —
  - **HaaS (preferred, lowest adoption barrier):** no/low upfront; hardware amortized into a monthly fee over a 24–36 month contract. Indicative ~$140–150/court/month (BOM ÷ 24 + SaaS margin) — *but see the BOM caveat; this number is optimistic.*
  - **Buyout + maintenance:** one-time hardware+install, then ~10–20%/yr software/updates. Lower recurring, higher friction.
- **Player side (value-added):** free **low-res, venue-watermarked** 15–30s clip (the venue gets free IG/TikTok promotion) → paid **premium** (HD/4K, no watermark, multi-angle, personal stats) at ~$1–3/session or ~$10/month. **Revenue-share with the venue** (≈5:5 / 6:4) so the venue installs at zero cost and earns on traffic.

**Pricing mechanics that matter:**
- **Per-court (per-device) licensing with volume tiers** (e.g. 1–2 / 3–5 / 6+ courts at descending per-court rates). Aligns price with the per-court hardware; the tiering is what stops it reading as "greedy." Players never see the license — to them it's "buy the 4K download," not "buy a device."
- **The A/B-test wedge (the strongest go-to-market move):** install on **1–2 courts for ~2 months**, and *prove with the venue's own numbers* that the "smart court" books more and sustains a **+20–40% price premium** before proposing full rollout. KPIs: booking / off-peak fill rate, premium payback in 3–6 months, referral reach from watermarked clips. Turns "trust me" into "here's your data."
- **Taiwan billing:** charge via **綠界 (ECPay)** with 開發票 — consistent with the earlier payments discussion; you provide system-integration service, not a foreign SaaS subscription.

**Edge economics (why on-device wins here):** doing the clipping on the edge box (Jetson / Mac mini, §5) means **near-zero cloud-GPU cost** — the cloud only stores files and serves the CDN + payments. That makes SaaS margin high and, because compute is a *fixed* per-box cost, **margin improves the more highlights a court produces.** The trade is a higher device cost and an **OTA fleet-management burden** (pushing model updates to every box) — the same fleet-ops cost already flagged in §5.

**⚠️ The caveat that governs this whole section.** The business case quietly assumes the hardest technical thing is solved. As of 2026-08-12 it's closer but not there yet:
- **The BOM is optimistic.** The exploration assumed **Orin Nano + YOLOv8n, ~$700–1,000/court**. But nano-class detection produced head-as-ball noise; usable detection requires **yolov8x** (~10× heavier). Real hardware is likely **Orin NX/AGX** or serious model-optimization (fine-tuned yolov8n — ADR-040) — which moves the BOM upward. Fine-tuning on our own fixed-mount footage is the path to nano viability (ADR-040).
- **False-positive root cause fixed, but only on handheld footage.** The `max_ball_px=25` filter (ADR-045) eliminated player-body false positives. The mechanism is validated on a 13-min handheld clip. **Still unproven on clean fixed-mount footage** — which is the gate for a real benchmark number.
- **Multi-camera is unbuilt.** The exploration assumes 4 cameras/court with best-angle splicing; everything built so far is **single fixed camera**. That's a whole additional system, not a config flag.
- **Privacy is a real operational item.** A multi-court gym captures bystanders and adjacent courts — face-blur + opt-in check-in (§7) are required, not optional. The N100+cloud shape keeps raw footage local; only a 720p proxy leaves the building (ADR-043).

**In one line:** the model is the right destination; the critical path is still *proving the clipper works on clean footage*, not designing the pricing. Don't let a polished monetization plan imply the product is further along than it is.

---

## 10. Open questions, priority-ordered

1. **Do player-only markers cleanly separate dinks and courtesy returns at real camera geometry?** — Phase 0.6. Gates everything below.
2. **Which piece is actually defensible** — the labeled corpus, the ranking model, or neither?
3. **Does one edge box hold the load** on real footage (the ball / real-time benchmark)?
4. **Live or batch** for the venue product? (Currently batch.)
5. **How much labeled data per new angle category** before it works?
6. **Is 30 minutes a firm user-facing promise** (→ Option B rolling) or is ~1 hour fine (→ Option A, less code)?
7. **Far-court pose reliability** — usable as a trigger, or position/motion only? (Now a prototype risk.)
8. **What's the real BOM** once detection quality is pinned down (yolov8x-class, not Nano; camera resolution to resolve the ball)? Decides whether the HaaS ~$150/court/month math holds.
9. **Does the A/B-test wedge hold** — will a proven "smart court" actually command a booking premium, or do players value the clips but not enough to pay/switch?
10. **HaaS vs buyout vs rev-share** as the lead motion — which one gets the first venues to yes?
