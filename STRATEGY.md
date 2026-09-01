# STRATEGY — Beyond the Prototype

**Status:** Exploratory · **Owner:** Tony · **Last updated:** 2026-08-12, reconciliation pass 2026-08-26, desktop client sketch 2026-08-26, ADR-071 architecture split 2026-09-02

**Nothing in this document is committed.** It records the direction and the open questions from a design conversation about what a multi-venue product *could* look like, so the thinking isn't lost. The prototype ([`PRD.md`](./PRD.md)) gates all of it — specifically the Phase 0.6 result. Venue deployment is "a different product, not a port" (`PRD.md` §10), and this document does not change prototype scope.

**Gate status (2026-08-26): the prototype's own gate is cleared** — `DECISIONS.md` ADR-067/ADR-068 confirm the reel-watchability objective (`PRD.md` §2) has been met. So this document is no longer moot pending that result; it's the live next-decision surface `PRD.md` §1 points at.

**Reconciliation caveat (2026-08-26): most of this document below §3 still describes a player-position-tracking product, which was never built.** `ADR-047` (2026-08-13) pivoted the actual, shipped, validated pipeline to **ball-crossing detection** (TrackNet) — player tracking was deferred and remains completely unbuilt (no player boxes, no positions, nothing). §3 already carries its own superseded note; §4/§7/§8 below were not reconciled at the time and are corrected in place below. Read every "player tracking gives you X" claim in this document as a **future capability contingent on building player tracking from scratch**, not a description of, or free byproduct of, the current system.

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

**Operator's working answer (2026-08-26): neither of the above — the moat is venue relationships.** Being first to a venue and getting them to implement compounds two ways at once: it's the acquisition channel for the labeled corpus above (more venues in early = more footage variety to refine on, reinforcing rather than replacing that candidate), and it creates real switching cost once a venue has adopted the system (their booking/marketing workflow, their footage history, their players' expectations). This reframes the labeled-corpus and ranking-model candidates above as **reinforcing assets a relationship-first strategy accumulates**, not the primary thing being defended. Consequence for §9 and §10 below: speed of venue acquisition matters more than model sophistication — a "good enough" detector shipped to venue #1 before a competitor arrives beats a marginally-better detector shipped later. Not yet stress-tested against the obvious counter (what stops a venue from switching to a better competitor later, or a venue operator negotiating hard once they see the value) — worth pressure-testing before treating this as settled.

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

**Corrected 2026-08-26 for the actual, shipped mechanism (see the reconciliation caveat above).** The paragraph below described a *learned* segmentation model operating on player position — that was never built. What actually exists and is validated: a **fixed arithmetic pipeline** (`court_wedge` gate → `track_ball` → `crossing_times` → `cluster_crossings`, no trained model in the loop at all) operating on **calibrated ball position**, plus **per-venue calibration** (`calib/*.json`, `court_wedge`, `net_line_y`). The calibration-need conclusion below still holds — it's *more* true for a fixed pipeline than a learned one, since there's no learned venue-invariance to fall back on if calibration is off. "Angle generalization" below is a live, partly-answered question now (see the 2026-08-24 side-on note further down) — reframe it as *does the ball-crossing pipeline survive non-baseline angles*, not player segmentation.

**Shape (original, superseded framing — kept for the calibration argument, not the mechanism):** one universal segmentation model operating in **court-normalized coordinates**, plus **per-venue calibration**. Calibration absorbs each camera's geometry; the model learns the venue-invariant behavior of a rally.

**What calibration does *not* normalize** — and therefore what still causes domain shift venue to venue:

- Lighting (indoor vs. outdoor — the daylight requirement doesn't go away)
- Occlusion geometry (camera height/angle differ even after the court is mapped)
- Ball visibility
- Audio

So "universal" is honest for court-plane player *positions* and a fiction for appearance, occlusion, ball, and sound.

**Court calibration at a new venue:** auto-detect the court lines to propose an outline, then **a human confirms or nudges** — never blind auto. Because calibration is once-per-mount and everything downstream depends on it, the asymmetry (catastrophic-if-silently-wrong vs. 30-second confirm) argues against full automation until customers self-serve. A court is the same shape everywhere, so a single court-detector is the one place "universal model" cleanly applies. Auto-detection's better first job may be the **per-session drift check** ("has the camera moved since calibration?").

**Angle generalization (progressive):** start by *insisting* on the behind-baseline mount. Expand support **one angle category at a time** (behind-baseline → elevated-corner → side-on …) as labeled footage for each category accumulates. "Any angle" is really "enough coverage of the common angle categories." Collecting other-angle footage can begin before support ships — capture now, label later, enable when a category has enough data.

**Open questions, corrected for the actual mechanism:** does the ball-crossing pipeline survive non-baseline angles at all? **Partly answered** — corner-angle footage in hand confirmed `net_line_y`'s flat-average slope assumption breaks on that angle; a fix is designed (interpolate net height by image-x) but not built, deferred by the operator (`PIC-23`, see the side-on note below for the easier case). How much labeled data does a new angle category need before it works — genuinely still open, and this pipeline needs boundary/quality labels per venue (for `min_crossings`/`gap_sec` tuning), not a training-data volume question the way a learned model would.

**Decision (2026-08-26): stay on the behind-baseline mount for now.** Courtside is not being pursued at this time — this note is kept as background for later, not an active direction.

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

**The desktop client (2026-08-26, exploratory): the software vehicle for the local side of "N100 + cloud GPU," generalized to any local box.** This section's hardware table above frames local capture as a *hardware* choice (N100 vs. Jetson vs. Mac mini). A parallel question came up directly: does it have to be vendor-supplied hardware at all, or can a venue point its own workstation (Windows, Mac, whatever) at the same role? Under the current architecture — detection fully offloaded to a RunPod GPU (`ADR-043`) — the local side no longer needs an accelerator to do that job, which was the original reason `DECISIONS.md` (the ADR just before `ADR-043`) rejected venue-owned hardware ("unknown, varied Windows hardware, no reliable accelerator"). That reasoning predates the RunPod pivot and no longer fully applies — worth remembering the next time this tradeoff comes up, so the old objection isn't treated as still-binding without rechecking it.

**Split 2026-09-02 (`DECISIONS.md` ADR-071, accepted — not a hardware choice like the table above, an application-architecture one): a thin local agent, not a single desktop client that owns everything.** Two days of actually building the desktop client (`desktop/`) made the original single-client framing below wrong in an important way — most of what it listed isn't LAN-bound and doesn't need to run at the venue at all. The forcing constraint: ONVIF discovery is UDP multicast and a venue's cameras sit on a private LAN with no port-forwarding, so only camera-facing work (discovery, RTSP connect/capture, and — because full-res video stays local per `§7`'s privacy stance — cutting the final reel from it) has to run on a machine physically at the venue. Scheduling, court/venue management, footage review, and multi-venue admin are just data and belong in a real hosted web app instead (see the new subsection below). This reframes the list that follows: it's now the **local agent's** scope, not the whole system's.

Local agent (venue owner-facing, runs on a machine at the venue), responsible for:

- **Camera discovery/management** — locate cameras on the local network, let the owner add/configure them. Built (`desktop/electron/cameras/*`). `DECISIONS.md`'s RTSP-over-wifi evaluation already found real reliability problems (frame drops, non-monotonic timestamps) worth designing around rather than rediscovering.
- **Recording** — pull and save the camera's actual stream to local segmented files. Built (`desktop/electron/capture.js`, 2026-09-01) — manual start/stop only so far, not yet tied to a schedule (`PIC-72`).
- **Court calibration** — needs a live/local frame to click points on, and is invalidated by camera movement (ADR-049), so it can't move to the web app. Exists today as a standalone script (`setup_venue_calibration.py`), not yet folded into the local agent.
- **Encode/compress locally** — this is where CFR conversion belongs (settled 2026-08-26, after initially assuming it should move cloud-side): it's a correctness fix-up (frame timing) and a corruption-repair side effect, not a detection step, so it has no reason to run anywhere but next to the raw footage. Today's implementation hardcodes `h264_nvenc` (`cloud_pipeline/run_cloud_job.py`), which assumes an NVIDIA GPU — a real gap against "any venue's own workstation," not yet fixed (needs a portable/CPU fallback, `PIC-67`), and not yet invoked by the local agent at all.
- **Send to the cloud** — already built (`cloud_pipeline/r2_storage.py`), just needs to be called from the local agent instead of the operator's own CLI (`PIC-68`). Per ADR-071: invoked as a subprocess, not reimplemented in JS — same pattern already used for `ffmpeg` in `capture.js`.
- **Receive the cloud pipeline's output and clip from local full-res using the returned timestamps** — this is not new: it's exactly this section's own "proxy video trick: 720p to cloud, cut from local full-res" (`ADR-043`), just never implemented. The local agent would be the first thing to actually build it, and per ADR-071 it has to stay here regardless of how the rest of the system splits, since the full-res file never leaves the venue.
- **Connectivity to the cloud web app: outbound-only.** The agent polls (or maintains a lightweight persistent connection) for pending commands and reports status back — never an inbound port opened on the venue's router. Chosen so no venue needs any special network configuration, the same "any camera, no vendor-specific setup" stance extended to networking (ADR-071).

**Not yet scoped, flagged not solved:** real cross-platform packaging (this is a native app for venue owners' own machines, not the current CLI-script prototype); and — raised in the same conversation, acknowledged by the operator as a known follow-up, not addressed here — today's RunPod/R2 credentials are the operator's own `.env` values, which cannot ship inside a client distributed to external venue owners without exposing full infrastructure access. Whatever access-scoping fix replaces that (`PIC-71`) is a prerequisite for this client reaching an actual venue, not for prototyping it.

**The cloud web app (2026-09-02, exploratory — architecture only, nothing built) owns everything that's just data, not LAN-bound:**

- **Scheduling** — booked sessions per camera. Built once already, in the wrong place: `desktop/`'s `ScheduleOverviewPage`/`ScheduleEditorPage` + `electron/schedule.js` (2026-09-01) is real and useful in the interim, and is the reference design to port, but per ADR-071 it migrates wholesale (data and UI both) once the web app exists, rather than staying maintained in two places. The local agent still needs to know when to actually trigger a recording — closes that gap by polling/caching the relevant schedule over the same outbound connectivity channel above, not a separate mechanism.
- **Court/venue management records, footage review, multi-venue admin, delivery to players** — all new, none of it built. Delivery is *serving* finished clips (access-control/link-generation, `§7`'s privacy stance still applies — a scoped/signed/expiring link is the likely right shape, not an open one, still not decided); the finished clip's bytes reach storage via the local agent's own upload step above, not a separate upload path.
- **Not yet built at all:** the local-agent API surface itself (nothing external can drive `desktop/`'s Node backend today — only its own Electron renderer can, via IPC), the outbound connectivity/relay mechanism, and a real multi-tenant database + auth system (today everything is flat JSON locally or R2 objects, with zero user accounts anywhere).

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

**Free second product surface (corrected 2026-08-26 — not actually free yet):** anonymous within-session movement analytics — kitchen-line presence, distance covered, court coverage, partner spacing / stacking — would fall out of player tracking, need no ball, and require no cross-session identity, so no privacy conflict (the anonymous-vs-cross-session distinction is drawn in `DECISIONS.md` ADR-034). **But player tracking itself does not exist in the shipped pipeline** — `ADR-047` deferred it before it was built, not after, so this is a real future capability requiring player detection/tracking built from scratch, not a byproduct that "rides the same foundation as highlights" the way this section originally claimed. The current foundation (ball-crossing) produces zero player-position data today.

**Delivery mechanism (2026-08-26, exploratory; owner corrected 2026-09-02 — `DECISIONS.md` ADR-071):** Cloudflare-as-CDN, link-based delivery is the actual output leg — the piece this section discusses identity/personalization for, but never specifies a transport for. Originally sketched as the desktop client's job; per ADR-071 that's now the **cloud web app**'s "delivery to players" responsibility (`§5`) — the local agent's role stops at uploading the finished clip's bytes, it doesn't serve the link. Same caveat applies either way: a bare public link sits awkwardly next to this section's own privacy stance, so it likely wants to be scoped/signed/expiring rather than open — not decided, see `§5`.

---

## 8. What player-only tracking would unlock — and can't do (hypothetical; player tracking is not built)

**Reframed 2026-08-26.** The table below describes a *hypothetical* system built on player tracking, which does not exist — `ADR-047` deferred it before any of it was built. Read every "Yes" below as "buildable if player tracking gets built," not "available today." See the companion table after it for what the actual, shipped system does.

| Capability (if player tracking were built) | Player-only? | Note |
|---|---|---|
| Dead-time trimming / highlight reels | Yes | Superseded — the actual shipped mechanism is ball-crossing, not player tracking; see below |
| Kitchen-line presence, court coverage | Yes | Movement analytics — real future work, not built |
| Player workload, distance, sprint speed | Yes | Anonymous, within-session — real future work, not built |
| Partner positioning / stacking patterns | Yes | Reuses position data — real future work, not built |
| Estimated rally duration | Yes (approx.) | Boundary precision is the Phase 1.5 problem either way |
| **Automated line calls** | **No** | Needs ball localization — ruled out (`PRD.md` N8) regardless of mechanism |
| **Ball speed / spin** | **No** | Needs ball tracking |
| **Bounce detection** (kitchen, net tape) | **No** | Needs ball tracking |
| **Definitive error attribution** | **No** | Needs paddle-contact + ball trajectory |

### What the actual shipped system (ball-crossing, no player tracking) does today

| Capability | Ball-crossing pipeline? | Note |
|---|---|---|
| Dead-time trimming / highlight reels | **Yes** | The real, validated core product (`PRD.md` §2, ADR-067/068) |
| Reel ranking (which rallies make the cut) | **Yes** | `src/select.py`, ADR-063 — duration + peak crossing rate + velocity-spike count |
| Estimated rally duration/boundaries | Yes (approx.) | Boundary precision is the known open item, `PIC-33`/`PIC-55` |
| Ball speed, as an internal signal | Partial | Frame-to-frame ball speed is already computed for the ranking signal above; not exposed as a product feature, spin not attempted |
| Kitchen-line presence, distance covered, court coverage | **No** | Needs player tracking — unbuilt, see §7's correction |
| Player workload, partner positioning/stacking | **No** | Needs player tracking — unbuilt |
| Paddle-contact / error attribution | **No** | `PIC-42` prototyped paddle detection (Grounding DINO works, unfiltered); contact detection itself unbuilt |
| Automated line calls, bounce detection | **No** | Same as above table — out of scope regardless of mechanism |

The practical read: **the current system is a highlights-only product.** Everything in §7's "free second product surface" and most of the original table above is real, plausible future work — but it's a from-scratch build on top of what exists, not a byproduct already sitting there.

---

## 9. Business model & monetization (directional)

From a business-model exploration (2026-08-10). Distilled here because it's sound thinking, but **gated on the same thing as everything else: the clipper reliably producing good highlights.** As of 2026-08-10 that was not yet proven — **as of 2026-08-26 it is (`DECISIONS.md` ADR-067/068)**, so this gate is cleared. The BOM/hardware caveats below are not: they were written assuming the player-tracking edge-compute profile (§3/§8's superseded mechanism), and have not been redone against the actual ball-crossing pipeline's compute cost — treat the $ figures below as unverified for the current mechanism, not just optimistic.

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

1. **~~Do player-only markers cleanly separate dinks and courtesy returns at real camera geometry?~~ Answered, by a different mechanism than this question assumed (2026-08-26).** The project never tested this via player markers — `ADR-047` pivoted to ball-crossing before that mechanism was tried. The underlying concern (can dinks/courtesy-returns be told apart from real rallies) turned out to resolve mostly through **honest labeling**, not detection logic at all: `ADR-060` found `PIC-31`'s "separate real rallies from dead-time junk" problem is almost entirely a labeling-completeness artifact project-wide, not a signal-separation problem. No longer gates anything below.
2. **Which piece is actually defensible** — the labeled corpus, the ranking model, or neither?
3. **Does one edge box hold the load** on real footage (the ball / real-time benchmark)?
4. **Live or batch** for the venue product? (Currently batch.)
5. **How much labeled data per new angle category** before it works?
6. **Is 30 minutes a firm user-facing promise** (→ Option B rolling) or is ~1 hour fine (→ Option A, less code)?
7. **Far-court pose reliability** — usable as a trigger, or position/motion only? (Now a prototype risk.)
8. **What's the real BOM** once detection quality is pinned down (yolov8x-class, not Nano; camera resolution to resolve the ball)? Decides whether the HaaS ~$150/court/month math holds.
9. **Does the A/B-test wedge hold** — will a proven "smart court" actually command a booking premium, or do players value the clips but not enough to pay/switch?
10. **HaaS vs buyout vs rev-share** as the lead motion — which one gets the first venues to yes?
