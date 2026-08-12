# PRD — Pickleball Rally Cutter

**Status:** Draft — prototype scope
**Owner:** Tony
**Last updated:** 2026-07-30

Companion documents: [`TECH_SPEC.md`](./TECH_SPEC.md) (how it's built) · [`DECISIONS.md`](./DECISIONS.md) (why)

---

## 1. Prototype scope

**This specifies a prototype, not a product.** One operator, one camera, one court, run from the command line, to answer a single question:

> Can a fixed camera plus audio plus cheap motion analysis reliably find pickleball rallies — and is the resulting reel something I actually watch?

If yes, a production PRD follows, written with real numbers instead of guesses. If no, roughly three weeks were spent and the reasons are recorded in `DECISIONS.md`.

**Out of scope:** packaging, installers, UI, hosting, multi-user, auth, monitoring, cost optimization, mobile capture, and any camera or court other than the one calibrated mount.

**In scope, and non-negotiable:** honest measurement against a labeled holdout set (§5). Without it the prototype answers nothing.

---

## 2. Problem

A two-hour recreational session contains roughly 25–40 minutes of live play. The rest is serving prep, ball retrieval, score talk, and standing around. Reviewing means scrubbing manually, so in practice nobody reviews.

**Goal:** one command turns a session recording into a watchable highlight reel **under 10 minutes**.

### The 10-minute budget forces selection

Cutting dead time alone lands at ~30 minutes, not 10. Reaching 10 requires *choosing* which rallies make it — which means ranking. So the pipeline emits two artifacts from one detection pass:

| Artifact | Contents | Used for |
|---|---|---|
| `highlights.mp4` | Top-ranked rallies, chronological, **≤ 10 min** | Watching back a session |
| `rallies_full.mp4` | Every detected rally, chronological (~25–35 min) | Studying play without dead time |

The two want opposite things — tight selection versus complete coverage — so both are emitted rather than one compromise. Detection is shared; only selection differs.

---

## 3. User modes

The only user is Tony. These are the modes.

| Mode | Job | Artifact | What matters most |
|---|---|---|---|
| **Watch back (primary)** | "See tonight's best play in under 10 minutes" | `highlights.mp4` | Watchability. A dull rally included is worse than a good one dropped. |
| **Study play** | "Review everything, skip the standing around" | `rallies_full.mp4` | Completeness. A missed rally is worse than a loose cut. |
| **Share a few points** | "Post the best 3" | Hand-picked from the reel | Not automated — picking from a 10-min reel is already easy |

---

## 4. Goals and non-goals

### Goals

- **G1.** `highlights.mp4` under 10 minutes, unattended, from one command.
- **G2.** `rallies_full.mp4` from the same run.
- **G3.** High recall on rally *detection* — missing a rally is the primary failure mode.
- **G4.** Runs on the RTX 2000 Ada workstation for PoC iteration; production target is N100 edge + RunPod GPU (ADR-043). Runtime budget stated per platform.
- **G5.** Every quality claim measurable against a labeled holdout set.

### Non-goals

- **N1. Score tracking.** The most valuable feature and the hardest — needs serve detection, side-out logic, and error recovery, since one missed rally desynchronizes the score for the rest of the match.
- **N2. Shot classification** (dink / drive / lob / third-shot drop).
- **N3. Learned or preference-validated ranking.** The prototype ships a deliberately simple heuristic ranker. Establishing what makes a rally "good" against human judgment is deferred.
- **N4. Multi-court or arbitrary-camera generalization.** One fixed mount, calibrated once.
- **N5. Real-time or live processing.** Batch only, post-session.
- **N6. Player identification.**
- **N7. Overlays, graphics, replays, music, transitions.**
- **N8. Line calls / in-out adjudication.** Out, and likely permanently — the accuracy required is far beyond this rig.
- **N9. Everything in §1's out-of-scope list.**

---

## 5. Success metrics

### Definitions

- A **rally** runs from serve contact to the moment the ball becomes dead — it next touches the ground or goes out of play (`LABELING.md` v2).
- A predicted rally **matches** a labeled rally when their overlap-over-union in time is ≥ 0.5.

### Detection targets — measured on the complete rally list

| Metric | Target |
|---|---|
| **Rally recall** — matched labeled rallies / all labeled rallies | **≥ 0.90** |
| **False positives** — predicted rallies with no match, per 10 min of source | **≤ 1.0** |
| **Boundary error** — median absolute error on start/end times | **≤ 1.0 s** |
| **Wall clock** — processing time / source duration | **≤ 0.5×** |

**Detection is measured before selection, never on the 10-minute reel.** Otherwise "dropped to fit the budget" is indistinguishable from "failed to detect," and recall stops meaning anything.

### Selection targets — measured on the reel

| Metric | Target |
|---|---|
| **Budget compliance** — output duration | **≤ 10:00, hard** |
| **Budget utilization** — output / budget | **≥ 0.85** |
| **Rally count** in the reel | **≥ 12** |
| **Keep rate** — selected / detected | reported, not targeted |

Budget compliance is a bug class, not a target to approach. A run that exceeds it fails rather than emitting a non-conforming file.

### The subjective gate

Every metric above can pass on a reel that's dull to watch. So: **watch `highlights.mp4` from three different sessions and answer "would I have watched this voluntarily?"** Two of three yes, or the ranker gets reworked regardless of the numbers.

This is deliberately unrigorous — it's a prototype and the sample size is one. Formalizing it is the first thing a production PRD should address.

### Anti-metrics — do not optimize

- **Compression ratio.** Trivially gamed by cutting aggressively and dropping rallies.
- **Budget utilization alone.** Padding rallies with slack fills the budget and lowers quality. Only meaningful next to rally count.

### Protocol

`eval-set-A` is held out and never tuned against. All tuning happens on `dev-set-B`. Any change that regresses detection recall on `eval-set-A` is reverted, however good the reel looks. Mechanics in `TECH_SPEC.md`.

---

## 6. Product constraints

These are limits users must know about — conditions under which the product works or doesn't. They are not implementation choices. Rationale for each is recorded in `DECISIONS.md`.

| Constraint | Requirement | Consequence if violated |
|---|---|---|
| **Lighting** | Bright outdoor daylight for ball tracking | The camera has no manual shutter control, so in low light it opens to a long exposure and the ball becomes an untrackable smear. Indoor gym lighting is expected to fail, not just night. The pipeline degrades to a coarser mode rather than breaking. |
| **Camera position** | Behind the baseline, elevated ≥ 8 ft, centered, rigidly mounted | Must not move mid-session — the court is calibrated once per mount |
| **Frame rate** | 1080p at 30 fps, fixed | Confirmed once at setup, not re-checked per session. Fixing the rate also caps exposure at 1/30 s, which bounds motion blur — the camera can't expose longer than one frame interval. Helps, but doesn't remove the lighting requirement above. |
| **Audio** | Recorded if available; not required | Optional. Paddle impacts give precise shot timing, but a microphone hears the *whole building* — in a multi-court venue, adjacent courts produce identical impacts that cannot be separated. Detection is video-based and works with audio absent; where audio is clean it only sharpens boundaries. |
| **Court visibility** | All four corners and the net line visible and unobstructed | Detection depends on player positions relative to court geometry. If the court can't be calibrated, nothing downstream works. |
| **Capture** | Recorded to a local file before processing | Batch, not live. Live streaming buys nothing and loses the ability to look ahead when deciding a rally has ended. |
| **Camera** | Must record standalone — no NAS, cloud, or hub in the recording path | Capture happens at courts with no network back to base. This requirement alone has already eliminated one otherwise-superior camera. Full criteria in `DECISIONS.md` ADR-029. |

### Privacy

Recording at a public court captures strangers who haven't consented. Therefore: footage stays local by default, nothing is retained in the cloud beyond a processing window, no face recognition ever — this is intended to cover non-consented re-identification generally, not just literal facial recognition — and the operator is responsible for local law and for telling other players.

---

## 7. Milestones

Ordered so the riskiest assumptions are tested first and something watchable exists in week one.

| Phase | Deliverable | Exit criteria | Est. |
|---|---|---|---|
| **0. Instrument** | Verified capture, labeled eval sets, calibrated court, working eval harness | Harness reports the §5 tables on a hand-written stub | 2 days |
| **0.5. Benchmark prior art** | Existing open-source rally detectors scored against our eval set | A baseline number exists | 1 day |
| **0.6. Validate the approach** | Measure how often "play has stopped" markers misfire — two cases named: **during dink rallies** (low-motion real play) and **after points on courtesy returns** (motion during dead time) | Both near zero. **If not, the detection approach is unsound** and changes before anything is built. → **Measured 2026-08-08: markers inverted on casual play (dead time more active than dink rallies). Led to ADR-039 — v1 pivot.** | 1 day |
| **1. Core pipeline** | End-to-end detection → ranked selection → both artifacts. **Two parallel tracks (ADR-039):** v0 (player dead-time inversion, frozen baseline) and v1 (ball net-crossings, current primary effort). | A watchable ≤10-min reel exists. Recall and FP measured. Subjective gate run once. | 1 week |
| **1.5. Sharpen boundaries** | Dense sampling around rally edges | Boundary error ≤ 1.0 s | 3 days |
| **2. Ball presence** | Off-the-shelf ball detection — no training | FP improves, recall doesn't regress | 3 days |
| **2.5. Audio** (conditional) | Impact timing, only if the recording's audio is usable | Boundary error improves | 3 days |
| **3. Ball trajectory** (gated) | **Entered only if 1.5 and 2.5 both miss the boundary target** | Boundary error ≤ 1.0 s | 1–2 weeks |
| **3.5. Tune ranker** | Weight sweep + subjective gate across 3 sessions | 2 of 3 pass; utilization ≥ 0.85; ≥ 12 rallies | 2 days |
| **4. Tidy** | Resumability, config surface, README | Tony can re-run it a month later without re-reading the code | 2 days |

**Total: 3–4.5 weeks**, depending on the Phase 3 gate.

**Phase 0.6 is the real gate.** The detection approach works by spotting when play *stops* — someone crosses the net, walks off court, picks up the ball — and treating everything else as a rally. That's more robust than trying to score how "rally-like" a moment looks, but only if those markers are clean. One day of measurement confirms or kills it before a week of building. The two cases most likely to break it are pickleball-specific and must be measured explicitly, not averaged away: **dink rallies**, where players barely move during real play so a motion-based marker reads live play as dead time; and **courtesy returns**, where the tap-back after a point looks like a short rally. The easy 80% of points isn't the test — these two are. → **Measured 2026-08-08 on real footage: dink rallies were the failure case — dead time registered as more active than live play. The gate failed; v0 (player) is frozen as a baseline and v1 (ball net-crossings) is the current primary approach (ADR-039).**

**Phase 0.5 is new and deliberately early.** Several open-source pickleball rally detectors already exist, one of which implements roughly Phases 1–2 — but none publishes a single accuracy number. Measuring them costs a day and either saves two weeks or produces a baseline to beat. Building first and comparing later would repeat the mistake this plan exists to avoid.

### Decision point after Phase 1

The prototype exists to produce this fork, not just an artifact:

- **Reel is good** → write the production PRD using measured numbers.
- **Detection works, reel is dull** → the problem is ranking, not vision. Go to 3.5, not 3.
- **Detection is weak** → Phase 2, then 2.5, then the Phase 3 gate.
- **Prior art already beats what we build** → adopt it and spend the time on selection and ranking, which nobody else has done.
- **Player detection is too noisy to trust** (Phase 0.6 fails) → the detection approach needs rethinking, not more tiers. Better camera placement or a better detector, before anything else. → **This fork was taken (2026-08-08). Current primary: v1 ball net-crossings (ADR-039).**

Audio being unusable is no longer on this list. It was once a project-ending risk; it is now a configuration choice.

---

## 8. Risks

| Risk | Likelihood | Impact | Response |
|---|---|---|---|
| **Player detection is noisy or occluded**, so dead-time markers fire during real rallies | **Realized** | **High** | Measured 2026-08-08: markers inverted on casual play. Response: ADR-039 — v1 (ball net-crossings) as primary; v0 (player) frozen as baseline. |
| **Far-court pose estimation too noisy to trigger on** — small, partly-occluded players from an 8-ft baseline mount | Medium | Medium | Keypoint-based rally triggers (swing/stance detection) may be unreliable at range. Test pose quality on the *far* court before depending on it; position and motion markers, not pose, are the fallback signal. |
| Thresholds overfit to one session | **High** | **High** | Strict holdout separation; recall regressions auto-revert |
| **Courtesy returns** read as short rallies — happens after *every* point, so systematic | **High** | Medium | Require ≥ 2 ball crossings plus minimum duration |
| Adjacent courts contaminate audio | High in venues | Low | Audio is optional and auto-disabled by a usability gate. It was demoted from primary precisely because of this. |
| **Warm-up is indistinguishable from play** by any available signal | High | Low | Accepted, not solved. Trim the opening minutes if it's a nuisance. |
| Simple ranker picks dull rallies — all metrics pass, reel is boring | Medium | High | The subjective gate is a hard gate, not advisory |
| Inadequate light makes the ball untrackable | High indoors | Medium | Tiered pipeline degrades instead of failing; a low-light eval set measures the degraded path |
| Low light forces high gain, degrading detection | Medium | Medium | The camera can no longer drop frame rate to compensate, so this surfaces as image noise rather than corrupted timing — a gradual, visible failure instead of a silent one |
| Adjacent-court play triggers false rallies | Medium | Medium | Court-region masking and player-position gating |
| 10 minutes turns out to be the wrong budget | Medium | Low | It's a flag. Try 5 / 10 / 15 on one session and pick by watching. |
| Mount shifts mid-session, invalidating calibration | Low | Medium | Per-session calibration check, warn and re-calibrate |

The first two are the most likely to actually bite. The second is the quiet one — it looks like success right up until the first new session.

---

## 9. Open questions

1. **Are the "play has stopped" markers clean enough to build on?** → **Answered No (2026-08-08).** Markers inverted on casual play — dead time more active than dink rallies. Led to ADR-039 (v1 ball net-crossings as primary; v0 frozen as baseline).
2. **How good is existing open-source rally detection, really?** None of it publishes accuracy numbers. Phase 0.5 answers this and may reshape the whole plan.
2b. **Is this recording's audio usable at all?** Measured, not assumed — it determines whether Phase 2.5 happens, and nothing more.
3. **Is the public pickleball dataset usable?** Camera angles, class list, image count, and licence all unverified. Broadcast or mixed-angle footage won't transfer to a fixed baseline mount, and a domain-mismatched dataset is worse than none.
4. **Is 10 minutes right?** It's a requirement, but also a guess. Cheap to test, and it changes how the ranker should be weighted.
5. **Singles or doubles for the eval sets?** Doubles has more occlusion and more talking. Probably label both and report separately — a system tuned on singles may not transfer.
6. **How tight should boundaries be?** The 1.0 s target is an assumption. Generous padding may feel better than tight cuts.
7. **Does the reel need ordering beyond chronological?** Building to a climax is how humans edit highlights. Chronological is the safe default; worth one experiment later.
8. **Camera capture reliability over wifi RTSP.** Measured across 4 captures (counting decoded frames), delivery is 90–96% of expected @30fps — one earlier test dropped to 113 of 900 (~12.5%), which now looks like the intermittent worst case rather than the norm. Loss is bursty (isolated 1–4 s stalls), not a steady low rate. Root cause of bad *timestamps* was trusting the camera's RTP clock rather than wallclock time; fix is `-use_wallclock_as_timestamps 1`, plus always using a clean stop (`-t N` flag or SIGINT) rather than a hard kill, to avoid corrupting the MKV container. Caveat: even with the wallclock flag, ffmpeg still warns `Timestamps are unset in a packet` on the MKV write — output probed clean, but verify before a real session. All four measurements were short captures on a clean network (6–11 ms ping, 0% loss); a congested venue or a 2-hour session is untested. Recommend microSD local recording over wifi capture once available, to remove the network dependency entirely.
9. **SD card sizing.** Measured stream bitrate is ~1.4 Mbps — possibly the substream; the main stream could be 4–8 Mbps — so a 2-hour session is ~1.26–5.4 GB. Recommend 64GB minimum. Verify the camera's actual max supported card size and required filesystem before purchase (FAT32 caps at 32GB).

---

## 10. Deferred

Each needs its own success criteria before it starts.

- **Preference-validated ranking** — the most likely thing to matter, since a dull reel is the highest-impact risk no metric catches
- **Score tracking** (N1) — winner determination likely requires line-call-level accuracy, already ruled out (N8), so audio-based score-calling (players speaking the score aloud) is a more promising path than vision-only winner detection, *if* sessions use rally scoring (need to confirm ruleset). Serve/side attribution is comparatively tractable and reuses the existing position-tracking signal.
- **Shot classification** (N2)
- **Per-player statistics / player tracking** — distinguish anonymous within-session tracking (tractable, reuses existing position data, no privacy conflict) from cross-session identification (requires some form of re-identification, in tension with the "no face recognition ever" stance, §6). Recommend opt-in check-in (QR code or name selection) or a visual marker (wristband/pinnie) as the identity-linking mechanism instead of biometric re-ID.
- **Multi-court generalization** — the only scenario where automated court detection earns its cost
- **Live processing**
- Everything in §1's out-of-scope list

### Venue deployment — a different product, not a port

Running this at clubs or courts on their hardware would invalidate several decisions rather than merely extending them. Recorded here so it doesn't creep in unnoticed:

| What breaks | Why |
|---|---|
| Hand-calibrated court | Venue staff can't be asked to click 12 points per mount — this is the one case where automated court detection is worth its cost |
| Daylight requirement | Most venues are indoor, where ball tracking is expected to fail. Audio and player motion would have to carry the product alone. |
| Single fixed camera (N4) | Generalization becomes required, not deferred |
| No packaging (§1) | Needs a real installer and a non-technical setup flow |
| Local-only storage | Uploading a venue's footage means a data-processing relationship: retention, access control, consent signage, breach exposure |
| Runtime budget | "Generic Windows PC" spans hardware with and without any usable accelerator |

The likely architecture is capture plus coarse detection on a small dedicated box, uploading only candidate segments for cloud processing. That keeps most footage in the building and removes the variable hardware instead of routing around it.
