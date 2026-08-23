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

---

## 2026-08-06 — Prior-art assessment: vinod-polinati ball-presence detector (ADR-021)

**Assessment, not a benchmark** — no footage to score against yet. Read the repo's README + `rallysplitv.py`.

**What it is.** ~200 lines, MIT. YOLOv8x on *every* frame → COCO "sports ball" → size / shoe-zone / physics(teleport) filters → binary ball-present timeline → 0.6 s gap-tolerance state machine → rally clips (min 1.0 s). No court geometry; players used only to reject foot-zone ball detections. No accuracy numbers reported.

**Decision — beat it, don't adopt.**
- **Too slow:** YOLOv8x every frame (~1 TFLOP/frame, hours on an M2) vs. the ≤0.5× budget — and the ball can't be subsampled, so the cost is structural, not tunable.
- **Hard-coded pixel thresholds** (65 px size, 300 px jump, 45% shoe) are overfit to the author's rig; violates the "court-units, not pixels" principle (TECH_SPEC §1.1).
- No validation, no court geometry, no temporal smoothing.
- **Untested crux:** whether COCO sports-ball reliably detects a real pickleball at our distance/lighting (the §6 "untrackable smear" risk).

**Keep from it** (for the Phase 2 ball path): the shoe filter, the physics/teleport filter (implausible jump doubles as scene-cut detection), the gap-tolerance state machine.

**The measurement that decides it** (needs footage — rows 10/11): ball-detection recall on our footage. If an off-the-shelf detector reliably finds our ball, the ball-presence approach is viable and complements player-only on the still moments (serves/dinks) that beat it in the read above. Fusion (ADR-022) remains the likely answer.

---

## 2026-08-08 — First real footage (indoor drop-in): compromised by zoom; approach unresolved, ball direction reinforced

**Footage.** Two phone clips from an indoor casual session (IMG_7652 ~13 min, IMG_7655 ~9.4 min), 1080p/30fps, ~0 dropped frames. **Not fixed-camera — the phone zoomed/panned during play**, which invalidates the single homography (calibration only holds for a fixed view) and pushes players out of frame. So the read below is confounded — not a fair test.

**Setup.** Order-independent calibration (RMSE 0.45 ft, borderline far-corner). YOLOv8n @5fps → foot → court coords → on-court filter → motion + kitchen markers, scored vs 32 hand-labeled *plays*. Labels were "any play" (warm-up/casual included), not strict competitive rallies — a target mismatch.

**Result (confounded).**
- Player detection noisy: median **2–3 players/frame, only 21% find 4** (occlusion + nano model + players off-frame from zoom + adjacent-court leakage).
- Markers **inverted** even on clean 4-player frames: motion RALLY 2.4 vs DEAD 3.2 ft/s; kitchen RALLY 0.43 vs DEAD 0.77. No separation.
- Ball probe: COCO sports-ball detected in **5/6 in-play frames** (2 at 0.88–0.91 conf) — **detectable indoors**, but noisy (false positives, misses).

**Conclusion.** Not a verdict on the approach — confounded by zoom (broken calibration + off-frame players), broad labels, and detection noise. Two directions reinforced: (1) player-activity likely can't separate low-energy casual rallies from active dead-time → the **ball / net-crossing count** (ADR-028) is the real rally signal; (2) **tracking (ByteTrack) and the ball are both needed earlier** than planned (revisit ADR-008 / ADR-022). The ball being detectable makes the net-crossing path viable.

**Decisions.** Target = competitive rallies; domain = casual drop-in play. Fixed camera non-negotiable (no zoom/pan). Pivot to the ball-net-crossing rally counter as the next build.

**Follow-up.** Capture clean **fixed** footage (no zoom/pan, whole court). Re-label to competitive rallies only. Build the ball-net-crossing counter + ByteTrack. Then a fair Phase 0.6.

---

## 2026-08-09 — v1 auto-annotator on full 7652 (raw footage → rally segments)

**Hypothesis.** If the ball-net-crossing signal is a real rally detector, scanning the whole raw clip and clustering dense crossing-bursts into segments should cover the hand-labeled rallies. Expected good recall, unknown precision.

**Setup.** `IMG_7652.MOV` (zoom-compromised), whole clip at `sample_fps=10`, `band=15`, `cluster gap_sec=2.0`, `min_crossings=2`. Net line reused from `IMG_7652_calib.json`. Ground truth = curated `IMG_7652.jsonl` (9 competitive rallies). Commit `e47ac73` (branch `feat/v1-annotate`).

**Result.**

| Metric | Value |
|---|---|
| Labels covered (recall) | 9 / 9 (100%) |
| v1 proposed rallies | 96 |
| Spurious vs labels | 78 / 96 (81%) |
| Sampled frames / ball-present | 7769 / 5408 (70%) |

Distribution: MATCH segments median 7 crossings (max 22); spurious median 4 (max 20). **10 spurious segments have ≥10 crossings** — near-certainly real sustained play, just not in the competitive-9. **31 spurious have ≤3 crossings** — likely noise (zoom moving the net line + loose `min_crossings=2`).

**Conclusion.** Kept. Recall is the headline: v1 misses no labeled rally. The 81% "spurious" rate is confounded, not a clean precision number — the labels are a curated *competitive* subset (9 of an original ~32), so much of the "extra" is genuine casual play the crossing signal correctly detects. Confirms crossing-count is a real rally signal (consistent with the 7652/7655 smoke tests). Not validated — compromised footage.

**Follow-up.** (1) Clean fixed footage for a real precision number. (2) Raise `min_crossings` / widen band to shed the ≤3-crossing noise. (3) Separating *competitive* from *casual* likely needs rally length/intensity, not crossings alone — a ranking layer, not a detection fix. (4) Same scan on 7655.

---

## 2026-08-10 — Ball detection: nano vs yolov8x (visual diagnostic, both clips)

**Hypothesis.** The prior-art splitter (Medium, Polinati) uses yolov8**x**; we use nano. A bigger model should cut the false "ball = head" detections we saw.

**Setup.** Annotated a labeled rally with ball boxes + net line drawn on frames. 7652 window 58–77.5s, 7655 window 86–101s (net line reused from IMG_7652_calib.json). nano vs yolov8x. Commit `c10888b`/`8a193a9` (branch `feat/ball-recipe`).

**Result (visual, verified by zooming into detections).**

| Case | Ball detected? | Confidence |
|---|---|---|
| 7652, ball mid-court (t=69) | yes, real ball | **0.91** |
| 7655, ball at the net (t=98) | yes, real ball | **0.20–0.32** |
| Both, false positives (heads/bodies) | — | 0.19–0.4 |

nano crossings 22 → yolov8x 15 (7652); 7655 yolov8x 14. Net line wrong (below the net) on **both** clips — reused calibration + zoom.

**Conclusion.** yolov8x is clearly better than nano — it finds the real ball, and on a **big** (mid-court) ball the 0.9-vs-0.3 gap cleanly separates ball from junk. **But confidence is size-dependent:** the ball *at the net* — small and far from a behind-baseline camera — scores only 0.2–0.3, overlapping the false-positive range. **Sharp implication: the crossing moment (ball at the net) is intrinsically the hardest detection from this camera angle**, because the net is the farthest point. A plain confidence cutoff would drop exactly the frames we care about. Net-line error confirmed on both clips → the derived line is unreliable; mark it.

**Follow-up (filed as ADR-040 candidate).** (1) Ship yolov8x default + `ball_box_ok` size filter + `net_line_y` marked-net (done, `feat/ball-recipe`). (2) Confidence alone insufficient → need size filter + a tracker (bridge/interpolate the small-ball frames) — TrackNet-style is the real answer for the tiny far ball. (3) Camera angle matters: side/elevated so the net isn't the farthest point, or higher resolution — a capture lever, not a software one (ADR-038). (4) Re-test the full recipe only on clean fixed footage with a marked net.

---

## 2026-08-10 — Reprocess with corrected net line: rallies clean, dead time still noisy (needs a tracker)

**Hypothesis.** With the net line hand-placed correctly + yolov8x + size filter, real rallies should show clean crossings AND dead time should go quiet.

**Setup.** Rendered annotated clips (yolov8x, `max_ball_px=50`, per-window hand-measured net line): 7652 rally 58–77.5 (net y=260), 7652 rally 620–638 (y=170), 7655 rally 86–101 (y=210), and a "dead" segment 659–666 (y=160). Crossings counted on the drawn output.

**Result.**

| Window | net y | crossings | read |
|---|---|---|---|
| 7652 rally 58–77.5 | 260 | 33 | clean rally, net line on the net |
| 7652 rally 620–638 | 170 | 12 | clean (vs 20 with the old wrong line — noise removed) |
| 7655 rally 86–101 | 210 | 20 | clean, even with the ball small at the net |
| 7652 DEAD 659–666 | 160 | **18** | **noise persists — 2.6/s, higher than rallies** |

Also: the net line moved **y=260 → 170** between two rallies of the same clip — pure zoom. Confirms one calibration can't hold across a zooming clip.

**Conclusion.** Rallies reprocess cleanly with a correct net line — the net-line + model fixes work *during play*. But **dead time still produces phantom crossings**, and it's a *third* cause the earlier fixes don't touch: in a multi-court gym the detector locks onto **out-of-play balls** (adjacent courts, idle balls, warm-up) — genuine ball-sized detections in the wrong place — and taking "best ball anywhere" per frame makes the pick hop between them, flipping sides. Not a net-line or size problem.

**Follow-up.** Dead-time rejection needs a **ball tracker** (single-ball motion continuity + reject teleports, à la the prior-art cut logic) — this moves tracking from "maybe later" to **required** for dead-time discrimination. Possibly an image-region gate for the active court too. Rendering note: OpenCV writes mp4v (not web-playable) — re-encode to H.264 before delivery.

---

## 2026-08-11 — Ball tracker wired into the crossing pipeline: dead time → 0, rally preserved

**Hypothesis.** The single-ball tracker (`track_ball`, teleport rejection) should drop the 659–666s dead-time phantom crossings toward ~0 *without* erasing a real rally's crossings. Until now the tracker was tested only on synthetic candidate lists — never run against the benchmark that motivated it, because the glue from `detect_candidates` → `track_ball` → `crossing_times` didn't exist.

**Setup.** New `src/pipeline.py` (`rally_segments_from_candidates`, `detect_rallies`) chains detect → track → crossing → cluster. IMG_7652 (compromised/zoomed footage), dense per-frame yolov8x, per-window hand-measured net line, `max_jump=150`, `band=0`, `max_ball_px=None`. commit f28ccba. Compared naive "best ball per frame" vs tracked on the *same* detections.

**Result.**

| Window | net y | naive crossings | tracked crossings | tracked rallies (gap=3s, min=5) |
|---|---|---|---|---|
| DEAD 659–666 | 160 | 22 | **0** | **0** |
| RALLY 58–77.5 | 260 | 36 | 16 | 1 |

Tracked crossings stable across `max_jump` 100–200 (dead=0, rally=16); at 300 the rally dropped to 11. Clustering sweep on the rally (16 crossings, inter-crossing gaps up to ~2s): `gap_sec=1.0` → 0 rallies (dissolved), `2.0` → 2, `3.0–4.0` → 1 (15/16 crossings clustered). Dead time stayed 0 at every gap.

**Conclusion.** The tracker works on real footage: dead-time phantom crossings **22 → 0**, while the real rally keeps a strong 16-crossing signal — clean separation, the core v1 mechanism validated end-to-end for the first time (resolves the prior entry's follow-up). Two findings: (1) `max_jump` 100–200 is safe here; 300 starts dropping real crossings. (2) **`gap_sec=1.0` is too tight** — rally net-crossings are up to ~2s apart, use ~3s; a recipe value, not a code default.

**Caveats.** One rally + one dead-time window, still on **compromised (zoomed)** footage with per-window hand-measured net lines. Validates the *mechanism*, not a benchmark number. Clean fixed-camera footage is still the gate for a real recall/FP measurement and for tuning `max_jump`/`gap_sec`/`max_ball_px` without overfitting to one clip.

**Follow-up.** On clean footage: measure ball pixel size → set `max_ball_px`, compute one net line from calibration, run `detect_rallies` across all labeled rallies vs the harness. Then wire selection/ranking + `cut.py` (footage → clips) — `render.py` primitives already exist.

---

## 2026-08-11 — Alternative ball detector survey: PikleYOLO, TrackNet (badminton), AndrewDettor TrackNet-Pickleball

**Hypothesis.** A domain-specific ball tracker (TrackNet architecture, trained on paddle-sport footage) might outperform the generic yolov8x "sports ball" class, especially for the small ball at the net.

**Setup.** Tested four detectors against two benchmark windows on IMG_7652 — a known rally (58–77.5s, net_y=260, expected: 16 crossings → 1 rally) and a known dead segment (659–666s, net_y=160, expected: 0 crossings). yolov8x result reused from the 2026-08-11 tracker experiment.

| Detector | RALLY crossings | DEAD crossings | Verdict |
|---|---|---|---|
| yolov8x (tracked, baseline) | 16 → 1 rally | 0 → 0 rallies | ✅ clean separation |
| PikleYOLO yolov8n | 0 → 0 | 0 → 0 | ❌ detects at cy=3–47px (ceiling artifacts) |
| TrackNet badminton pretrained | 0 → 0 | 0 → 0 | ❌ detects at y=5–176px (domain gap + temporal mismatch) |
| AndrewDettor TrackNet-Pickleball | cannot run | cannot run | ❌ CUDA-only: TF Conv2D NCHW requires NVIDIA GPU |

**PikleYOLO:** yolov8n trained on pickleball, but appears to have been fine-tuned on a different court setup. On this footage it fires almost exclusively at the ceiling, never detecting the ball in play.

**TrackNet (badminton):** VGG16 encoder-decoder trained on badminton shuttlecock, NCHW input, 9-channel (3 RGB frames stacked). Loaded via community PyTorch port (tf2torch). The model does produce heatmaps but detects at the top of the frame — classic domain gap from a near-overhead camera angle used in badminton vs. behind-baseline pickleball.

**AndrewDettor TrackNet-Pickleball:** TF 2.11 SavedModel, trained on pickleball footage. Loads successfully under TF 2.13 (Keras 2, earliest ARM64-compatible version). But the Conv2D layers use `data_format='channels_first'` (NCHW), which TF only supports on CUDA GPUs — not macOS CPU or Apple Silicon. Cannot run without NVIDIA hardware.

**Conclusion.** yolov8x remains the only working detector for this pipeline on macOS. The alternatives all have blockers: PikleYOLO is overfit to a different court, TrackNet badminton has an irreconcilable domain gap, AndrewDettor requires a CUDA GPU. AndrewDettor is worth re-testing on Jetson Orin (which has CUDA) — it was trained on pickleball footage and the architecture is right for ball tracking.

**Follow-up.** (1) Re-test AndrewDettor on Jetson once it's available. (2) Fine-tune yolov8n on our own fixed-mount footage — this is the production path (see ADR-040).

---

## 2026-08-11 — Auto net-line detection from raw footage (Hough lines on temporal median)

**Hypothesis.** A temporal median of sampled frames erases moving players/ball, leaving static court structure. Hough line detection on the median should find the net line without manual calibration.

**Setup.** `detect_net_y()` in `src/calib.py`. Samples 20 frames from first 20% of video, computes per-pixel median, applies Canny + HoughLinesP restricted to 15–65% of frame height, filters to near-horizontal lines with left-half-frame coverage, takes the topmost sufficient cluster. Tested on IMG_7652 (known net_y=260).

**Result.** Auto-detected net_y = 312 (error = 52px, ~5% of frame height). The algorithm finds the far service line painted on the floor, not the pickleball net itself. Root cause: the net is a dark mesh that creates no strong horizontal Hough edge. The service line at y≈308–312 is the topmost spanning horizontal line the algorithm can reliably find.

At sample_fps=5 (for speed), crossing counts with net_y=312 collapsed to 1 vs 5 with net_y=260 on the rally window — confirming the 52px error degrades detection meaningfully on this footage. Not tested at full fps.

**Conclusion.** Hough-on-median auto-detection is not reliable for this court setup. Kept as a `--auto-detect` flag for rough use. The interactive picker (`pick_net_y`, default mode) is the practical solution: one click on the first frame gives exact net_y in under 5 seconds. See ADR-041.

**Follow-up.** On a court with a white net tape against a dark background, the Hough approach may work — worth re-testing with fixed footage. Long-term, net post detection (find vertical posts → derive net_y from post height) is more robust than line detection.

---

## 2026-08-11 — sample_fps=10 default; hanging on long videos without it

**Observation.** Running `python -m src.cut` on a full 13-minute clip at default `sample_fps=None` (every frame) would take several hours on a MacBook CPU — yolov8x processes ~2 fps, so 23,000 frames = ~3 hours. The CLI had no `--sample-fps` argument, so there was no way to reduce this without editing source code.

**Fix.** Added `--sample-fps` to the CLI defaulting to 10 fps. At 10 fps on a 13-min clip: ~7,800 frames, ~65 minutes on CPU. Reduces to ~30 min at 5 fps (with some crossing miss rate on very fast exchanges). The underlying `detect_candidates` already accepted `sample_fps` — this was a missing CLI wiring.

**Note.** sample_fps=5 in a benchmark test showed 5 crossings vs 16 at full fps for the same rally window — many crossings are missed between samples. At 10 fps the miss rate should be acceptable for rally-level detection (the ball completes a net crossing in ~0.1s; at 10fps there is a 0.1s gap between samples, so some crossings are borderline). Full fps remains the most accurate path if time allows.

---

## 2026-08-12 — TrackNet-Pickleball on RunPod RTX 3090: 25 crossings vs YOLO's 5

**Hypothesis.** AndrewDettor's TrackNet-Pickleball (3-frame heatmap architecture, trained on pickleball) should detect more ball crossings in the benchmark rally window than yolov8x, because it was designed specifically for small, fast-moving ball tracking across a net.

**Setup.** RunPod RTX 3090 community pod ($0.22/hr, CUDA 12.8, TF 2.21). `IMG_7652.MOV` 55–80s clip (covers rally #3: 58–77.5s). Model: **old TrackNetV2 badminton weights** (`TNV2_old_weights`, 130MB HDF5, loaded with `compile=False` to bypass Keras 3 optimizer deserialization failure). The pickleball fine-tuned weights (`weights_k14_epoch19` SavedModel) could not be loaded: TF 2.21 Keras 3 refuses legacy TF 2.11 SavedModel format. Full fps inference, net_y=260 (per-window hand-measured), clip offset=55s. Script: `/workspace/tracknet_infer.py` on pod.

**Result.**

| Metric | YOLO (yolov8x, best params) | TrackNet (old badminton weights) |
|---|---|---|
| Crossings in rally #3 window (58–77.5s) | 5 | **25** |
| Visible frames | ~5 | 409 / 750 (54.5%) |
| Clustered events (gap=2s) | 1 | ~4 |

Raw crossing timestamps (all within 58–77.5s): 62.17, 62.40, 62.90, 62.93, 63.00, 63.13, 63.57, 63.93, 65.30, 66.03, 67.70, 67.73, 68.10, 68.80, 70.40, 71.03, 71.90, 72.00, 72.20, 72.40, 73.83, 74.70, 75.83, 76.07, 76.50.

With gap=2.0s clustering: 4 events (~62–64s, ~65–66s, ~67–69s, ~70–77s). With gap=1.0s: ~9 events.

**Conclusion.** TrackNet detects 5× more crossing evidence than yolov8x on this footage. Even with mismatched badminton weights (wrong domain), the 3-frame heatmap architecture sees the ball across the net where YOLO cannot. The 54.5% visible rate is higher than expected and likely contains false positives from the domain-mismatched model — but the crossing density (25 in a 19.5s window) aligns with observed play intensity.

**Caveats.**
1. **Wrong weights** — badminton-trained, not pickleball fine-tuned. The fine-tuned `weights_k14_epoch19` SavedModel can't load under TF 2.21 due to the Keras 3 format break. Pickleball weights should perform better (or at least differently — lower false positive rate).
2. **54.5% detection rate** is suspicious on handheld indoor footage. Some "visible" frames are almost certainly false positives from the badminton model treating non-ball objects as shuttlecocks.
3. **No dead-time control** — didn't run the equivalent dead-time segment (659–666s) through TrackNet to measure false positive rate. That's the key missing number.
4. **Footage is compromised** — handheld/zoomed; still not a clean benchmark.

**Follow-up.**
1. Re-run with pickleball fine-tuned weights once TF version mismatch is resolved: either use TF 2.13 + Python 3.10 pod image, or re-export the SavedModel to `.keras` format in the original environment.
2. Run the dead-time segment (659–666s) through TrackNet to measure FP rate — essential before concluding TrackNet is better.
3. Add TrackNet as an optional ball detector in the pipeline (`--detector tracknet`) once weights are loadable on macOS (requires CUDA; Jetson Orin is the target deployment).
4. The production path is still fine-tuning yolov8n on fixed-mount footage (ADR-040) — TrackNet requires CUDA which rules it out for the Mac mini / N100 deployment shape. TrackNet is the right answer for the cloud-GPU inference shape (ADR-043).

---

## 2026-08-16 — Pickleball fine-tuned weights (k14) vs badminton weights: full IMG_7655 A/B on local GPU

**Hypothesis.** The pickleball fine-tuned `weights_k14_epoch19` (blocked since 2026-08-12 by the Keras 3 format break) should beat the badminton `TNV2_old_weights` at the source — fewer false positives, better boundaries — making downstream filter tuning easier.

**Unblocking the weights (no Docker needed).** The TF 2.11-era SavedModel loads cleanly under **TF 2.15.1 (last Keras-2 release) with `compile=False`** — same trick as the .h5. Docker daemon was down and sudo unavailable; instead built a standalone env: python-build-standalone 3.11.16 + `tensorflow[and-cuda]==2.15.1` at `/mnt/fast_scratch/tf215_env/` (set `LD_LIBRARY_PATH` to the venv's `nvidia/*/lib` dirs). `tf.saved_model.load` on TF 2.21 still fails (optimizer `add_slot` error) — it's the Keras-2 `load_model` path that works. Weights downloaded from the TrackNet-Pickleball Google Drive ("New Weights") to `/mnt/fast_scratch/tracknet_weights/weights_k14_epoch19/`.

**Throughput (answers the real-time question).** Both weight sets run at **~58 fps on the RTX 2000 Ada** (17,004 frames in 4.9 min, batch-1 `tf.function` call) — ~2× faster than the 30 fps footage. Real-time inference is feasible on this GPU; the batch architecture is a choice, not a compute constraint.

**Setup.** Full IMG_7655.MOV (566.9s, 17,004 frames), local inference mirror of `scripts/pod_infer.py` (same prep, same blob-confidence peak pick). Both CSVs through the identical pipeline: `rally_segments_from_predictions`, net_y=210 (hand-measured at the 86–101s window), gap_sec=3.0, min_crossings=3, band=0, max_jump=150, reset_after=15, no court X-gate (no 7655 calib). Scored with `eval/harness.py` vs the 36 labels in `eval/labels/IMG_7655.jsonl`. CSVs: `IMG_7655_predictions_k14.csv`, `IMG_7655_predictions_badminton.csv`.

| Metric | pickleball k14 | badminton old |
|---|---|---|
| Visible frames | 4,627 (27%) | 5,504 (32%) |
| track_ball teleport drops | 1,108 (24% of visible) | 1,477 (27% of visible) |
| Raw crossings | 238 | 278 |
| Segments (min_crossings=3) | 32 | 36 |
| Recall @ IoU≥0.5 | **11/36 (31%)** | 5/36 (14%) |
| FP /10min @ IoU≥0.5 | **22.2** | 32.8 |
| Boundary error (median) | **1.05 s** | 1.34 s |
| Recall @ IoU≥0.3 | 20/36, 12 FP | 19/36, 17 FP |
| Recall @ IoU≥0.1 | 25/36, 7 FP | 28/36, 8 FP |

**Read.** At loose overlap both arms find roughly the same rallies (25 vs 28 of 36) — but the pickleball weights get the *boundaries* right: strict-IoU recall more than doubles (11 vs 5) and boundary error drops 1.34→1.05s. The badminton arm's segments are longer and blurrier (e.g. 91.5–111.2s spanning past the labeled rally), which inflates loose-overlap recall while failing strict matching. Pickleball is also cleaner upstream: 5% fewer raw detections, a lower teleport-drop rate, fewer sub-threshold noise clusters. Domain-matched weights win on precision and boundary quality at equal recall — as hypothesized.

**Caveats.**
1. **Fixed net_y=210 on zoomed footage** — the net line drifts across the clip, so absolute recall is meaningless; only the A/B delta is meaningful (both arms share the handicap).
2. Labels are "any play", not strict competitive rallies (2026-08-08 caveat still applies).
3. No court X-gate (no 7655 calibration) — adjacent-court noise not filtered.

**Follow-up.**
1. **Make k14 the default weights** for pod/local inference (pod needs the TF 2.15 image or this env, not TF 2.21).
2. Re-run the A/B on clean fixed-mount footage (IMG_7743/7744) with real calibration + court gate — needs the ground-truth labeling pass (benchmark plan step 1).
3. Local GPU at 58 fps makes the RunPod round-trip optional for ≤~30-min footage — prefer local inference for iteration.

---

## 2026-08-16 — First trustworthy benchmark on clean footage: crossing-count alone cannot separate rallies from casual play

**The first eval on genuinely clean fixed-mount footage, against complete hand labels, with both sides blind.** Ground truth: 33 rallies hand-marked on IMG_7743 (11 graded highlight-worthy, 22 ordinary) using the two-pass workflow — mark serve→ball-dead with no judgement, then grade with hindsight (`label_web.py`). The detector ran before labelling and never saw the labels; the labeller never saw the detector's segments.

**Source footage had to be repaired first.** Both IMG_7743.MOV and IMG_7744.MOV carry localized HEVC damage that makes `cv2.VideoCapture` stop silently — a full-video run returned **930 of 121,013 frames with exit code 0**. Repaired with a CFR NVENC re-encode (`-fps_mode cfr -r 30` is load-bearing: passthrough drops frames and shifts every later timestamp). `scripts/pod_infer.py` now aborts when it decodes <98% of the expected frames.

**Setup.** k14 pickleball weights, full 4037s / 121,110 frames (31% visible), real calibration (`IMG_7743_calib.json`, net_y=552 from hand-marked net tape, RMSE 0.85ft), court X-gate derived from the calibration. Scored at IoU≥0.3 against the 33 labels.

| Config | precision | recall | segments proposed |
|---|---|---|---|
| **Shipped defaults** (gap 3.0, min_crossings 3, band 0) | **0.10** | 0.61 (20/33) | 201 |
| Best of a 156-point sweep (min_crossings 9) | 0.25 | 0.45 (15/33) | 60 |
| Best with an added min-duration filter (≥8s) | **0.26** | 0.48 (16/33) | 62 |

**Pass 3 (gap review) is what makes these numbers trustworthy.** 24 of the 181 unmatched detector segments, sampled evenly across the video and stripped of their crossing counts, were hand-judged: **all were junk** — bad serves, idle time, ball-tapping with no exchange. So the labels are not merely sparse; the detector is genuinely over-firing at ~3 segments/minute against ~0.5 real rallies/minute.

**The ceiling is in the signal, not the thresholds.** Tuning doubles F1 (0.17→0.34) and then stops, because the junk is *physically the same event* as a rally — a ball crossing a net. Discriminators that should have worked don't:

| | real rallies | junk segments |
|---|---|---|
| duration (median) | 10.1 s | 4.2 s |
| **crossings per second** | **1.09** | **1.29** |
| ball-tracked frames | 37% | 43% |

Junk has a *higher* crossing rate and *better* ball visibility than real play. Duration is the only separator, and filtering on it buys 0.01 F1. Practice serves and warm-up dinking produce exactly the crossing signature the rule looks for.

**Recall is a second, smaller problem.** Of the 13 rallies missed: 5 had <3 raw crossings inside them (invisible to any threshold — the ball simply wasn't tracked across the net enough), 8 had ≥3 and were lost to clustering/boundary effects (recoverable by tuning).

**CORRECTION (same day, after user review of the pass-3 clips).** The conclusion first drawn from the table above — that junk segments were casual-but-real play, physically identical to a rally, implying a signal ceiling — **was wrong**. It rested entirely on aggregate statistics and never checked *where* the detections were. The user's review forced a recheck: "a lot of them are just people walking, passing the ball back, or dead time."

**Plotting the tracked positions on a frame settled it in one look.** Real rallies plot as clean arcing ball trajectories in a tight column over the near court between the players. Junk plots as a diffuse, structureless cloud over the **adjacent court to the left, the far wall, the barrier netting and the ceiling** — with almost nothing on the near court. The false positives are **hallucinated detections in background clutter**, not real play. Because that cloud straddles the net line, `track_ball` wanders inside it and manufactures crossing bursts. This also explains the paradoxical stats: a distant blob jittering near the net line flips sides constantly, giving junk a *higher* crossings/sec than real play.

**Also checked and found correct: the hand-marked net line (y=552).** It sits above the calibrated far baseline (589), which looks geometrically impossible and was briefly taken as a calibration bug. It isn't. The camera is mounted below net-tape height — the marked tape is below the ground plane's horizon (y=526) — so an elevated object at 22ft legitimately projects above a ground point at 44ft. The homography-derived alternative (y=638) is the net's *base*, and is visibly wrong on the frame. `net_line_y`'s preference for hand-marked points is correct.

**What the correct diagnosis buys.** `court_x_range` is inoperative on this footage: derived from the near-baseline corners it spans x=4..1915 on a 1920px frame and excludes nothing. Replacing it with a **perspective-aware wedge** — the court's x-extent interpolated as a function of image-y, plus a margin — cuts the left adjacent-court cluster and 43% of all detections.

| config | precision | recall | F1 |
|---|---|---|---|
| shipped (x-range gate, min_crossings 3) | 0.10 | 0.61 | 0.17 |
| court wedge +80px, min_crossings 3 | 0.12 | 0.52 | 0.19 |
| **court wedge +80px, min_crossings 7** | **0.31** | 0.45 | **0.37** |

**Still unsolved.** Much remaining junk sits in the column *directly above* the near court, where no spatial gate separates it from real play. The distinguishing feature there is **trajectory coherence** — real balls trace smooth parabolic arcs, junk jumps incoherently — so the indicated next experiment is a velocity/smoothness constraint in `track_ball` (its `max_jump=150` px/frame is permissive enough to let the tracker roam the cloud), not another count threshold.

**Method note worth keeping:** aggregate statistics could not distinguish "casual play looks like a rally" from "the detector is hallucinating in the background"; a scatter plot of detections on the frame distinguished them immediately. Plot before theorising.

**Follow-up.**
1. Implement the perspective-aware court wedge in `src/calib.py` (replacing/alongside `court_x_range`) and re-score.
2. Add a trajectory-smoothness constraint to `track_ball` and re-score.
3. Raise `min_crossings` from 3 to ~7 and settle the long-standing inconsistency.
4. Repeat the benchmark on IMG_7744 (repaired, side-on angle) to see whether the conclusion is angle-dependent.

---

## 2026-08-16 (later) — Capped trapezoid gate works; masking before inference does NOT

Follow-on to the same 33-label IMG_7743 benchmark. All rows: k14 weights, hand-marked net (y=552), IoU≥0.3.

| config | precision | recall | segments |
|---|---|---|---|
| shipped (flat x-interval, min_crossings 3) | 0.10 | 0.61 (20/33) | 201 |
| **capped trapezoid, min_crossings 6** | **0.29** | **0.61 (20/33)** | **69** |
| masked-at-inference + trapezoid, min_crossings 6 | 0.20 | 0.52 (17/33) | 83 |

**The gate shape that works** follows the court's perspective taper (not a straight-sided trapezoid: the taper is strongly non-linear, and a straight shape is still ~half the frame wide at net-line height, exactly where the adjacent court sits — measured precision 0.18 vs 0.29), widens above the far baseline by ~0.5 of the far width (a ball hit high *near the camera* is high in the image but still horizontally wide), and is **hard-capped** ~0.7 court-heights above the far baseline.

**The cap raises recall, which was not expected.** Spurious ceiling/light-fixture detections were hijacking `track_ball` *inside* real rallies — it would jump to a fixture, lose the ball, and the rally would lose crossings and fall under threshold. So the gate does double duty: it drops bad segments *and* protects the tracker during good ones. A fully-open cone recovers the cut detections, finds the same rallies, and only loses precision — width was never the constraint, height was.

**Masking before inference is worse than filtering after** (tested because it should in principle stop hallucinations at the source). Detection rate fell 31%→22% of frames and three real rallies were lost. The hard mask edge is a high-contrast boundary the model never saw in training, and a half-blacked frame is out of distribution — consistent with the frame-edge false positives seen in the preprocessing experiment. **Conclusion: filter geometrically after inference; do not mask the input.**

**Generalisation is unproven and one part is known to break.** The trapezoid outline derives from the calibration, so it adapts to any camera angle. The *cap* is expressed as a fraction of the court's image height, which scales with camera elevation: on IMG_7652 (higher mount, court 717px tall vs 385px) it lands 280px above the top of the frame, silently disabling itself and leaving 78% of the frame open. A cap defined in real ball height would transfer — the marked net tape is a free height ruler (0.86 m ≈ 86 px at the net's depth on 7743, so ~100 px/m). Untested elsewhere: IMG_7744 has a calibration but no labels; IMG_7655 has 36 labels but no calibration; IMG_7652 is zoom-compromised so one homography does not hold.

**Found while checking generalisation: IMG_7652's net line is wrong**, ~130px too low. Its calibration has no `net_image_points`, so `net_line_y` fell back to the homography-derived line — which returns where the net's *base* meets the floor, never its tape. That is a bias, not noise, and it silently corrupts every crossing count from that calibration. `net_line_y` now warns.

---

## 2026-08-17 — PIC-1: the recall ceiling is a mid-session camera bump, not a detection problem

**Hypothesis (going in).** PIC-1's own framing (occlusion / motion blur / low contrast / ball too small) assumed the *detector* was failing during the 13 missed rallies. Checked this by categorizing the misses first, then rendering the actual footage with detections and the net line drawn on — the same method that cracked the earlier false-positive question.

**Setup.** `IMG_7743_fixed.mp4`, `IMG_7743_predictions_k14.csv`, `IMG_7743_calib.json` (`net_y=552`), shipped config (`court_wedge`, `min_crossings=6`, `band=0`). Scored at IoU≥0.3 against the 33 labels.

**Step 1 — categorize the 13 misses by time, not just by crossing count.** Listing all 33 labels as hit/miss in chronological order:

| range | hits | misses |
|---|---|---|
| t=147–2841s (labels 0–21) | 20/22 | 2 (label#3 @475s, label#19 @2378s — isolated) |
| t=2950–3993s (labels 22–32) | 0/11 | **11/11 — every single rally in the last ~18 minutes of the session** |

This is not a scattered pattern. Something changes hard at a single point around t≈2850–2860s and nothing after it is ever detected again, regardless of gate/threshold.

**Step 2 — ruled out band (net hysteresis) as the fix**, since several of the 11 had decent visibility (41–62%, in line with the rest of the video) but almost no registered net crossings (0–2) — the ADR-042 dink-hovering signature. Swept `band` 0→40px × `min_crossings` 3/4/6 (28 configs): **band recovers zero of the 13 misses at any setting, and actively destroys recall on the other 20** (0.61 → as low as 0.00 at band=40). Rejected.

**Step 3 — rendered raw + tracked detections with the net line drawn on, inside label#22 (2949.8–2965.9s, quality-1/highlight).** The tracked `y` sequence shows a real, coherent ball bouncing repeatedly near the net (`y` oscillating 340↔530 many times over 16s — a genuine fast net exchange) but almost never reaching `net_y=552` — only one clean crossing registers. Pulling the actual frame at the one moment it *did* cross (t=2953.70) and zooming on the net: **the ball sits right on the visible net tape, but the calibrated `net_y=552` line is drawn ~50px below it** — visibly wrong. The same check on an early *hit* rally (t=597.9, t=672.1) shows `net_y=552` landing exactly on the net tape — correct there.

**Step 4 — confirmed this is the camera, not the net sagging, and found the exact moment.** Compared clean (no-ball) crops of the net at the same x-position, early vs. late: at t=680 the net tape lines up with `net_y=552`; at t=2900/3500/3990 it sits visibly higher in the frame, a gap that doesn't change across the whole tail (rules out gradual net-tape sag, which would keep growing). Bisecting between the last hit (t=2841) and the first shifted check (t=2900) in ~10s steps: **the shift happens in a 2-second window, t=2858→2860** — a discrete event, not a drift. Far-wall signage (DÉFI logo, banner) sits in the same pixel position before and after, which rules out a camera *tilt* (that shifts near and far objects together); a near-field-only shift is the signature of a camera *translation* — i.e. **the camera was physically bumped or nudged around t≈2859s**, close enough to the net to shift its image position a lot while barely moving the distant back wall.

**Step 5 — measured the new net position and validated the fix.** Sampled pixel brightness along vertical strips near the net post at t=3500 (post-shift): net tape sits at `y≈496–503`, call it 500. Re-scored each of the 11 tail labels' raw crossing count with `net_y=500` instead of 552: **9 of 11 immediately clear `min_crossings=6`** (crossings jump from 0–3 to 5–13 per window). Running the *full* 33-label scoring with a piecewise `net_y` (552 before t=2859, 500 after, everything else — gate, thresholds — unchanged):

| config | precision | recall | segments |
|---|---|---|---|
| shipped (`net_y=552` throughout) | 0.29 | 0.61 (20/33) | 69 |
| **piecewise `net_y` (552 / 500 at t=2859)** | 0.33 | **0.85 (28/33)** | 84 |

Still missed: label#3, #19 (pre-shift, see below), #28, #30, #31 (post-shift, likely needs the full geometry re-derived, not just `net_y` — see Follow-up).

**The two pre-shift misses (label#3 @475s, label#19 @2378s) are a different, smaller issue.** Both already have enough raw crossings (9 and 7, over `min_crossings=6`) but `cluster_crossings`' `gap_sec=3.0` boundary splits real play into fragments that don't line up with the label window (label#3: a real 7-crossing segment exists at 473.4–480.6s, overlapping only 4.8 of the label's 14.3s). This is the already-known `gap_sec` rally-boundary tradeoff (`[[project-tracknet-false-positive]]` 2026-08-16 entry, real-vs-fake serve-pause problem) — not new, and not the dominant cause.

**Conclusion.** The 13-rally recall ceiling is **not** a detection failure (occlusion/blur/contrast/size, PIC-1's original hypothesis) for 11 of 13 cases. **The dominant, named cause: the camera was physically bumped at t≈2859s** (47 minutes into a 67-minute session), shifting the net's image position by ~50px and silently invalidating `net_y=552` for the rest of the recording. TrackNet kept detecting the ball fine throughout (visibility in the tail is 41–62%, normal for this footage) — the crossing *logic*, not the detector, broke. No amount of `min_crossings`/`band`/gate tuning downstream of a wrong `net_y` can recover this, which is exactly why PIC-1 observed "no amount of adjusting settings brings them back." This is a **capture-side** cause — filed as ADR-049.

**Follow-up.**
1. **Fix (recommended, not yet built):** detect the shift automatically (e.g. a periodic frame-diff or feature-match check against the calibration reference frame) and split the session at t≈2859s into two calibration regions; re-run `calibrate.py` on a post-shift frame for the second region rather than reusing a single rough `net_y=500` guess (this validation only patched `net_y`, not the full homography/`court_wedge`, which is why precision only moved 0.29→0.33 instead of further — the wedge gate is still geometrically stale for the tail, likely explaining most of the 84 vs. 69 segment growth).
2. **Mount hardening (capture-side, ADR-049):** a bumped camera is now confirmed to happen mid-session and to be catastrophic for this pipeline (kills every subsequent rally) — worth a physically stiffer mount and/or a start/end-of-session calibration-frame check as a matter of course.
3. label#3/#19's `gap_sec` boundary issue is separate and smaller-scale (2 of 33 labels) — worth revisiting alongside the existing open `gap_sec` finding, not urgent on its own.
4. `label#28`, `#30`, `#31` still miss even under the rough piecewise fix — `#30` in particular has genuinely low visibility (22%, vs ~50% for the rest of the tail) and may have an additional real detection-difficulty cause; worth a second look once a proper post-shift calibration exists.

---

## 2026-08-17 (later) — Real split calibration for IMG_7743: recall 0.61 → 0.91; found and fixed a `calibrate_web.py` regression

**Follow-up to PIC-1/PIC-29.** The rough `net_y≈500` patch above was a proof of concept, not a real calibration. Built the real thing: split `IMG_7743_fixed.mp4` at t=2900s (safely inside the gap between the last pre-bump rally and the first post-bump one) into `IMG_7743_prebump_0-2900s.mp4` and `IMG_7743_postbump_2900s-end.mp4`, split `IMG_7743.jsonl` the same way (postbump labels re-offset by −2900s), reused the existing calibration for the pre-bump half (same camera position, unchanged), and had the user click a fresh 12-point + 2-net calibration for the post-bump half via `calibrate_web.py`.

**Found a real bug while doing this.** The first save came back at **30.3 ft RMSE** — wildly bad, resembling ADR-035's original "mis-ordered clicks" failure (28.2 ft). Investigated instead of re-clicking blind: `calibrate.py`'s interactive tool calls `solve_assignment()` (the ADR-035 order-independent solver) before `compute_calibration()`, but **`calibrate_web.py`'s `/save` handler skips straight to `compute_calibration()`** — the order-independent fix never made it into the browser tool when it was built. Re-ran the user's *exact same clicks* through `solve_assignment()` by hand: RMSE dropped to **0.69 ft**, in line with the original calibration's 0.85 ft. The clicks were fine; the tool was silently reintroducing a bug that was already fixed once, for a different entry point. Fixed `calibrate_web.py` to match `calibrate.py` (one line: call `solve_assignment` before `compute_calibration`), 73 tests still pass, no test previously covered this path (`calibrate_web.py` has no test file at all — untested code, which is how the regression shipped unnoticed).

**Result, scoring each half independently against its own calibration and labels** (same shipped config: `court_wedge`, `min_crossings=6`, `band=0`, reusing the existing `IMG_7743_predictions_k14.csv` sliced by time — no re-inference needed):

| | net_y | calib RMSE | segments | precision | recall |
|---|---|---|---|---|---|
| prebump (0–2900s, 22 labels) | 552.0 | 0.85 ft | 69 | 0.29 | **20/22 (0.91)** |
| postbump (2900s–end, 11 labels) | 494.2 | 0.69 ft | 22 | 0.45 | **10/11 (0.91)** |
| **combined (33 labels)** | — | — | 91 | **0.33** | **30/33 (0.91)** |

Recall clears the PRD's ≥0.90 target for the first time. This is a real jump over the rough patch's 28/33 (0.85) — a proper post-bump calibration recovers `label#28` and `#31` that the single hand-patched `net_y` missed, leaving only `label#30` (22% visibility in-window, a genuinely harder detection case, unrelated to calibration) plus the two pre-bump `gap_sec` boundary misses (`label#3`, `#19`) already characterized above.

**Conclusion.** Confirms PIC-1's diagnosis end to end: the 13-rally recall ceiling was ~entirely a stale-calibration problem, not a detection-quality problem. Per-segment recalibration is sufficient, no model or gating change was needed.

**CORRECTION (same day): the "recall clears the PRD ≥0.90 target" claim above was wrong — it used the wrong IoU threshold.** `TECH_SPEC.md` §11 specifies matching at **IoU≥0.5**, but this entry (and every other IMG_7743 number in this file since the 2026-08-16 baseline) was scored at **IoU≥0.3**, a looser bar adopted informally and never reconciled with the spec. Re-scored the same segments/labels at the actual spec'd threshold:

| IoU threshold | single stale calib (before) | split, real calib (after) |
|---|---|---|
| 0.3 (used above, and throughout this file) | 0.29 precision / 0.61 recall (20/33) | 0.33 / **0.91** (30/33) |
| **0.5 (the actual TECH_SPEC §11 spec)** | 0.25 / 0.52 (17/33) | 0.29 / **0.79** (26/33) |
| 0.7 | 0.09 / 0.18 (6/33) | 0.13 / 0.36 (12/33) |

At the real threshold, recall is **0.79, not 0.91**, and does **not** clear the ≥0.90 target. The underlying finding is unchanged and still large (0.52→0.79 recall from calibration alone) — only the "target cleared" claim was wrong. **Every prior IMG_7743 number in this file (the 2026-08-16 baseline, the capped-trapezoid/min_crossings sweep, the band sweep) was also scored at IoU≥0.3**, so they're mutually consistent, just all looser than `TECH_SPEC.md`'s documented bar. Not yet reconciled project-wide — flag any future "recall/precision" number in this file as IoU≥0.3 unless stated otherwise, until someone re-scores the whole benchmark history at 0.5.

**Follow-up (updates PIC-29).**
1. Two of PIC-29's four checklist items are now done: per-segment calibration works (proven by hand, two calibration files + a manual time-sliced scoring script) and the real post-shift calibration beats the rough-patch baseline on both precision and recall. **Still not built:** automatic drift detection, and wiring per-segment calibration into `src/tracknet.py`/`src/cut.py` itself rather than a one-off script — today this requires manually splitting the video/labels and running two separate scoring passes.
2. `calibrate_web.py` has no test coverage at all — worth a regression test asserting it calls `solve_assignment` before `compute_calibration`, so this specific bug can't silently reappear a third time.
3. Precision (0.33 combined) is still well short of a usable product — this experiment only touched calibration/net_y; the background-clutter false-positive problem (`EXPERIMENTS.md` 2026-08-16) is untouched and still the binding precision constraint.

---

## 2026-08-17 (later) — First second-camera-angle scored benchmark: IMG_7744

**PIC-11.** Every number this project has produced, including everything above, came from one single camera angle (IMG_7743). Built a real hand calibration for IMG_7744 (`calibrate_web.py`, 12 court + 2 net points — the order-independent-solver fix from earlier today applies here too) and a real two-pass hand-labelling session (`label_web.py`) from scratch, since neither existed before today.

**Calibration: 1.60 ft RMSE**, worse than IMG_7743's 0.85 ft or the same day's `pb_draft_cup` calibration (0.34 ft, below). Broken down: 11 of 12 points fit to ~0.36 ft (as good as anything else calibrated this session), but the near-right corner alone is 5.42 ft off — **the camera's framing cuts that corner off the frame at every timestamp** (confirmed fixed-mount, not timestamp-dependent), so it had to be estimated outside the visible image. Accepted as the honest ceiling given the framing, same call as IMG_7743's lens-distortion floor (`[[project-camera-lens-distortion]]`).

**Labelling: 10 rallies** (2 highlight-worthy, 8 ordinary), covering the first ~21 minutes of the 38.9-minute video — the labeller stopped there because the rest of the video only has play on the adjacent court, not ours.

**Note found along the way: `label_web.py` had its own real bug**, unrelated to the `calibrate_web.py`/`solve_assignment` one from earlier today. It used a single-threaded `HTTPServer`; the `/video` streaming endpoint's blocking write loop over the multi-GB file could (and did, once, live) wedge the entire server so a later `/save` POST queued forever and never completed — labelled rallies were lost once already before this run. Fixed by switching to `ThreadingHTTPServer` (`daemon_threads = True`). No test coverage existed for this either.

**Inference:** full-video TrackNet, local GPU, 70,002/70,004 frames (99.997%), 38.1 min at 30.6 fps — noticeably slower than IMG_7743's ~58 fps on the same hardware; not investigated (could be thermal, could be a colder cache, could be something about this video specifically).

**Scored** (shipped config: `court_wedge`, `min_crossings=6`, `band=0`, `gap_sec=3.0`):

| | segments | precision | recall |
|---|---|---|---|
| IoU≥0.3 | 24 | 0.29 | 0.70 (7/10) |
| **IoU≥0.5 (the real spec)** | 24 | **0.25** | **0.60 (6/10)** |

**Conclusion.** In the same ballpark as IMG_7743 (0.25–0.29 precision on both), which is a mildly reassuring sign the pipeline's precision problem isn't specific to one camera/venue. Recall is lower here (0.60 vs. IMG_7743's 0.79 post-calibration-fix) — plausibly explained by the worse calibration (1.60 ft vs 0.85 ft) feeding a less accurate `court_wedge`/`net_y`, plausibly just a smaller, noisier sample (10 labels vs 33). Not enough data yet to tell which.

**Follow-up.**
1. PIC-11 substantially done: real calibration + real labels + a real scored number now exist for a second camera angle. Not fully closed — the calibration's near-right-corner gap and the small label count (10, vs IMG_7743's 33) limit how much confidence to put in the cross-camera comparison above.
2. `label_web.py`'s threading fix should get the same regression-test treatment as `calibrate_web.py`'s `solve_assignment` fix (both bugs shipped with zero test coverage on these tools).
3. The 30.6 fps vs 58 fps inference speed gap is unexplained — worth a look if local-GPU throughput becomes a bottleneck later, not urgent now.

---

## 2026-08-17 (later still) — IMG_7744's false positives are real exchanges, not hallucinated clutter — a different failure mode than IMG_7743's

**Watched all 14 of IMG_7744's within-labelled-region false positives at real playback speed** (cut to individual padded clips, `clips/IMG_7744_fp_review/`, watched end to end — not stills; this project already got burned once trusting stills for a rally-vs-not call, see the 2026-08-16 IMG_7743 correction). Still frames at each segment's midpoint had already hinted at this (real balls/players visible near the net, not empty background), but per house method that's a lead, not a verdict, until someone actually watches it.

**Verdict (user, direct playback): most of the 14 are real ball exchanges, but almost none are real rallies — they're quick exchanges and failed return-of-serve attempts.**

**This is a different root cause than IMG_7743's diagnosed false-positive problem.** IMG_7743 (2026-08-16) traced its false positives to TrackNet *hallucinating* ball-shaped detections in background clutter (adjacent court, wall, ceiling fixtures) — no real ball was there at all, and the fix was geometric (`court_wedge`). IMG_7744's false positives are the opposite: **the ball is real, the crossings are real, the court is right — the exchange itself just didn't develop into what a human would call a rally.** No geometric gate, size filter, or confidence threshold can tell "6 real crossings from a failed serve return" apart from "6 real crossings from a real rally," because both are literally the same signal (a ball legitimately going back and forth over the net) at the same location. `min_crossings=6` was tuned exactly to suppress this class of thing (ADR-028's original "courtesy-return" concern, ADR-048's tuning) and evidently isn't high enough here — these exchanges clear 6+ real crossings before dying.

**This is the already-known, previously-unsolved "warmup/real-rally distinction" problem, now with a second confirmed instance.** `[[project-tracknet-false-positive]]`'s 2026-08-16 entries flagged this same gap on IMG_7743 (serve-pickup-vs-serve, `gap_sec` boundary ambiguity) and concluded it needs "a genuine serve-start signal... crossing-gap clustering fundamentally can't distinguish [this] from timing alone." IMG_7744 confirms the same ceiling on a second camera, with cleaner evidence (direct video confirmation of *what kind* of real exchange these are, not just a boundary-fragmentation guess).

**Conclusion.** IMG_7744's precision problem (0.25) is not, or not only, IMG_7743's problem (background-clutter hallucination). It looks more like a rally-*completeness*/duration problem — real crossings from real but abortive exchanges. `min_crossings` and geometric gating (`court_wedge`, `PIC-2`'s blob filtering, `PIC-3`'s trajectory smoothness) target the hallucination failure mode and won't touch this one.

**Follow-up.**
1. Filed as a new issue (not folded into PIC-2/PIC-3, which target a different cause): distinguishing real rallies from quick/failed exchanges needs a different signal than crossing count or geometry — candidates: minimum sustained-exchange duration tuned specifically for this (distinct from `gap_sec`, which controls clustering gaps not minimum length), rally-length distribution modeling, or point-outcome signals (players resetting position, a clear dead-time pause after) rather than trying to classify the exchange itself.
2. Worth checking whether IMG_7743's remaining (unexplained) false positives, post-`court_wedge`, are more of *this* failure mode rather than more hallucination — the two projects' precision ceilings might be the same problem wearing two different hats.

---

## 2026-08-17 (later still) — Third camera scored: pb_draft_cup, precision holds in the same 0.25–0.29 band

**PIC-11 follow-on.** Calibrated (`calibrate_web.py`, 12 court + 2 net points — 0.34 ft RMSE, the best of the three videos scored so far), hand-labeled (`label_web.py`, 7 rallies over the first ~10.4 minutes), and TrackNet-inferred (local GPU, 18,735/18,736 frames). Scored against the shipped config (`court_wedge`, `min_crossings=6`, `gap_sec=3.0`, `band=0`) — same recipe as IMG_7743/IMG_7744, one-off script (not yet a committed CLI path — see the open follow-up in the 2026-08-17 IMG_7743 split-calibration entry above about wiring `court_wedge` into `src/cut.py` directly).

**Expected:** something in the same ballpark as the other two videos, since neither showed camera-specific behavior so far.

| | net_y | segments | labels | precision | recall |
|---|---|---|---|---|---|
| IoU≥0.3 | 457.7 | 22 | 7 | 0.32 | 1.00 (7/7) |
| **IoU≥0.5 (spec)** | 457.7 | 22 | 7 | **0.27** | **0.86 (6/7)** |
| IoU≥0.7 | 457.7 | 22 | 7 | 0.18 | 0.57 (4/7) |

**Conclusion.** Confirms the cross-camera pattern already suspected from two data points: precision sits in a tight 0.25–0.29 band across three different cameras/venues (IMG_7743 0.29, IMG_7744 0.25, pb_draft_cup 0.27) regardless of recall, which swings much more (0.60–0.86). Precision looks like a property of the pipeline/gating logic itself, not something a specific camera's calibration or footage quality is driving. Recall here is the highest of the three, but the label count (7) is the smallest — treat it as a rough read, not a tight one.

**Follow-up.**
1. Not yet FP-reviewed at real playback speed the way IMG_7744 was — unknown whether pb_draft_cup's false positives are hallucinated clutter (IMG_7743's mode) or real abortive exchanges (IMG_7744's mode), or a third thing. Worth doing before drawing conclusions about which fix path (geometric gating vs. rally-completeness signal) has the bigger cross-camera payoff.
2. Reinforces that the two already-open precision follow-ups (IMG_7743's post-`court_wedge` residual FPs, IMG_7744's rally-completeness problem) are worth prioritizing over further per-camera calibration work — three cameras in, calibration/recall keeps improving per-video but precision hasn't moved.

---

## 2026-08-17 (later still) — PIC-2 spike: blob size and confidence do NOT separate real balls from clutter on IMG_7743 — rejected

**PIC-2.** `scripts/pod_infer.py` has recorded each detection's blob size (`W`, `H`) and peak model confidence (`Conf`) since 2026-08-16, but nothing downstream read them — `src/tracknet.py` parsed only `X`/`Y` and hardcoded every candidate's confidence to `1.0`. Hypothesis: an adjacent/far-court ball renders smaller than one on our own court, and a background hallucination (wall texture, netting) should score lower confidence than a real ball — so these two already-computed, already-discarded numbers might cut false positives with no new model.

**Built** (fail-then-pass evidence in `tests/test_tracknet.py`, 6 new/updated tests, full suite 83/83 green): `load_predictions` now parses `W`/`H`/`Conf`, returning `None` for older CSVs or invisible frames rather than crashing or inventing a value. `rally_segments_from_predictions` gained `min_ball_px`/`min_conf` (both default `None` — off, zero behavior change for existing callers) applied alongside `court_wedge`, and no longer hardcodes confidence to `1.0` downstream.

**Regenerated** `IMG_7743_predictions_k14.csv` with the new columns (local GPU, 121,110/121,111 frames, 35.2 min at 57.3 fps — old file predated the code change that records them). Verified the rerun is faithful before trusting it: identical X/Y positions to the old file for every sampled row (same model, same video, deterministic), and the `(min_ball_px=None, min_conf=None)` row below exactly reproduces the already-documented baseline (0.29/0.79).

**Expected:** some real separation — the whole premise of the spike.

**Step 1 — do the two groups' distributions even look different?** Tagged every visible detection across the full video as "inside one of the 33 labeled rallies" or "outside" (absolute time, same 33 labels used throughout this project), split, and compared:

| | size (max(w,h), px) — median | confidence — median |
|---|---|---|
| in-rally (n=5,160) | 15.0 | 0.642 |
| outside (n=31,866) | 15.0 | 0.627 |

Size: identical medians, heavily overlapping IQRs. Confidence: a 0.015 gap between medians, smaller than either group's own spread (IQR ≈0.10 wide). Bad sign before even trying thresholds.

**Step 2 — sweep real thresholds against the 33 labels anyway** (split pre/post camera-bump, same recipe as the 2026-08-17 split-calibration entry, IoU≥0.5):

| min_ball_px | min_conf | precision | recall | matched |
|---|---|---|---|---|
| – | – | 0.286 | 0.788 | 26/33 |
| – | 0.55 | 0.303 | 0.606 | 20/33 |
| – | 0.58 | 0.346 | 0.545 | 18/33 |
| 8.0 | – | 0.307 | 0.697 | 23/33 |
| 12.0 | – | 0.321 | 0.545 | 18/33 |
| **12.0** | **0.58** | **0.347** | 0.515 | 17/33 |

The best precision found anywhere in the sweep (0.347, `min_ball_px=12, min_conf=0.58`) costs 8 of the 26 currently-matched rallies to gain 6 points of precision — every combination trades recall away faster than it buys precision, and none beats the geometry-only baseline (0.286/0.788) on balance.

**Conclusion — rejected.** Neither blob size nor peak-detection confidence, as this TrackNet checkpoint currently computes them, separates real ball detections from background clutter on IMG_7743. The two numbers cluster in nearly the same range whether or not a real rally is happening, so any floor on either one cuts real detections almost as fast as it cuts junk. `court_wedge` (geometry) remains the whole precision story so far — this spike doesn't add to it. Definition of done from the ticket is met: answer is no, with numbers, not a shrug.

**Follow-up.**
1. `min_ball_px`/`min_conf` are kept in `rally_segments_from_predictions` (tested, off by default) rather than reverted — the mechanism is sound and cheap to keep even though this footage doesn't benefit; a different camera/detector combination could still get value from it later.
2. Doesn't touch the two open, higher-confidence precision leads: IMG_7743's post-`court_wedge` residual FPs (still uncharacterized) and IMG_7744's rally-completeness problem (PIC-31) — this result is a negative finding, not a redirect toward a specific fix.
3. Worth a real cause for *why* confidence doesn't separate the groups, if this gets picked up again — one candidate: the confidence value is the peak pixel probability within the model's own thresholded blob mask, which is somewhat self-selecting (a weak blob might not pass the >0.5 threshold to become a detection at all), which could compress the range for anything that clears detection regardless of whether it's a real ball.

---

## 2026-08-18 — Fourth camera scored: brickwall. Highest raw precision yet (0.59), but rally density explains most of it

**Setup.** `brickwall_pro_series_finals.mp4`, indoor tournament play, 25.2 min. Screened with the new `scripts/check_drift.py` before any manual work: 0.2 px total camera travel over the whole file — the most stable footage in the project. Converted 60→30 fps CFR (`videos/brickwall_30fps.mp4`, 45,397 frames, full decode verified). Calibrated with `calibrate_web.py`: **0.345 ft RMSE**, the best in the project alongside pb_draft_cup (0.341), both net-tape points marked. Hand-labeled with `label_web.py`: 33 rallies, graded. TrackNet inference on local GPU with `--calib` court masking (mask kept 53% of frame), 45,396/45,397 frames. Scored with the shipped config (`court_wedge`, `gap_sec=3.0`, `min_crossings=6`, `band=0`).

**Expected:** precision in the 0.25–0.29 band the three previous cameras all landed in.

| | segments | labels | precision | recall |
|---|---|---|---|---|
| IoU≥0.3 | 44 | 33 | 0.73 | 0.97 (32/33) |
| **IoU≥0.5 (spec)** | 44 | 33 | **0.59** | **0.79 (26/33)** |
| IoU≥0.7 | 44 | 33 | 0.50 | 0.67 (22/33) |

Precision more than doubled against every previous camera. Recall (0.79) exactly ties IMG_7743's post-fix best.

**Before treating that as the precision ceiling breaking, the obvious confound was checked — and it is large.** brickwall is a structurally different kind of footage from the other three:

| video | rallies | mean rally | **% of video that is live rally** |
|---|---|---|---|
| IMG_7744 | 10 | 9.4s | 4.0% |
| IMG_7743 | 33 | 10.8s | 8.8% |
| pb_draft_cup | 7 | 11.0s | 12.3% |
| **brickwall** | 33 | **21.8s** | **47.4%** |

Nearly half of brickwall is live play, in rallies twice as long as anyone else's. Both facts inflate precision mechanically: a spuriously-emitted segment is far more likely to land on real play when real play is everywhere, and a long label is easier to cover at IoU≥0.5 than a short one.

**Quantified with a null model.** For each video, the real predicted segments were re-placed uniformly at random (same count, same duration distribution, 400 trials) and scored the same way. That "chance precision" is what each video's density hands out for free:

| video | precision | chance precision | lift over chance |
|---|---|---|---|
| IMG_7744 | 0.25 | 0.02 | 13.7× |
| pb_draft_cup | 0.27 | 0.05 | 5.8× |
| **brickwall** | **0.59** | **0.14** | **4.3×** |

**Conclusion. The 0.59 is real but is not evidence that the precision problem is solved — measured against chance, brickwall is the *worst* of the three, not the best.** The pipeline is doing less discriminative work here than on footage where rallies are sparse; it simply gets more credit for it. The cross-camera "precision pinned at 0.25–0.29" reading from 2026-08-17 is not overturned. What this run does overturn is the assumption that raw precision is comparable across videos at all — it is not, unless rally density is held roughly constant, which it was for the first three (4–12%) and is not for this one (47%).

**Caveat on the lift column:** IMG_7744's 13.7× rests on a chance estimate of 0.02 from only 10 labels, so the exact ordering of the lift figures is not tight. The direction — brickwall's raw precision is substantially density-inflated — does not depend on that ordering.

**Method note.** The scoring script was validated by reproducing the already-published IMG_7744 (0.25 / 0.60, 6/10) and pb_draft_cup (0.27 / 0.86, 6/7) numbers exactly through the same code path, before brickwall's numbers were trusted.

**Follow-up.**
1. brickwall's 18 false positives at IoU≥0.5 have not been reviewed at playback speed — unknown whether they are IMG_7743's hallucinated clutter or IMG_7744's real-but-abortive exchanges (PIC-31). Same open question as pb_draft_cup.
2. The 7 missed rallies are mostly graded 2 (ordinary): rallies 4, 12, 19, 20, 23, 25 are quality 2, rally 22 is quality 1. Worth checking whether ordinary/lower-intensity play is systematically harder, since that would be a different miss mode than the camera-bump one.
3. **Past cross-camera precision comparisons should be re-read with density in mind**, including the 2026-08-17 conclusion that precision is a pipeline property. That conclusion happened to compare three videos of similar density (4–12%), so it is probably safe — but it was never checked, and this run shows the comparison is not automatically valid.

---

## 2026-08-18 (later) — brickwall's "false positives" are mostly fragments of real rallies: a third, distinct failure mode

**Prompted by an operator observation** that brickwall's exchanges are the highest-quality of any footage supplied so far — almost all sustained, competitive points. That is objectively visible as rally *duration* (21.8s mean vs ~10s on all three earlier videos); it is not visible in the quality grades (brickwall 36% grade-1 vs IMG_7743 33%), because grading is relative within a session and cannot express cross-video quality. The observation reframed the question: on footage that is half live rally with long points, what actually *are* the 18 false positives?

**Anatomy of the 18 false positives at IoU≥0.5** (each FP segment classified by how much of it falls inside any labeled rally):

| kind | count |
|---|---|
| entirely inside a labeled rally (fragment) | **10** |
| partial / boundary overlap | 2 |
| genuine dead-time false positive | 6 |

**And every one of the 7 "missed" rallies contains a fragment or partial segment.** Rallies 4, 19, 22, 23, 25 each have one or two segments sitting entirely inside them; 12 and 20 have partial ones. The detector found all 33 rallies. It split the long ones into pieces, so no single piece reached IoU≥0.5 — and each rally was then charged **twice**: once as a miss, and once (or twice) as a false positive.

**Root cause: `gap_sec=3.0` is too tight for 21.8s rallies.** It was tuned on IMG_7743 (ADR-048), whose rallies average 10.8s. A long point contains lulls — lobs, slow dink exchanges, brief detection dropouts — that exceed 3.0s, so `cluster_crossings` cuts the rally in two.

**Confirmed by sweeping `gap_sec`** (IoU≥0.5, everything else at shipped defaults):

| gap_sec | brickwall prec / recall | pb_draft_cup | IMG_7744 |
|---|---|---|---|
| **3.0 (shipped)** | 0.59 / 0.79 (26/33) | 0.27 / 0.86 | 0.25 / 0.60 |
| **4.0** | **0.68 / 0.91 (30/33)** | 0.22 / 0.71 | 0.21 / 0.60 |
| 5.0 | 0.55 / 0.67 | 0.24 / 0.71 | 0.06 / 0.20 |
| 6.0 | 0.54 / 0.58 | 0.11 / 0.29 | 0.09 / 0.30 |

Precision and recall rise **together** on brickwall at 4.0 — the signature of merging fragments rather than trading one metric for the other. Mechanism verified directly: 4 segments at gap=4.0 swallow more than one gap=3.0 segment, total covered time grows 693s → 785s, and merging also lifts several clusters over the `min_crossings=6` bar (new segments at 6–7 crossings). Segment count coincidentally stays at 44 because merges and promotions cancel out.

**Do NOT ship `gap_sec=4.0`.** It is a sharp, video-specific optimum: it degrades both other cameras (pb_draft_cup 0.27→0.22, IMG_7744 0.25→0.21), and brickwall itself collapses by 5.0. The narrow window is mechanically explainable — at 47% rally density the dead gaps *between* rallies are short, so there is only a thin band where the gap bridges within-rally lulls without bridging between-rally ones.

**Conclusion — this is a third failure mode, distinct from the two already logged.** IMG_7743's is hallucinated clutter (geometric, fixed by `court_wedge`). IMG_7744's is real-but-abortive exchanges (PIC-31, needs a rally-completeness signal). This one is **long rallies fragmented by a clustering gap tuned on shorter ones** — a parameterization problem, not a detection problem. The real lesson is that a single global `gap_sec` cannot serve footage with different rally-length distributions; it wants to scale with observed rally length, or be set per venue.

**The density caveat still stands after the fix.** Recomputed chance-adjusted: gap=3.0 gives 0.59 raw / 4.3× lift; gap=4.0 gives 0.68 raw / 4.5× lift. Even with fragmentation repaired, brickwall's lift over chance stays below pb_draft_cup (5.8×) and IMG_7744 (13.7×). Both things are true at once — fragmentation was really costing real accuracy, *and* brickwall's raw numbers still overstate the pipeline relative to sparser footage.

**Follow-up.**
1. The 6 genuine dead-time false positives are the ones worth watching at playback speed — notably a 40.0s segment at 1290–1330s carrying 66 crossings, which is far too sustained to be clutter and may be unlabeled real play rather than a true false positive.
2. An adaptive or per-venue `gap_sec` is now a concrete, evidence-backed proposal rather than a guess. Not yet designed or filed.
3. This result is unreviewed — it changes the read on brickwall and adds a failure mode, and has not been through adversarial review.

---

## 2026-08-18 (later still) — brickwall false positives reviewed at playback speed: only 2 of 44 segments are actually wrong

**Method.** All 6 of brickwall's dead-time false positives were cut as clips and judged by the operator at real playback speed, per the project rule that a rally-vs-dead-time call is not a verdict until someone watches it. The operator supplied not just verdicts but *true crossing counts*, which is what made the diagnosis below possible.

**Verdicts:**

| clip | flagged span | counted | operator verdict |
|---|---|---|---|
| fp1 | 02:48–02:55 | 6 | **junk** — only 3 real crosses; player tossing the ball, its image-y swings across the net line without the ball crossing the net |
| fp2 | 08:43–08:45 | 6 | borderline — 4 real crosses, "borderline ordinary play" |
| fp3 | 10:56–11:03 | 12 | **real rally** (not yet added to labels) |
| fp4 | 12:41–12:51 | 8 | **junk** — 4 real crosses, players tossing the ball back across the net between points (the *courtesy return*) |
| fp5 | 20:48–20:59 | 15 | **real rally** — added as rally 31 |
| — | 21:30–22:10 | 66 | **real rally** — added as rally 33 |

**Full anatomy of all 44 emitted segments**, combining this with the fragmentation analysis above:

| what the segment actually is | count |
|---|---|
| matched a labeled rally | 26 |
| fragment sitting entirely inside a real rally | 10 |
| partial/boundary overlap with a real rally | 2 |
| real rally the labels didn't have | 3 |
| borderline ordinary play | 1 |
| **genuinely wrong** | **2** |

**Only 2 of 44 segments (4.5%) are things the operator would call outright errors.** The measured precision of 0.59 was charging the detector twice for fragmenting long rallies, and again for correctly finding play that wasn't labeled.

**Rescored after adding the 2 confirmed rallies** (35 labels; fp3 still unlabeled so it still scores as a false positive):

| config | segments | precision | recall |
|---|---|---|---|
| shipped (`gap_sec=3.0`) | 44 | **0.64** | **0.80** (28/35) |
| `gap_sec=4.0` | 44 | **0.73** | **0.91** (32/35) |

FP anatomy at the shipped config is now 16 false positives = 10 fragments + 2 boundary + 4 dead-time (the 4 being fp1, fp2, fp3-unlabeled, fp4).

**Hypothesis tested and REJECTED: the hysteresis band does not fix the toss artefact.** `count_crossings` has a `band` parameter built precisely to stop jitter near the net inflating the count, and it ships at `band=0.0` — off. Turning it on does not touch fp1 (stays 6 crossings) or fp4 (stays 8) at any value from 5 to 30 px, while real rallies start disappearing at 15. The reason: a tossed ball swings through a *large* image-y range, so it clears any sane band in both directions. The band suppresses jitter; this is not jitter. (Incidentally `band=10` does improve brickwall overall — 0.59→0.66 precision, 0.79→0.82 recall on the 33-label set — but by removing other segments, not these. Treat it like `gap_sec=4.0`: a single-video optimum, not a default to ship.)

**Two distinct junk mechanisms, needing different fixes:**
1. **Phantom crossings (fp1)** — the ball never crosses the net, but its image-y crosses `net_y`. This is a limitation of using image-y as a proxy for which side of the net the ball is on: a ball high in the air on the near court has a small image-y and reads as "far side". Neither geometry (`court_wedge`) nor the band addresses it.
2. **Real crossings during dead time (fp4)** — the courtesy return. The ball genuinely crosses the net; it just isn't play. This is the *same shape* as IMG_7744's PIC-31 problem, and it was named as a confounder in `PRD.md` §0.6 and ADR-028 before any of this was built. Still unfixed.

**A caution recorded deliberately.** An attempt to characterise these two windows from aggregate trajectory statistics (x/y spread, side-of-net frame counts) did **not** separate junk from real rallies — fp1 has the *largest* horizontal spread of the four windows examined, contradicting a simple "vertical toss in one spot" model. This mirrors the 2026-08-16 IMG_7743 finding, where an aggregate-stats read of false positives was wrong and only a per-frame scatter plot settled it. Any follow-up on mechanism 1 should go straight to per-frame trajectory plotting, not summary statistics.

**Follow-up.**
1. fp3 (10:56–11:03) was confirmed as a real rally at playback but is not in `eval/labels/brickwall_30fps.jsonl`. Adding it would raise precision further. Left as-is rather than inserting a label using the detector's own boundaries, which would be circular.
2. **The other three cameras have never had this review done.** IMG_7743, IMG_7744 and pb_draft_cup precision figures may be understated for the same two reasons (fragmentation double-charging, unlabeled real play). The cross-camera "precision pinned at 0.25–0.29" conclusion rests on numbers that have not had this correction applied.
3. Density caveat still stands: brickwall is now 51.1% live rally, still far denser than the others (4–12%), so raw precision remains not directly comparable.

---

## 2026-08-18 (addendum) — pb_draft_cup is a SINGLES match; format, not camera, drives rally length

**Operator note, recorded because it changes the reading of everything above:** `pb_draft_cup` is a **singles** match. Every other scored video is doubles (brickwall is doubles tournament play; IMG_7743/7744 are casual drop-in doubles). Singles exchanges are inherently shorter — one player covering the whole court produces more winners and errors and far less dinking than four players at the kitchen line.

**This gives rally length a cause, where previously it was just a per-video number:**

| video | format | mean rally | % of video live |
|---|---|---|---|
| brickwall | doubles, tournament | 21.8s | 47–51% |
| pb_draft_cup | **singles** | 11.0s | 12.3% |
| IMG_7743 | casual doubles | 10.8s | 8.8% |
| IMG_7744 | casual doubles | 9.4s | 4.0% |

**Three earlier observations now have a single explanation.**
1. **Why brickwall fragments and pb_draft_cup doesn't.** brickwall had 10 fragment-type false positives, pb_draft_cup exactly 1. `gap_sec=3.0` was tuned on ~10s rallies; it fits singles and casual doubles fine and is too tight only for long competitive doubles points. The fragmentation failure mode is a property of **rally length**, i.e. of format and skill level — not of the camera.
2. **Why the density confound exists at all.** Rally density follows directly from rally length. brickwall's 47% is doubles tournament play; the others' 4–12% is singles or casual play.
3. **Why a single global `gap_sec` cannot work.** The proposed adaptive `gap_sec` now has a real causal variable behind it rather than a hand-wave: it should track observed rally length, which varies by format (singles vs doubles) and standard of play, both of which change per venue and per session.

**Caution on `min_crossings=6`.** It was tuned on IMG_7743 (casual doubles). A singles rally has fewer net crossings for the same duration, so the same threshold is effectively stricter on singles footage. This has not been measured and is not a claim — just a flag that the one tuned threshold in the pipeline may not transfer across formats either.

**Does this weaken the "pb_draft_cup labels look incomplete" suspicion?** Somewhat, but not much. Singles points are shorter, not rarer — 7 labelled rallies across 10.4 minutes still means one point every 89 seconds, with observed gaps up to 160s. The 15 unlabelled detector segments (3–10s, 6–12 crossings) sit squarely inside the duration range of the 7 labelled singles rallies (6.7–18.3s). The suspicion stands, but it is still a suspicion: **only the playback verdicts settle it**, and they are still outstanding.

---

## 2026-08-18 (key result) — pb_draft_cup relabelled: precision 0.27 → 0.59. The cross-camera precision ceiling was a label artefact

**What changed.** The 15 dead-time false positives from the anatomy above were cut into a single review reel and judged at real playback speed. The operator marked **11 additional rallies**, taking the label file from 7 to 18. Nothing else changed — same `predictions.csv`, same calibration, same shipped config (`court_wedge`, `gap_sec=3.0`, `min_crossings=6`, `band=0`), same scoring code.

| | 7 labels (as scored 2026-08-17) | 18 labels (relabelled) |
|---|---|---|
| **precision @ IoU≥0.5** | **0.27** | **0.59** |
| recall @ IoU≥0.5 | 0.86 (6/7) | 0.72 (13/18) |
| IoU≥0.3 | 0.32 / 1.00 | 0.68 / 0.83 |

**Precision more than doubled on ground-truth correction alone.** Of the 15 flagged segments, 8 were real rallies; 7 were confirmed junk. The operator additionally marked 3 rallies the detector never proposed.

**Both properly-labelled videos now sit near 0.6, not 0.25–0.29:**

| video | precision (as previously published) | precision (after playback review) |
|---|---|---|
| pb_draft_cup | 0.27 | **0.59** |
| brickwall | 0.59 (first scoring) | **0.64** |
| IMG_7743 | 0.29 | not re-reviewed |
| IMG_7744 | 0.25 | not re-reviewed |

**Conclusion — the 2026-08-17 finding that "precision is pinned at 0.25–0.29 across cameras, therefore precision is a property of the pipeline's gating logic" does not survive.** The band was an artefact of how the labels were made, not a property of the detector. Two of the three videos supporting it have now been re-measured against corrected ground truth and both roughly doubled. The remaining two (IMG_7743, IMG_7744) have never had this review and should not be cited as evidence of a precision ceiling until they have.

**Why the labels were incomplete is worth understanding, not just fixing.** `EXPERIMENTS.md` (2026-08-09) records IMG_7652 being deliberately curated from 32 marked rallies down to 9 "competitive" ones. `LABELING.md` and `label_web.py`'s own docstring warn against exactly this — grade ordinary play 2, don't delete it, "or the detector gets charged for correctly finding real play." That is precisely what happened here: pb_draft_cup's original 7 labels behave like a competitive-only subset, and the detector was charged for every ordinary rally it correctly found.

**What is genuinely still wrong on this video:**
- **7 confirmed junk segments**, clustered early (00:48, 01:16, 01:30, 02:34, 03:02) plus 07:48 and 08:06 — the early cluster is consistent with warm-up hitting before the match settles.
- **5 missed rallies** (1, 10, 11, 13, 16). Rally 1 (00:02–00:13, 11.3s) is a fragmentation miss — the detector emitted 00:06–00:11 inside it, too short to reach IoU≥0.5. The rest are short singles points of 4.5–7.9s.

**Follow-up.**
1. **Re-review IMG_7743 and IMG_7744 the same way.** Their precision figures are the last support for the ceiling claim and are measured against labels of unknown completeness. IMG_7743's 33 labels over 67 minutes (8.8% density) look sparse by the same standard that flagged pb_draft_cup.
2. Recompute the chance-adjusted lift for pb_draft_cup — its density moved from 12.3% to 26.7%, so the earlier 5.8× figure is stale.
3. **This result is unreviewed.** It overturns the project's stated direction on the basis of one operator's relabelling pass, and should go through adversarial review before it is treated as settled.

---

## 2026-08-19 — IMG_7743 and IMG_7744 re-reviewed at playback speed: label artefact confirmed on the last two videos, closing ADR-050 follow-up #1

**What was done.** `scripts/review_gaps.py extract` (already run 2026-08-18) had produced detector-only candidate lists for IMG_7743 pre-bump (49), IMG_7743 post-bump (12), and IMG_7744 (17) — every detector segment with no matching label. All 78 were graded at real playback speed in `label_web.py`'s GRADE pass (1/2 = real rally, 3 = drop).

**New capability built for this pass:** `label_web.py` GRADE mode originally only played back a candidate's exact `start`/`end` and looped there — enough to judge real-vs-junk, but not enough to fix a *boundary*, since a detector segment spans only first-to-last net crossing, not serve-to-dead (see 2026-08-18 entries above on the two junk mechanisms; the same crossing-envelope logic also truncates real rallies at both ends). Added in-place boundary correction: `s`/`e` in GRADE mode re-mark the current candidate's true start/end, with the original pipeline value preserved alongside it as `detector_start`/`detector_end` rather than discarded or left as a second, detached entry. This mattered in practice — a large fraction of the real rallies recovered below needed a boundary correction, not just a keep/drop verdict.

**Grading outcome:**

| video | candidates reviewed | kept (real rally) | dropped (junk) |
|---|---|---|---|
| IMG_7743 pre-bump | 49 | 21 | 28 |
| IMG_7743 post-bump | 12 | 0 | 12 |
| IMG_7744 | 17 | 10 | 7 |

Merged via `review_gaps.py merge` (dedup at IoU≥0.3 against existing labels):

| video | labels before | labels after |
|---|---|---|
| IMG_7743 pre-bump | 22 | **42** |
| IMG_7743 post-bump | 11 | 11 (no-op — every post-bump candidate was junk) |
| IMG_7744 | 10 | **20** |

**Rescored** (`src/tracknet.rally_segments_from_predictions`, shipped config — `court_wedge`, `gap_sec=3.0`, `min_crossings=6`, `band=0` — called directly against the cached `*_predictions_k14.csv`, no re-inference; pre/post-bump each scored against their own per-half calibration, matching the 2026-08-17 split-calibration method):

| video | IoU | precision (before) | precision (after) | recall (before) | recall (after) |
|---|---|---|---|---|---|
| IMG_7743 pre-bump | ≥0.5 | — | **0.45** | — | 0.74 (31/42) |
| IMG_7743 post-bump | ≥0.5 | — | **0.41** | — | 0.82 (9/11) |
| IMG_7743 combined | ≥0.5 | 0.29 (26/33) | **0.44** (40/53) | 0.79 | 0.75 |
| IMG_7744 | ≥0.5 | 0.25 | **0.54** | 0.60 | 0.65 (13/20) |

**Conclusion — the label artefact from ADR-050 is now confirmed on all four scored videos, not two.** Precision on IMG_7743 and IMG_7744 moves the same direction and by a similar margin as `pb_draft_cup` (0.27→0.59) and `brickwall` (0.59→0.64) did on 2026-08-18. The "precision pinned at 0.25–0.29" reading was a labelling artefact everywhere it was checked, not a property of any one camera. ADR-050's follow-up #1 ("re-review IMG_7743 and IMG_7744 the same way") is done.

**Two things keep this from reading as a clean win, both expected, neither new:**
1. **Recall dipped slightly on IMG_7743 combined (0.79→0.75)** despite every recovered label coming from a detector-proposed candidate. This is the boundary-truncation mechanism made visible in the score itself: correcting a candidate's boundary to the true serve-to-dead span makes it *larger* than the original detector segment, which lowers IoU against that same (unchanged) detector segment — a previously-passing match can now fall under 0.5. Not a regression in the detector; a side effect of measuring against a wider, more honest ground truth.
2. **Precision is still well under 1.0, and the false-positive mix hasn't been anatomized the way brickwall's was** (fragment vs. boundary vs. dead-time junk, EXPERIMENTS.md 2026-08-18). Some of the 38 pre-bump / 13 post-bump / 11 IMG_7744 false positives are likely fragments of rallies that were just correctly recovered above (same rally, different detector-proposed piece, still short of IoU≥0.5 against the now-correct full span) rather than genuine junk. Not broken out here — would need the same reel-and-grade treatment applied to the *false positives*, not just the gaps.

**Follow-up.**
1. Run the fragment/boundary/junk anatomy (as done for brickwall) on IMG_7743 and IMG_7744's remaining false positives, now that labels are trustworthy — needed before citing these precision numbers as a ceiling on the detector itself.
2. This closes ADR-050 follow-up #1. Follow-up #2 (chance-adjusted lift recompute for pb_draft_cup) is still open. Follow-up #3 (adversarial review of the label-artefact conclusion) has still not been done, and now covers four videos instead of two.
3. Consider wiring `court_wedge`-based, per-segment scoring (used ad hoc here via a scratch script calling `rally_segments_from_predictions` directly) into `src/cut.py` proper — today `src/cut.py`'s CLI still only derives the older flat `court_x_range` from `--calib`, not `court_wedge`, so a real re-run of `python3 -m src.cut` would silently score worse than this entry's numbers unless `in_court` is wired in by hand.

---

## 2026-08-19 (later) — FP anatomy on IMG_7743/7744 (PIC-37): the dominant mechanism is real dead-time crossings, not phantom crossings

**Method.** Built `scripts/fp_anatomy.py`, a reusable version of follow-up #1 above. For each of the 62 false positives left after PIC-32's relabelling (38 pre-bump + 13 post-bump + 11 IMG_7744), it first checks the cheap, fully mechanical case — does the false positive overlap or sit within `gap_sec` of a real label? That's a **fragment**: the same burst as an already-labelled rally, just clustered into a separate piece, not a detector error. For everything left, it plots each candidate's raw image-y (vs. `net_y`) and image-x over time from the predictions CSV and reads the shape — per the 2026-08-18 finding that aggregate x/y-spread statistics do **not** reliably separate these cases (the toss artefact there had the *largest* horizontal spread of the windows examined), only a per-frame plot did.

**Fragment count (mechanical, high confidence):**

| video | false positives | fragments |
|---|---|---|
| IMG_7743 pre-bump | 38 | 11 |
| IMG_7743 post-bump | 13 | 1 |
| IMG_7744 | 11 | 4 |
| **total** | **62** | **16 (26%)** |

**Non-fragment classification (visual read of 46 trajectory plots, lower confidence — see caveat below):**

| pattern | what it looks like | likely mechanism |
|---|---|---|
| smooth, repeated arcs crossing `net_y`, correlated x motion | a real ball being hit back and forth | genuine crossing during dead time — courtesy return / between-point practice (PIC-31) |
| short, high-frequency, erratic jumps inconsistent with ball physics (e.g. IMG_7744 1203.3–1204.9s: 6 "crossings" in 1.6s) | tracking noise | hallucinated detection |

| video | non-fragment | real dead-time crossing | noise/hallucinated | ambiguous |
|---|---|---|---|---|
| IMG_7743 pre-bump | 27 | 14 | 10 | 3 |
| IMG_7743 post-bump | 12 | **12** | 0 | 0 |
| IMG_7744 | 7 | 4 | 3 | 0 |
| **total** | **46** | **30 (65%)** | **13 (28%)** | **3 (7%)** |

**Combined across all 62 false positives: fragment 26%, real dead-time crossing 48%, noise/hallucinated 21%, ambiguous 5%.** No candidate read as a clean example of the previously-known *phantom crossing* signature (large vertical range with no genuine net-side change) — every "real motion" plot showed a genuine, physically coherent crossing, not a toss/bounce artefact. The far-side-bounce trigger noted during PIC-32's review (PIC-34 comment) may still be real; it just didn't show up in this batch's non-fragment population.

**This overturns the working assumption behind PIC-34's priority.** Going in, phantom crossings (a contained geometry fix) looked like the leading junk mechanism on IMG_7743, per the 2026-08-18 brickwall entry's two-mechanism framing. On this video the leading mechanism among genuine junk is **real dead-time play** — courtesy returns, between-point warm-up, dinking while resetting — which is PIC-31's territory (needs a game-state signal, not a geometry fix) and was previously thought to be a smaller, `PRD.md` §0.6-named risk rather than the dominant one. Post-bump in particular is *entirely* real dead-time crossings (12/12) — nothing there is a detector flaw at all.

**Caveat, stated plainly: this is a plot read, not a playback verdict**, and the project's own rule (`CLAUDE.md`, `EXPERIMENTS.md` IMG_7744 review) is that rally-vs-dead-time calls need real playback, not stills or derived statistics — a trajectory plot is closer to the former than the latter but is still not the same thing. Two segments are long/high-value enough that being wrong would matter and deserve an actual playback check before trusting this table further: **IMG_7743 pre-bump 863.5–887.9s (24.4s, 28 crossings)** and **2484.3–2502.2s (17.9s, 18 crossings)** — both plotted as clean, sustained, repeated-arc trajectories indistinguishable in shape from a real labelled rally. If either turns out to be a genuine missed rally rather than dead-time practice, it would be a recall finding on top of everything above, not just a mechanism label.

**Follow-up.**
1. ~~Playback-confirm the two flagged long pre-bump segments before trusting this table as final.~~ **Done.** Both watched at real speed: warm-up with a lot of exchanges, not missed rallies. The trajectory-plot read was correct on both of the highest-stakes calls in the batch — real support for trusting the method on the rest of the 46, though only these two got an actual playback check, not all of them.
2. Re-weight PIC-31 above PIC-34 for this video given the above — a game-state/rally-boundary signal looks like the higher-leverage fix here than further geometry work on the net-crossing gate.
3. `scripts/fp_anatomy.py` is reusable for PIC-36 (pb_draft_cup's junk anatomy) and for pb_draft_cup post-relabelling — not yet run there.

---

## 2026-08-19 (later still) — Adaptive gap_sec (PIC-33): a two-pass self-calibrating design beats the fixed constant on every video tested

**The problem, restated with numbers.** `gap_sec=3.0` (ADR-048) was tuned on IMG_7743 (~10.8s average rally). A fixed sweep against the current (post-relabelling) ground truth on the three other scored videos confirms the fragmentation problem is real and video-specific:

| video | precision/recall @ `gap_sec=3.0` | best fixed `gap_sec` found | precision/recall there |
|---|---|---|---|
| brickwall (doubles, tournament, ~22s rallies) | 0.64 / 0.80 | **3.5** | 0.76 / 0.91 |
| pb_draft_cup (singles, ~9s rallies) | 0.59 / 0.72 | 3.0 (already optimal) | — |
| IMG_7744 (casual doubles, ~9s rallies) | 0.54 / 0.65 | 2.5–3.0 (flat) | ~0.60 / 0.60 |

Confirms the already-known trap: `gap_sec=3.5`–`4.0` is a real win for brickwall alone but a loss everywhere else (IMG_7744 falls to 0.38/0.55 at 4.0) — no single fixed constant is right for every video, because rally length is a property of the video (format, skill level), not the pipeline.

**First design tried and rejected: per-crossing local adaptivity.** Idea: let the allowed gap scale with the *median interval between crossings already seen in the current cluster* (`allowed = k * local_median_gap`, clamped) — a fast-paced rally tolerates less pause, a slow one tolerates more, decided causally as the cluster grows. Swept `k` ∈ [2.0, 4.0], floor ∈ [1.0, 2.0], cap ∈ [4.0, 8.0] (60 combinations): **every single combination scored worse than the fixed `gap_sec=3.0` baseline on all three videos.** Root cause understood after the fact: within an active rally, most inter-crossing gaps are short (successive net crossings during play), so a multiple of the local median is systematically *tighter* than 3.0s for most of a rally's own history — the opposite of what's needed to bridge a genuine lull. Rejected; not pursued further.

**Second design, validated: two-pass self-calibration per video.** `src/ball.py`'s new `adaptive_gap_sec(times, min_crossings, base_gap=3.0, k=0.10, gap_min=2.0, gap_max=5.0, ref_duration=10.0)`:
1. Pass 1 clusters at `base_gap` (the existing shipped constant) — a coarse, still-fragmented-where-it-matters estimate of this video's typical rally span (median cluster duration).
2. Pass 2 nudges `base_gap` toward that estimate, scaled down by `k` and relative to `ref_duration` (~IMG_7743's own average, what `base_gap` was itself tuned against): `gap_sec = clip(base_gap + k·(median_duration − ref_duration), gap_min, gap_max)`. Re-clusters the same raw crossings with the derived `gap_sec`.

This works because even a fragmented long rally's *pieces* are still typically longer than a genuinely short video's clusters — the video-wide median carries enough signal to lengthen the gap where it's needed, without hand-fitting a constant per video.

**Sweep result (`k` ∈ [0.06, 0.15], `gap_max` ∈ [3.5, 5.0], `base_gap=3.0`, `gap_min=2.0`, `ref_duration=10.0`, scored at IoU≥0.5 against current labels):** `k=0.10` sits in the middle of a stable plateau (`k`=0.06–0.10 all pass; breaks down above 0.11 on IMG_7744). Final validated result, same raw crossings/predictions as every other number in this file, no re-inference:

| video | fixed `gap_sec=3.0` | adaptive (derived gap shown) | acceptance criterion (PIC-33) |
|---|---|---|---|
| brickwall | 0.64 / 0.80 | **0.76 / 0.91** (gap→3.49) | improve vs. baseline — ✅ (beats even the single-video-optimum 3.5 fixed result) |
| pb_draft_cup | 0.59 / 0.72 | **0.65 / 0.72** (gap→2.80) | do not regress — ✅ |
| IMG_7744 | 0.54 / 0.65 | **0.64 / 0.70** (gap→2.61) | do not regress — ✅ |
| IMG_7743 (combined, sanity check only, not a formal criterion) | 0.44 / 0.75 | 0.44 / 0.74 (gap→2.61–2.70) | ~unchanged, within one-rally noise |

**All four videos improve or hold, including the one `gap_sec=3.0` was originally tuned on.** This is the property the earlier `gap_sec=4.0` proposal (rejected 2026-08-18) never had — that was a single-video optimum that cost precision everywhere else. This is not: the derived gap moves in the *right direction per video* (wider for brickwall's long rallies, narrower for the two short-rally videos) from one shared formula and shared constants, not four hand-picked numbers.

**Shipped as opt-in, not yet the default.** `src.tracknet.rally_segments_from_predictions(..., adaptive_gap=True)` and `python3 -m src.cut --adaptive-gap` (both default `False`, existing behavior unchanged). Held back from becoming the shipped default for two reasons: (1) `k`/`gap_min`/`gap_max`/`ref_duration` were fit against the same four videos being validated against — the classic risk this file has flagged before (`gap_sec=4.0`) — a genuinely held-out fifth video would be a stronger check; (2) PIC-40 (this file, earlier today) already found `src/cut.py`'s CLI doesn't even apply `court_wedge` correctly — promoting a second unvalidated-in-the-real-CLI-path default at the same time would make a future regression hard to attribute to either change.

Tests: 4 new (`tests/test_ball.py` — merges a lulled rally given long-rally evidence elsewhere in the video, tightens for a short-rally-only video, empty-input case; `tests/test_tracknet.py` — end-to-end CSV-to-segments wiring check for the `adaptive_gap` flag). Suite 94 → 98 green.

**Fragment-type-FP check (PIC-33's own acceptance criterion, not just the aggregate number):**

| video | fragment FPs @ `gap_sec=3.0` | fragment FPs @ adaptive | total FPs @ adaptive |
|---|---|---|---|
| brickwall | 12 of 16 | **5** | 10 |
| pb_draft_cup | 2 of 9 | 2 | 7 |
| IMG_7744 | 4 of 11 | 3 | 8 |

Brickwall's fragment count more than halves (12→5) — the mechanism moved, not just the aggregate precision number.

**Follow-up.**
1. Run `--adaptive-gap` against a video not used to fit `k`/`ref_duration` (once one exists) before considering it for the shipped default.
2. Closes PIC-33's core question (a self-calibrating design exists, is validated, and the fragmentation mechanism itself measurably improved); left open as a promotion decision for a future ADR once the held-out check above is done.

---

## 2026-08-19 (yet later) — PIC-31: a self-calibrated duration/rate threshold does not separate real rallies from real dead-time crossings — tested and rejected

**Motivation.** PIC-37's anatomy found real dead-time crossings (courtesy returns, between-point practice) are the dominant remaining false-positive mechanism on IMG_7743 (48%, 100% on post-bump). PIC-31's candidate #1 — a minimum-duration or crossing-rate threshold — is the cheapest thing to try. It cannot be a fixed constant (the same trap `gap_sec` fell into: rally length is a property of format/skill level, e.g. `pb_draft_cup` singles has real rallies as short as 4.5s), so it would need to be self-calibrated per session, with no ground-truth labels available at inference time in real deployment.

**Sanity check first (IMG_7743 post-bump, where all 12 remaining false positives are confirmed real dead-time crossings — no ambiguity):**

| | duration | crossing rate |
|---|---|---|
| real rallies (n=11) | median 11.8s, all ≥7.3s | median 0.80/s |
| dead-time junk (n=12) | median 5.6s, 11 of 12 <7s | median 1.14/s |

Duration alone gets 11 of 12 right on this one video-half — but one dead-time segment (141.10–152.70s, 11.6s, rate 0.60/s) is indistinguishable from a real rally by either measure, and a fixed "≥7s" cutoff would wrongly kill `pb_draft_cup`'s real short singles points.

**Unsupervised check across all 4 videos (5 video-halves), two methods, labels used only to score afterward, never to pick the threshold:**

1. Largest-gap (sort by duration/rate, split at the single biggest jump): found nothing but a lone extreme outlier every time — e.g. brickwall's "split" isolated 1 segment out of 44, telling us nothing about the other 43.
2. 2-means clustering (proper bimodal split): a real but weak signal on crossing rate — e.g. brickwall below-threshold segments were 73% real (vs. a 64% base rate) but above-threshold were still 50% real; pb_draft_cup 69% vs. 59% base, still 33% real above; IMG_7743 pre-bump 52% vs. 45% base, still 24% real above. IMG_7744 showed no signal at all either way.

**Conclusion: rejected.** No video showed a clean separation with either method. The faint tendency (lower crossing rate leans slightly toward "real") is real but far too weak to use as a filter — deployed as a hard cutoff it would misclassify 24–50% of real rallies as junk, depending on the video. This is not a "wrong threshold" problem; the two populations genuinely overlap in duration and pace. Candidate #2 (statistical rally-length modeling) was not separately tested — it's the same signal shape and would be expected to hit the same overlap.

**Follow-up.**
1. Candidate #3 (a signal beyond ball crossings — player positioning, serve-shape, audio) is the one left standing. Brainstormed candidates filed as PIC-42 (backlog, not scoped or prioritized): serve-shaped ball arc, double-bounce at rally end, reviving the frozen player-position/kitchen-formation signal (`src/players.py`/`src/events.py`, ADR-039/047), audio score-calling, audio hit rhythm.
2. PIC-31 stays open — this closes out candidate #1, not the issue.

---

## 2026-08-19 (final) — Eval-set-A locked (PIC-17): overdue, and today's own tuning work is why

**Why this got picked up.** PIC-17 was filed 2026-08-16, flagging that this project had one set of labels doing two jobs — tuning parameters *and* judging how well they worked — and that a 156-setting sweep had already happened despite the Phase 0 gate naming this as a prerequisite. It sat untouched for three days. Today's session made the problem worse before catching it: PIC-33's `gap_sec` search ran ~100 parameter combinations, and PIC-31's threshold check ran two more sweeps, both against the same four videos this project has always used for both tuning and reporting.

**What changed.** `sessions.jsonl` (referenced in `TECH_SPEC.md`'s repo layout, never actually created) now exists, and `LABELING.md`'s pre-existing `dev`/`eval` role table (also written but never populated) is now populated:

| session | role | reason |
|---|---|---|
| IMG_7743 | **eval** (locked) | most-labelled video (53); PIC-33's adaptive-gap search and PIC-31's threshold check already happened to leave it untouched, by construction, not by policy |
| brickwall | dev | only labelled example of tournament-doubles/long-rally play — locking it out of tuning would remove a whole regime |
| pb_draft_cup | dev | only labelled example of singles play — same reason |
| IMG_7744 | dev | casual doubles, same regime as IMG_7743 — the one video that *can* be spared from `eval` without losing a regime |

**The one clean before/after this project actually has:** PIC-33's `adaptive_gap` was tuned only against `dev` (brickwall, pb_draft_cup, IMG_7744) and checked against `eval` (IMG_7743) afterward, without knowing this lock would later formalize that exact split. Re-stated under the new roles: precision/recall on `eval`, fixed vs. adaptive — **0.44/0.75 → 0.44/0.74**. Flat. That's the result this whole lock exists to produce, and it's reassuring that the one piece of recent parameter-search work already behaved this way by accident.

**What this lock does *not* fix — recorded honestly, not swept under it.** The *currently shipped* `min_crossings=6`, `gap_sec=3.0` base, and `court_wedge`'s cap/spread constants were all originally tuned using IMG_7743 itself (2026-08-16 entries, before any lock existed). That history is real and can't be retroactively undone by locking the video now — the shipped defaults carry a genuine, unquantified amount of overfitting to the video that's now `eval`. Re-deriving them against `dev` only, to see whether the current headline numbers survive, is the actual outstanding risk this issue named and is not resolved by writing the roles down — filed as PIC-43.

**Follow-up.**
1. PIC-43: re-derive `min_crossings`, `gap_sec` base, and `court_wedge`'s cap/spread against `dev` only, then report the result on `eval` for the first time as a true held-out number — the check PIC-17 actually wanted, not yet done.
2. Going forward: no sweep may use IMG_7743's labels to pick a parameter or threshold, only to report a final number, per its `eval` role in `sessions.jsonl`.

---

## 2026-08-19 (truly final) — PIC-43: `min_crossings=6` re-derived dev-only, converges on the exact number already shipped

**What this answers.** ADR-048's `min_crossings=6` was picked on 2026-08-16 using only IMG_7743, because it was the only labelled video that existed at the time — not a shortcut, there was nothing else available. PIC-17/ADR-052 locked IMG_7743 as `eval` three days later, after other videos existed. This entry is the first time `min_crossings` has ever been re-derived using only `dev` (brickwall, pb_draft_cup, IMG_7744) — checking whether the number picked on one video's quirks happens to hold up on three completely different ones, or whether it was quietly overfit.

**Method.** Raw net-crossing timestamps computed once per `dev` video (court-wedge gate + `track_ball`, identical to the shipped pipeline). Swept `min_crossings` ∈ {3..10} × gap mode ∈ {fixed `gap_sec=3.0`, adaptive (PIC-33, same `k=0.10`/`ref_duration=10.0` as shipped)} — 16 combinations, scored against `dev` labels only, IoU≥0.5. `eval` (IMG_7743) not touched anywhere in this search.

| min_crossings | mode | brickwall (p/r) | pb_draft_cup (p/r) | IMG_7744 (p/r) | avg F1 |
|---|---|---|---|---|---|
| 3 | fixed | 0.42/0.80 | 0.39/0.72 | 0.15/0.65 | 0.435 |
| 4 | fixed | 0.51/0.80 | 0.42/0.72 | 0.23/0.65 | 0.497 |
| 5 | fixed | 0.58/0.80 | 0.59/0.72 | 0.38/0.65 | 0.602 |
| 5 | adaptive | 0.62/0.86 | 0.65/0.72 | 0.40/0.60 | 0.629 |
| **6** | **fixed (current default)** | 0.64/0.80 | 0.59/0.72 | 0.54/0.65 | 0.650 |
| **6** | **adaptive** | **0.76/0.91** | **0.65/0.72** | **0.64/0.70** | **0.727** |
| 7 | fixed | 0.67/0.80 | 0.75/0.67 | 0.75/0.60 | 0.700 |
| 7 | adaptive | 0.82/0.91 | 0.75/0.67 | 0.87/0.65 | 0.771 |
| 8 | adaptive | 0.84/0.91 | 0.71/0.56 | 0.82/0.45 | 0.694 |
| 9 | adaptive | 0.89/0.91 | 0.86/0.33 | 0.71/0.25 | 0.584 |
| 10 | adaptive | 0.88/0.86 | 0.80/0.22 | 0.71/0.25 | 0.529 |

(3/4 fixed-only and 8/9/10 fixed rows omitted for space — recall collapses on `pb_draft_cup`/`IMG_7744` past `min_crossings=7` regardless of gap mode, same shape as the rest of the table)

**Result: of all 16 combinations, `min_crossings=6` + adaptive `gap_sec` is the only one that improves or holds on every `dev` video with zero regressions** (tolerance ±0.005) against the current shipped baseline (`min_crossings=6`, fixed). `min_crossings=7` (adaptive) scores a higher average F1 (0.771 vs 0.727) but costs real recall on `pb_draft_cup` (0.72→0.67) and `IMG_7744` (holds at 0.65 — borderline) — a genuine precision/recall tradeoff, not a free win, and it fails the same "no regression" bar PIC-33 held itself to.

**The held-out check, `eval` (IMG_7743), untouched throughout this search — already computed earlier today for other reasons:** precision/recall 0.44/0.75 (fixed) vs 0.44/0.74 (adaptive). Flat. No sign the winning config is fit to `dev`'s quirks.

**Conclusion: `min_crossings=6` survives a genuine, independent re-derivation.** A number chosen out of necessity on a single video three days before `dev`/`eval` even existed turns out, when re-searched blind on three different videos, to still be the answer. This is real evidence against the overfitting risk PIC-17 raised — not proof it's the globally optimal number forever, but proof it wasn't a fluke of IMG_7743 specifically. Paired with adaptive `gap_sec` (PIC-33), it's now the only config in this table with no regression anywhere, confirmed both on `dev` (by construction) and on `eval` (by held-out check).

**Follow-up.**
1. `min_crossings=7`/adaptive is a real, documented alternative — higher precision, lower recall, not selected here because it regresses `pb_draft_cup`'s recall. Worth revisiting if the product ever wants to bias toward precision over recall (e.g. a fully-automated reel with no human review step).
2. `court_wedge`'s `cap_court_heights`/`spread` constants remain unchecked against `dev` — the one piece of PIC-43's original scope not done here.
3. This is the strongest evidence so far for promoting `adaptive_gap` from opt-in to the shipped default — it now has a genuine dev-search / eval-check result, not just "tested on the 4 videos that exist." Not promoted in this entry; left as a decision for whoever reads this next, given `PIC-41`'s dual-report tooling still doesn't exist and no video outside the original 4 has ever been run through either path.

---

## 2026-08-20 — PIC-6: labelling self-consistency measured for the first time — presence disagreement is the real noise floor, not boundary jitter

**Method**, per `LABELING.md`'s own (previously unexecuted) consistency-check protocol: the same 5-minute stretch of IMG_7743 (0–300s, `videos/IMG_7743_consistency_0-300s.mp4`) was labelled a second time, in a separate file, without looking at the original labels first — deliberately done the day *after* PIC-32's boundary-correction work on this exact footage (2026-08-19), not same-day, to avoid the recency-bias risk `PIC-6`'s own description named.

**Result.** 5 rallies in the original pass, 7 in the blind second pass. Matched at IoU≥0.5 (project standard):

| | count |
|---|---|
| matched (both passes agree) | **3** |
| original-only (blind pass missed) | 2 |
| blind-only (not in original at all) | 4 |

Only 3 of 9 total distinct rally-windows identified across the two passes were agreed on by both — roughly a third.

**On the 3 matched rallies, boundary spread is small and in line with the project's stated target:**

| original | blind | IoU | start diff | end diff |
|---|---|---|---|---|
| 86.88–95.97 | 85.84–95.72 | 0.87 | 1.04s | 0.25s |
| 146.90–157.33 | 145.18–157.23 | 0.85 | 1.72s | 0.10s |
| 166.80–175.03 | 166.98–173.53 | 0.80 | 0.18s | 1.50s |

Median boundary diff (start and end combined): **0.64s** — close to `LABELING.md`'s ±0.5s aim, not alarming.

**The headline finding is presence, not boundaries.** Whether a given stretch of footage counts as a rally at all disagreed far more than where its edges fall: 2 of 5 original rallies were missed entirely on the blind repeat (63.23–69.48s, 278.93–285.46s), and 4 more were found that the original pass never marked (23.69–32.09s, 115.52–123.05s, 130.81–137.53s, 254.35–260.47s). Given this project's established finding that original labelling passes tend to be incomplete (the whole reason PIC-32's gap-review process exists), some of the blind-only rallies are plausibly real rallies the first pass missed rather than errors in the second — but that can't be settled without a third opinion, and isn't the point. **The disagreement itself is the noise floor**, regardless of which pass is "more correct."

**What this means for every precision/recall number this project has produced, including this week's:** boundary noise (~0.6s median) is small and was already roughly expected. Presence/absence noise — only ~1/3 agreement on whether a window is a rally at all — is a much larger, previously unmeasured source of disagreement, and it's bigger than several of the fine-grained comparisons made this week (e.g., `min_crossings=6` vs `7`'s ~0.05 precision gap, PIC-43). That doesn't invalidate this week's conclusions, but any comparison finer than roughly this noise floor should be read as possibly indistinguishable from labelling noise, not confirmed signal.

**Follow-up.**
1. This result should feed directly into PIC-39 (adversarial review of the label-artefact conclusion) — a labeller-consistency number this loose is exactly the kind of confound a skeptical review would ask about.
2. Not repeated on a second video/labeller — this is one data point (one person, one 5-minute stretch, one video). Treat the ~1/3 presence-agreement figure as a first estimate, not a precise constant.
3. `LABELING.md`'s rally-start/end definition may be tight enough (boundary noise is fine); the presence disagreement suggests the *edge cases table* (courtesy return, warm-up, interrupted rallies) is where the real ambiguity lives — worth revisiting which specific edge case each of the 6 disagreements falls into, rather than stopping at the aggregate number.

**CORRECTION, same day: the ~1/3 presence-agreement figure above is confounded and likely overstates true ongoing noise.** The operator reports that, until very recently (within the last day or two of sessions), they had been unconsciously applying a stricter personal standard than `LABELING.md` actually specifies — mentally gating which exchanges were "worth" marking as a rally at all (by quality/exchange count), rather than marking every real rally and grading quality separately, which is what the written policy has always said and what ADR-050 named as the root cause of the label-completeness artefact. That understanding only fully settled once the quality-grading mechanism (label/grade as a separate step from mark) was worked with directly.

This matters for the number above because **the "original" pass and the "blind" pass in this test were not drawn from the same standard.** The original IMG_7743 labels predate the operator's settled understanding; today's blind pass was made under it. The direction of disagreement fits this exactly: the blind pass found *more* rallies (7 vs 5), not fewer or just different — consistent with the original pass under-marking ordinary-looking exchanges rather than random per-instance disagreement in either direction. This is very plausibly the same mechanism behind why PIC-32's gap-review recovered so many "missed" rallies on IMG_7743/IMG_7744, and why `pb_draft_cup`/`brickwall` gained so many labels on relabelling (ADR-050) — not scattered inattention, but a consistent quality-gating instinct present until recently.

**Consequence: this test needs to be re-run on footage nobody has ever labeled, with *both* passes made under the now-settled standard, to get a number that isn't measuring "old standard vs. new standard."** Today's ~1/3 figure is retained as a data point (it's real, it happened) but should not be read as an estimate of steady-state labelling noise going forward — see the follow-up entry below for the corrected re-run.

---

## 2026-08-20 — PIC-39: adversarial review of ADR-050/051 — 0/3 survived, blocked

**Method.** Three independent agents (skeptic, red-team, simplifier), each with repo read/Bash access, each instructed to default to trying to overturn the conclusion, run in parallel with no visibility into each other's work, per the project's adversarial-review process. Conclusion under review: "the 0.25–0.29 cross-camera precision ceiling was a label-completeness artefact, confirmed by relabelling on all 4 videos (pb_draft_cup 0.27→0.59, brickwall 0.59→0.64, IMG_7743 0.29→0.44, IMG_7744 0.25→0.54)." Majority-survives rule: ≥2/3 SURVIVED confirms, ≤1/3 blocks.

| Lens | Verdict | Key reasoning |
|---|---|---|
| Skeptic | REFUTED | Reproduced published numbers exactly, then measured precision moving 0.290 (independent labels) → 0.449 (human-corrected while watching the detector's clip) → 0.536 (raw detector boundaries) on IMG_7743 pre-bump — a clean boundary-anchoring gradient nobody had checked for. The one non-detector-seeded label set that exists (PIC-6's blind pass) scores the detector at 0.14 on its window, worse than the retracted band. Half the gap-recovered labels in that window failed independent blind re-confirmation. |
| Red-team | REFUTED | `scripts/review_gaps.py`'s extract→grade→merge process seeds every candidate from the detector's own false positives and only ever adds — precision is mathematically guaranteed to rise regardless of true completeness. Ran the project's own required chance-adjusted-lift check (left undone until now, ADR-050 decision bullet 4): the detector's power relative to chance went *down* on 2 of 3 videos. Found a silently corrupted label file (duplicate/nested ground truth on IMG_7744) and an unguarded `merge` that overwrites committed ground truth in place with no backup. |
| Simplifier | REFUTED | ADR-050 and ADR-051 assert the same thing twice; PIC-6's own correction already names the same cause. Cross-checked PIC-6's blind pass against a stale gap-candidate file (`eval/labels/IMG_7743_gaps_all.jsonl`) and found 3 of 4 "extra" rallies the detector had already flagged but were never merged in — the published 0.44 understates completeness in the same direction it's accused of overstating it. |

**Review result: 0/3 survived → blocked.**

**What holds, what doesn't.** The *retraction* half of ADR-050 — "0.25–0.29 is not a hard property of the detector" — survives independently: the 2026-08-09 curated-label habit is separately documented (`PRD.md` §5 violation), and brickwall's fragment finding (FPs sitting inside already-labelled rallies) is provable from existing labels with zero relabelling. What's refuted is the *replacement* — 0.44/0.54/0.59/0.64 as trustworthy numbers, and "four cameras" as four independent confirmations rather than one labeller's still-settling standard counted four times.

**Concrete mechanisms found, not just "it's confounded":**
1. **Structural monotonicity.** Candidates come only from the detector's own false positives (`review_gaps.py:52-56`); the process can convert a FP into a TP but can never create a new FP or recover a rally the detector never proposed. A keep-rate of k on n candidates raises precision by k/n regardless of whether the keeps are correct — verified numerically: keeping a *random* 21 of 49 IMG_7743 pre-bump candidates yields 0.551 with zero variance across 2000 trials, close to the actual graded result of 0.449.
2. **Boundary anchoring.** Precision on the same rally set moves 0.290 → 0.449 → 0.536 as ground-truth boundaries move from independently-drawn to human-corrected-while-watching-the-detector's-clip to raw-detector-boundaries.
3. **Chance-adjusted lift goes the wrong way.** Re-running the project's own null model (uniform-random segment placement, same count/durations, 400 trials, `EXPERIMENTS.md` 2026-08-18 method): IMG_7743 pre-bump lift 7.9x→7.6x, pb_draft_cup 6.2x→4.9x, both down; IMG_7744 8.6x→10.3x, up. 2 of 3 down.
4. **The one independent check fails.** PIC-6's blind pass (not shown any detector output) scores the shipped detector 0.14 on its window (IoU≥0.5) — worse than 0.25–0.29, not better. n=7 segments, statistically thin alone, but consistent with findings 1–2.
5. **Structural asymmetry.** The process can only fix the precision-lowering half of label incompleteness (add a label where the detector already fired), never the recall-lowering half (a real rally the detector never proposed at all). PIC-6 found exactly this: 4 real rallies in a 300s window with no overlapping detector segment under the shipped config — unrecoverable by `review_gaps.py` by construction.
6. **Data integrity.** `eval/labels/IMG_7744.jsonl` contains a nested-duplicate ground truth pair (817.67–846.29 fully contains 839.22–845.87, IoU 0.232, under `merge`'s 0.3 dedup floor) — the same physical rally can score two true positives. `review_gaps.py merge` writes over `--labels` in place (`label.py` `save_rallies`, plain `open(path, "w")`) with no temp-file-and-rename, no backup, and no guard against a missing/mistyped `--gaps` file silently producing an empty merge. `rally_id`s are renumbered on every save, invalidating any prior citation by ID (verified on pb_draft_cup: old ids 1–7 map to new ids 2,3,4,5,9,11,18).
7. **Knife-edge threshold sensitivity.** Injecting PIC-6's own measured ~0.6s boundary noise as jitter (400 trials/video): precision on IMG_7743 pre-bump swings 0.406–0.478 (p5–p95), IMG_7744 0.458–0.583. The published two-decimal figures sit inside labelling noise at IoU≥0.5, which is knife-edge at these rally lengths (26 boundary-corrected labels cluster within ±0.05 IoU of the 0.5 cutoff against their own source segment).

**What would actually resolve it (not "run more experiments," specific):**
1. A blind full-window relabel under the settled standard, seeing neither detector output nor prior labels, on a contiguous 15–20 min slice of a video *not* already touched by multiple review passes — brickwall or pb_draft_cup, not IMG_7743 (locked `eval` per ADR-052, and now touched by three separate passes: original labels, PIC-32 gap review, PIC-6). Score against it; if precision lands near the original 0.25–0.3 band rather than the relabelled 0.44–0.64 band, the jump was the review loop, not the detector.
2. A decoy control: inject randomly-sampled dead-time intervals of matched duration that the detector did *not* propose, shuffled among real candidates during grading. If the labeller keeps a material fraction of decoys, the keep-rate measures the grading UI, not the footage.
3. A second-grader (or same grader, ≥1 week gap) re-grade of the *same* preserved candidate list, reporting keep/drop agreement — PIC-6 predicts this will be poor.
4. Score with boundaries authored blind vs. detector-anchored on the same rally set, to isolate the anchoring effect measured in finding 2.

**Decision, recorded as ADR-053:** ADR-051's replacement figures are downgraded to provisional. Filed follow-ups: none of #1–4 above are built yet. Separately, and more consequentially — this reopens what the project should spend effort on next. Detection precision was never the actual product goal (a highlight reel is), and "highlight-worthy" has no written definition at all, unlike "what is a rally" (which, even *with* a definition, only got ~1/3 agreement per PIC-6). Reprioritized: define "impressive"/"highlight-worthy" concretely and consistency-check that grading the same way PIC-6 checked rally presence, ahead of further detection-precision cleanup.

**Follow-up.**
1. PIC-40/43/38's remaining pieces (court_wedge wiring, court_wedge dev-only re-derivation, pb_draft_cup lift recompute) are deprioritized, not cancelled — they're real but lower-stakes than the above.
2. `scripts/review_gaps.py` and `label.py`'s `save_rallies` need the data-integrity fixes named in finding 6 (safe write, dedup floor, ID stability) before being trusted for further label work, independent of the bigger methodology question.
3. `CHECKLIST.md`/`PROGRESS.md` annotated provisional per ADR-053.

---

## 2026-08-20 — court_wedge wired into src/cut.py (closes the PIC-40 wiring piece); shape validated on dev, margin_px left open

**Found by.** `/committee-review` (new: a third reviewer, Kimi K3, added alongside Gemini and Claude) run against the full codebase, not a diff. Kimi's pass timed out mid-format but the reasoning transcript survived; two claims in it were concrete enough to verify directly rather than trust: `scripts/scan_crossings.py` imports a function (`detect_candidates`) that no longer exists in `src/ball.py` (confirmed by grep — broken YOLO-era leftover, not touched here), and `src/cut.py` wires the flat `court_x_range` gate, not `court_wedge`. Both confirmed true by reading the code directly.

**The bug.** `src/cut.py:25,115` (before this fix) imported and called only `court_x_range`. `court_wedge` was never reachable through `make process` — the actual, documented CLI entry point — despite being cited as "shipped config" in every scoring entry in this file since ADR-048. This is exactly what the 2026-08-19 entry above (line ~840) already flagged in its own follow-up #3 and never acted on.

**Fix.** `cut_rallies_from_predictions` gained an `in_court` passthrough to `rally_segments_from_predictions` (which already supported it — only `cut.py`'s CLI layer was missing the wiring). `main()` now builds `in_court = court_wedge(calib)` by default whenever `--calib` is given and no explicit `--court-x-min`/`--court-x-max` is set; a new `--flat-court-gate` flag opts back into the old flat behavior. 3 new regression tests cover all three paths. Full suite: 101/101 (`tests/`; the pre-existing `archive/` collection error is unrelated, retired YOLO path).

**Validation.** Scored via `rally_segments_from_predictions` directly against cached predictions (no re-inference), shipped defaults (`gap_sec=3.0`, `min_crossings=6`, `band=0`), IoU≥0.5, **dev sessions only** (`brickwall_30fps`, `pb_draft_cup_30fps`, `IMG_7744` — `IMG_7743` is locked `eval` per ADR-052 and untouched here). First pass compared flat@margin=50 (the actual old CLI default) against wedge@margin=160 (`court_wedge`'s own function default) and looked like a clean win everywhere. That comparison silently changed two variables at once (shape *and* margin), so it was redone as a shape × margin 2×2 to isolate them:

| session | flat@50 | wedge@50 | flat@160 | wedge@160 (shipped) |
|---|---|---|---|---|
| brickwall_30fps | 0.636 / 0.800 | 0.622 / 0.800 | 0.636 / 0.800 | 0.636 / 0.800 |
| pb_draft_cup_30fps | 0.500 / 0.611 | 0.600 / 0.667 | 0.478 / 0.611 | 0.591 / 0.722 |
| IMG_7744 | 0.197 / 0.600 | **0.619** / 0.650 | 0.197 / 0.600 | **0.542** / 0.650 |

(precision / recall, `n=44/22/61→24` segments respectively — see follow-up #1 for raw counts)

**Conclusion.** Shape is real, isolated from margin, and validated: zero cost on brickwall (no adjacent-court noise for either gate to catch there), a consistent ~+0.10 precision gain on pb_draft_cup at fixed margin, and the big one on IMG_7744 — the video documented as having adjacent-court noise — where recall is identical at both margins and only false-positive count moves with shape (61 flat vs 21–24 wedge segments). `court_wedge` is doing the job it was built for.

`margin_px` is a separate, smaller, still-open question. The shipped fix inherits `court_wedge`'s own function default (160px) unexamined — same category of gap as the wiring bug, just lower-stakes. The 2×2 shows a real tradeoff, not noise: IMG_7744 prefers margin=50 (0.619 vs 0.542, same recall), pb_draft_cup prefers margin=160 (better recall, 0.722 vs 0.667, at a small precision cost). Two dev videos disagreeing isn't enough to pick a value, and doing so now would repeat the ad hoc-tuning mistake ADR-053 just spent an adversarial review correcting. Left at 160 (unchanged) by decision, not oversight — recorded here so it isn't silently re-discovered later.

**Methodology note.** The single-column first-pass comparison would have attributed all of IMG_7744's gain to shape (0.542) when margin alone was actually costing ~0.08 of it (0.619→0.542 at fixed shape). Decomposing "does gate/parameter X help" into a small factorial (change one thing at a time) caught this before it became a false conclusion. Worth using this pattern for the next parameter-search-shaped question, including the margin_px one above.

**Follow-up.**
1. `margin_px` needs a proper dev-only search (PIC-43-style — multiple dev videos, no eval) before any value is treated as chosen rather than inherited.
2. Raw segment counts for the table above: brickwall 44/45/44/44, pb_draft_cup 22/20/23/22, IMG_7744 61/21/61/24 (flat@50 / wedge@50 / flat@160 / wedge@160, left out of the table for width).
3. `scripts/scan_crossings.py`'s broken import and `scripts/debug_detections.py`'s live YOLO code outside `archive/` (both flagged by the same committee-review pass) — done same day: both moved to `archive/`, `archive/README.md` updated. `calibrate_web.py`'s unused `threading` import and write-only `STATE["saved"]` (same review pass) also removed.

---

## 2026-08-20 — PIC-7 follow-up: testing the built-but-unwired quality signals (`events.py`), and a hand-label leakage bug caught mid-run

**Context.** PIC-7 (2026-08-18) found crossing count alone separates quality grade 1 (highlight) from grade 2 (ordinary) at 73% balanced accuracy on IMG_7743, and named player movement as an untested candidate ("if the frozen v0 player signals are cheap to run on these windows"). Two signals already exist in `src/events.py` (ADR-026/036/037) but were never wired into any pipeline: `mean_motion` (per-frame player displacement, tracking-free) and `n_at_kitchen` (players within 4ft of the NVZ line). Built a local dashboard (`quality_dashboard.py` + `scripts/compute_quality_signals.py`) to test these, plus rally duration, against quality grades on dev sessions (`brickwall_30fps`, `pb_draft_cup_30fps`, `IMG_7744`; `IMG_7743` untouched, locked `eval`).

**Bug caught before trusting the first result.** The first pass windowed every signal — including `duration` — using the *hand label's* `[start, end]`. Flagged during review: at inference time on new footage there is no hand label, only whatever segment the detector itself proposes. `duration` computed as the label's own `end - start` isn't a signal the deployed pipeline could ever produce; it's the label's own field re-measured. This is a milder version of the same shape of mistake `review_gaps.py` made (ADR-053) — using something adjacent to the ground truth as if it were an independent measurement.

**Fix.** Every graded rally is now matched to its actual shipped-config detector segment (`cluster_crossings`, `court_wedge`, `gap_sec=3.0`, `min_crossings=6` — same chain as `src/cut.py`'s new default) at IoU≥0.5, via `eval.harness.iou`/greedy matching. All signals — `duration`, `crossing_count`, `motion_mean`, `motion_max`, `kitchen_mean`, `kitchen_both_up_frac` — are computed from *that* detector segment's own boundaries, never the label's. A rally with no matching detector segment is dropped from the signal set entirely (nothing to rank), not backfilled from the label.

**Side effect: this directly answers a question PIC-7 flagged and never checked.** Match rate by grade, all three dev sessions:

| session | grade 1 matched | grade 2 matched |
|---|---|---|
| brickwall_30fps | 12/13 (92%) | 16/22 (73%) |
| pb_draft_cup_30fps | 2/2 (100%) | 11/16 (69%) |
| IMG_7744 | 2/2 (100%) | 11/18 (61%) |

Opposite of what PIC-7 worried about (quoting IMG_7743's earlier, differently-measured "6 of 11" figure) — here the detector matches grade-1 rallies *more* reliably than grade-2 on all three dev videos. Plausible mechanism, not yet confirmed: `min_crossings=6` is effectively a length gate, and grade-1 rallies tend to be longer (see below), so they clear it more easily; short grade-2 rallies are the ones most likely to fall under the threshold and never produce a segment at all.

**Result, brickwall only (the sole session with enough grade-1 examples, n=12, to trust — pb_draft_cup/IMG_7744 have n=2 each and are excluded from this table; see dashboard's `low_confidence` flag):**

| signal(s) | balanced acc |
|---|---|
| duration | 0.698 |
| crossing_count | 0.688 |
| motion_max | 0.688 |
| duration + crossing_count | 0.688 |
| duration + crossing_count + motion_max | 0.667 |
| all six signals | ~0.62 (worse than any single length signal) |

Method: per active signal, z-score within session (raw scales don't transfer across format — PIC-7), sum z-scores, single global threshold maximizing balanced accuracy (same method PIC-7 used for crossing count alone). Swept all 63 non-empty signal subsets via the dashboard's `/score` endpoint; reported the top ones by brickwall balanced accuracy.

**Conclusion.** Fixing the leakage bug changed the numbers only slightly (0.708→0.698 for duration, 13→12 usable grade-1 examples) — the original finding wasn't an artifact of it, which is reassuring, but the fixed version is the one that's actually meaningful, since it's now built only from information the deployed pipeline could produce for new, unlabelled footage. `duration` and `crossing_count` remain redundant with each other (both proxy "how much play happened") and dominate: no combination of the built player-motion/kitchen signals beats either one alone, and combining everything is worse than either alone. `motion_max` is a new, mildly interesting entrant (tied at 0.688) that wasn't competitive before the fix — plausibly because it's now measured over the detector's own crossing-defined window rather than the human's padded one — but it's one session's data and shouldn't be trusted further without PIC-45.

**Caveat, the one that matters most.** None of this — PIC-7's original 0.73, this entry's 0.70, or anything the dashboard will produce on a future toggle — has been checked against a `quality` grade that's itself been consistency-checked. PIC-45 (grade the same rallies twice, blind, a day apart, same method as PIC-6) is still not done. Until it is, "length weakly predicts a human's highlight grade" is the right-sized claim; "length predicts highlight-worthiness" is not yet earned.

**Follow-up.**
1. PIC-45's consistency check is now the load-bearing next step for all of PIC-7's work, not just a nice-to-have — flagged, not yet started.
2. `motion_max`'s showing after the fix is worth re-checking once a second large-n session exists; one video isn't enough to act on.
3. `scripts/compute_quality_signals.py` needs re-running (cheap, cached) whenever a new dev session is labelled/graded, or if the shipped `gap_sec`/`min_crossings`/`margin_px` defaults change.

---

## 2026-08-20 — `court_wedge`'s `margin_px` re-derived dev-only, shipped default (160) holds — flat, not a fluke

**What this answers.** The `court_wedge` fix (this file, earlier today) shipped with `margin_px=160` inherited unexamined from `court_wedge`'s own function default — flagged explicitly as an open question, not a validated choice. `margin_px` only became a shipped, CLI-reachable parameter today (`court_wedge` was never wired into `src/cut.py` before this session), so it was never part of PIC-43's original three checklist items — those are `min_crossings` (re-derived 2026-08-19), `gap_sec` base (effectively answered via PIC-33's adaptive-gap template), and `court_wedge`'s `cap_court_heights=0.7`/`spread=0.5`, which remain **fully unchecked, not addressed by this entry**. This entry closes the `margin_px` question specifically, using the same dev-only discipline as PIC-43 — it is not a closure of PIC-43 itself.

**Method.** `scripts/search_margin_px.py` — same chain as the shipped pipeline (`court_wedge` gate → `track_ball` → `crossing_times` → `cluster_crossings`, `gap_sec=3.0`, `min_crossings=6`), swept `margin_px` ∈ {30, 50, 80, 110, 140, 160, 200, 250} against `dev` only (`brickwall`, `pb_draft_cup`, `IMG_7744`), IoU≥0.5. `eval` (IMG_7743) not touched.

| margin | brickwall (p/r) | pb_draft_cup (p/r) | IMG_7744 (p/r) | avg F1 |
|---|---|---|---|---|
| 30 | 0.60/0.80 | 0.67/0.67 | 0.61/0.55 | 0.643 |
| 50 | 0.62/0.80 | 0.60/0.67 | 0.62/0.65 | 0.655 |
| 80 | 0.64/0.80 | 0.62/0.72 | 0.57/0.65 | 0.660 |
| 110 | 0.64/0.80 | 0.65/0.72 | 0.54/0.65 | 0.661 |
| 140 | 0.64/0.80 | 0.59/0.72 | 0.54/0.65 | 0.650 |
| **160 (shipped)** | 0.64/0.80 | 0.59/0.72 | 0.54/0.65 | 0.650 |
| 200 | 0.64/0.80 | 0.59/0.72 | 0.56/0.70 | 0.660 |
| 250 | 0.64/0.80 | 0.59/0.72 | 0.52/0.70 | 0.652 |

**Zero-regression check against the shipped baseline (160), tolerance ±0.005:** 30 and 50 regress recall or precision on 2+ dev videos; 250 regresses IMG_7744's precision (0.542→0.519). **80, 110, 140, 160, and 200 all hold with zero regression anywhere** — a wide, flat band, not a single sharp optimum.

**Conclusion.** Unlike `min_crossings` (PIC-43, 2026-08-19), which had one clear winning combination well above the rest, `margin_px` has no real maximum in this range — the best avg F1 in the zero-regression band (110px, 0.661) beats the shipped default (160px, 0.650) by 0.011, which is inside noise already measured on this project (PIC-6: ~1/3 presence disagreement, ~0.6s boundary noise). **The shipped default survives a genuine dev-only re-derivation** — not because it's provably optimal, but because it already sits inside the flat, safe interior of a wide non-regressing range. No change made. The one-time `eval` (IMG_7743) held-out check was deliberately not spent here — there's no new config to confirm, and burning it only makes sense when a decision actually changes.

**Follow-up.** `cap_court_heights`/`spread` — PIC-43's actual remaining scope — are still untouched; `scripts/search_margin_px.py`'s pattern (grid sweep, zero-regression check against the shipped baseline, dev-only) is directly reusable for them, just swept over `court_wedge`'s other two parameters instead. If a future need (e.g. a specific camera's adjacent-court framing) pushes toward the edges of `margin_px`'s tested range, re-run with a finer grid around that edge rather than assuming the flat interior still holds everywhere.

---

## 2026-08-20 — PIC-43 (final piece): `cap_court_heights`/`spread` re-derived dev-only; the dev-favored candidate does NOT hold on held-out `eval` — the exact failure mode PIC-43 exists to catch

**What this answers.** `cap_court_heights=0.7`/`spread=0.5` (`court_wedge`'s own function defaults, never explicitly chosen) are the last unchecked constants from PIC-43's original three-item scope. `min_crossings` was re-derived 2026-08-19; `gap_sec` base was effectively answered by PIC-33's adaptive-gap template; `margin_px` was a separate, adjacent question closed earlier today. This entry does the actual thing PIC-43 asked for: a dev-only grid search, then — for the first time in this project — a genuine, one-time `eval` (IMG_7743) confirmation of whatever dev picks.

**Dev-only search.** `scripts/search_wedge_shape.py`: grid over `cap_court_heights` ∈ {0.4..1.0, None} × `spread` ∈ {0.0..1.0}, 64 combinations, `margin_px` held at its confirmed value (160), scored against `dev` only at IoU≥0.5. **53 of 64 combinations hold with zero regression against the shipped baseline** (another wide, mostly-flat band, same shape as `margin_px`) — but unlike `margin_px`, one region stands out: `cap_court_heights=0.4` (spread 0.5–0.6) reaches avg F1 0.670 vs shipped's 0.650, driven entirely by IMG_7744 improving on *both* precision and recall (0.54/0.65 → 0.61/0.70) with brickwall/pb_draft_cup completely unchanged. This looked like a clean win, not noise — the kind of candidate that's earned a held-out check, unlike `margin_px`'s genuinely flat result.

**Mechanism check, done initially from a still calibration frame, then corrected against the actual detection data, then confirmed by direct human review of real footage (CLAUDE.md's own rule — verify from playback, not a still frame or assumption).** The first-pass explanation offered here was "a tighter ceiling filters more of IMG_7744's spurious high-frame detections" — plausible-sounding, matching `court_wedge`'s own docstring, and **wrong**. Checked in two steps:

1. Pulled every detection in `cache/IMG_7744_predictions_k14.csv` falling in the band the two caps disagree on (image-y between the cap=0.4 and cap=0.7 lines, 2141 detections). If this were mostly static ceiling-light hallucinations, they'd cluster at a handful of fixed positions. `x` instead spans 586 to 1918, nearly the full 1920px frame width — not the signature of a small number of static false-positive sources.
2. Pulled 12 real frames at actual detection timestamps in that band (4 from the one mildly concentrated spot ~150–180px above the net line, 8 spread across the rest of the band) and marked exactly where TrackNet reported the ball. Operator reviewed all 12 against the real footage: **all 12 are the ball, correctly detected, in real play** — not lights, not clutter, not a tracking artefact.

**The band is genuine signal, confirmed, not junk of any kind.** So the tighter cap's dev-search win came from discarding real ball detections — high, but real, moments of play (plausibly overhead/attacking shots near the net, given the concentration point sits ~150–180px above net height) — not from filtering anything spurious. That doesn't fully explain *why* discarding real data happened to improve `IMG_7744`'s dev-measured precision and recall (a real detection removed mid-rally still leaves `track_ball` able to re-acquire the same ball once it drops back below the cap, so the mechanism for how this nets out at the rally-segment level isn't traced end-to-end here) — but it removes the false explanation cleanly, and it makes the held-out `eval` result make much more sense: discarding genuine ball data is inherently video-dependent and risky, which is exactly consistent with it costing precision on `eval` while happening to help two specific dev metrics on one video.

**Held-out `eval` check (IMG_7743, first genuine use this project has made of this discipline) — same pre/post-bump split-calibration method as 2026-08-17:**

| config | eval precision | eval recall | eval F1 | dev avg F1 |
|---|---|---|---|---|
| shipped (cap=0.7, spread=0.5) | 0.440 | 0.755 | **0.556** | 0.650 |
| candidate (cap=0.4, spread=0.5) | 0.423 | 0.774 | **0.547** | 0.670 |

**The candidate does not hold.** On `eval`, it isn't a clean win at all — it trades precision for recall (0.440→0.423, 0.755→0.774) rather than improving both the way it appeared to on `dev`, and comes out slightly *behind* the shipped default on F1 (0.547 vs 0.556). A config that looked unambiguously better on three dev videos turns out to be a wash — arguably a net loss — on the one video never touched during selection.

**Conclusion.** `cap_court_heights=0.7`/`spread=0.5` are kept, unchanged. This is exactly the outcome PIC-43's own issue text anticipated as a live possibility ("if the eval number is materially worse... that is the real finding this exercise exists to surface, not a failure to hide") — and it's the first time this project has actually run the dev-search → eval-confirm loop all the way through and found the dev winner *doesn't* survive. `min_crossings=6`+adaptive (2026-08-19) and `margin_px=160` (earlier today) both survived this same kind of check when it was available; this is the first constant that didn't, and it's informative precisely because the other two didn't fail the same way — it's evidence the held-out check is doing real work, not passing everything through.

**This closes PIC-43.** All three original constants (`min_crossings`, `gap_sec`, `court_wedge`'s shape parameters) have now been re-derived dev-only and reported against `eval` at least once, per the issue's own checklist. `margin_px`, not part of the original scope, was closed alongside it.

**Follow-up.**
1. The mechanism hypothesis (tighter cap filters IMG_7744-specific spurious high detections) is now weaker evidence than it looked — worth remembering if IMG_7744-specific tuning comes up again, since the same reasoning was used to justify a change that didn't survive held-out validation.
2. `eval` has now been touched once this phase, per `LABELING.md`'s rule — no further `eval` scoring should happen until the next phase boundary, regardless of how promising a future dev candidate looks.

---

## 2026-08-20 — PIC-42 candidate check: zero-shot paddle detection (YOLO-World) works on real footage, untrained

**Context.** PIC-42 (signals beyond ball-crossing for telling a real rally from a casual exchange) is a parking spot for untested candidates; its own rule is to check a signal separates real signal from noise *before* building anything. Paddle tracking wasn't one of the five listed candidates — came up in conversation as an alternative to reviving `src/players.py`'s foot-point data (which is the wrong height for hit detection — it's a ground-contact point, not a hand/paddle position). Plain COCO-pretrained YOLO (`yolov8n.pt`, already used for player detection) has no "paddle" class and won't detect one. Checked whether a zero-shot open-vocabulary detector could, with no training at all, before considering a real custom-training effort.

**Method.** `ultralytics.YOLOWorld` (`yolov8s-world.pt`), prompted with `["paddle", "table tennis paddle", "racket", "tennis racket"]` — no pickleball-specific class exists in its vocabulary, closest concept is "tennis racket." Tested against `cache/IMG_7744_calib_frame.png` (a real, unmodified calibration frame, 4 players visible, 3 holding paddles near the net) two ways: a zoomed-in crop, and the full frame at native resolution with no cropping.

**Result.**
- Zoomed crop: all 3 visible paddles correctly boxed, labeled "tennis racket" (conf 0.10–0.39).
- **Full frame, no cropping, `imgsz=1920`**: correctly detected the paddle at the nearest player's hand (conf=0.50) plus 3 lower-confidence hits on the other players' paddles — all real, all correctly positioned, no manual help.
- At the default `imgsz=640`, this same full frame produced **0 detections** — paddles are too small in a wide establishing shot at that resolution. Needed full resolution to register at all, which costs more per-frame compute than the 640-default inference this project already runs for players/ball.
- One environment side effect: `ultralytics` auto-installed `git+https://github.com/ultralytics/CLIP.git` into `.venv` on first `YOLOWorld` import (needed for its text-prompt encoding) — not requested, flagged rather than left silent.

**Conclusion.** Zero-shot paddle detection is viable on this project's real footage without any custom training or labeled data — genuinely promising as a cheap first move on PIC-42's paddle-tracking idea. Not proven yet: this is one still frame, not a video — fast swing motion and motion blur during an actual hit are the real test, and haven't been checked. Also unresolved (flagged when this idea first came up): even with working paddle detections, naively combining paddle position with ball trajectory isn't guaranteed to help — a 2026 racket-sports benchmark (RacketVision, tennis/table-tennis/badminton) found naive concatenation of racket-pose features *hurt* trajectory prediction; a real fusion mechanism was needed to see any gain. Getting detections is step one, not the whole answer.

**Follow-up.**
1. Run this against a short real clip (not a single frame) to check whether detection holds up through actual swing motion and blur, before investing further.
2. If it holds up on video, the actual product question (does paddle-contact timing help separate real rallies from dead-time, PIC-31's original problem) is still untested — detection working is a prerequisite, not the answer itself.
3. `imgsz=1920`'s compute cost needs to be weighed against just detecting paddles in a lower-res proxy stream if this goes further, similar to the proxy-video idea already on record for the cloud-hybrid architecture (PROGRESS.md, 2026-08-12).

---

## 2026-08-20 — PIC-42 paddle-tracking candidate, follow-up #1: fails on real video — the single-frame test was misleading

**What this checks.** Follow-up #1 from the entry above: does `YOLOWorld` hold up across an actual rally, not one lucky still frame. Ran it at every frame (30fps, `imgsz=1920`) across a full real rally (`IMG_7744` rally 4, grade 1, 390.4–401.0s, 320 frames), `conf>=0.05`.

**Result: it does not hold up. Two distinct, real failure modes, not just occasional noise.**

1. **A systematic false positive.** The blue net-post roller equipment (visible at both net posts in every frame) gets confidently misdetected as "tennis racket" — 0.47 confidence in one frame, 0.06 in another. Same wrong object, not a one-off.
2. **Real paddles frequently missed entirely, even outside fast motion.** In one representative mid-rally frame, all 3–4 paddles visible in normal ready-position (players just standing, not mid-swing) produced **zero detections** — the only box present was, again, the net-post roller. This isn't a motion-blur problem specifically; the detector is unreliable on paddles held plainly in view.
3. **Duplicate/overlapping boxes on the same real paddle** at low confidence thresholds (one frame produced 15 boxes clustered around what's realistically 4 real paddles) — `YOLOWorld`'s NMS isn't cleanly collapsing near-duplicate detections at this threshold.

**No confidence threshold resolves this cleanly.** Swept `conf` from 0.05 to 0.3 across all 320 frames: low thresholds keep the false-positive/duplicate-box noise (many frames with 5–16 "paddles"); raising the threshold to clean that up produces 50–62% of frames with **zero** detections at all. There's no middle value that gives reliable, clean per-frame paddle counts.

**Conclusion.** The earlier single-frame test (this file, entry above) was real but misleading as a signal of readiness — it happened to land on a frame where the zero-shot vocabulary ("tennis racket," the closest concept to a pickleball paddle) worked. Across real play, it doesn't generalize: a systematic false-positive source (net-post equipment) and frequent misses of clearly-visible real paddles make the raw output unusable as-is for anything downstream (contact detection, or even just "how many paddles are in this frame"). This is exactly the caution flagged in the prior entry's follow-up #1, now confirmed.

**Follow-up.**
1. Plain zero-shot `YOLOWorld` is not viable for paddle tracking as tested. Before spending more effort here: try a heavier zero-shot detector (Grounding DINO) to see if the false-positive/miss pattern is `YOLOWorld`-specific or general to zero-shot detection on this footage; or reconsider whether this whole direction is worth a real custom-trained detector instead (RF-DETR, per the earlier model-landscape check) given zero-shot didn't hold up cheaply.
2. The net-post-roller false positive is worth remembering independent of paddle tracking — any future object-detection work on this footage (player detection, paddle detection, anything YOLO-family) should be aware that blue net-post equipment is a recurring confusable object.
3. This does not touch PIC-31's actual question (does *any* non-ball signal separate real rallies from dead-time) — paddle tracking was one candidate way to get at ball-contact timing, and it's now the second candidate (after the duration/rate threshold, PIC-31) to come back negative on this project.

---

## 2026-08-20 — PIC-42 paddle-tracking candidate, follow-up #2: Grounding DINO recovers cleanly where YOLO-World failed

**What this checks.** Follow-up #1's own recommendation: is the zero-shot failure `YOLOWorld`-specific, or general to zero-shot detection on this footage. Installed `transformers` (HuggingFace's `IDEA-Research/grounding-dino-tiny`, the standard way to run Grounding DINO now) and re-ran the identical test — same rally, same frames, prompted `"a paddle. a tennis racket."`.

**Result: meaningfully better, not just different.**
- **99% of frames (316/320)** have at least one plausible paddle-scale detection (`area<15000px²`), versus `YOLOWorld`'s pattern of alternating between noise-heavy and empty. Count distribution peaks at **4** (67 frames) — matching the real number of paddles in view — not scattered 0–16 the way `YOLOWorld`'s was.
- Checked the *exact* frame (t=395.4s) where `YOLOWorld` completely failed — zero real detections, false-positived on the net-post roller instead. Grounding DINO gets **3 of the 4 real paddles correctly, tightly boxed** on that same frame.
- A second spot-check frame (t=390.4s, near serve) again: all 3 visible paddles correctly boxed.

**Two known, filterable failure modes remain — not a clean solve, but a tractable one:**
1. **Whole-body boxes** (a large box spanning an entire player, ~0.15–0.26 confidence — overlapping the real paddle boxes' confidence range, so threshold alone won't separate them). Filterable by size: real paddle boxes are consistently small (tens to low hundreds of px²), whole-body boxes are an order of magnitude larger. The `area<15000px²` filter already used above catches this.
2. **The net-post roller — the same confusable object `YOLOWorld` also misfired on** — persists as a secondary detection in both spot-checked frames, small enough to survive the size filter. Unlike the whole-body case, this needs a different fix: the net-post rollers sit at a roughly fixed position relative to the calibrated net line, so a position-based exclusion (similar in spirit to `court_wedge` excluding off-court regions) is the natural next filter, not a confidence or size threshold.

**Cost.** ~0.4s/frame on GPU (`grounding-dino-tiny`) — about 10x slower than `YOLOWorld`'s ~0.034s/frame, but still under 2 minutes for a full 320-frame, 10.6s rally. Real cost at full-video scale, not free, but not prohibitive for testing.

**Conclusion.** The `YOLOWorld` failure was largely model-specific, not a fundamental limit of zero-shot detection on this footage. Grounding DINO is a real candidate to build on — genuinely usable paddle localization once the two known false-positive sources are filtered (one already solved by size, one with a clear, cheap fix available). This reopens the paddle-tracking direction that follow-up #1 had mostly closed.

**Environment note.** `transformers` (HuggingFace) installed into `.venv` for this test — not previously a project dependency.

**Follow-up.**
1. Build the position-based net-post exclusion (reuse existing calibration data, same pattern as `court_wedge`) and re-run the full-rally check with both filters applied together — the real bar is "clean paddle count per frame across a whole rally," not spot-checked frames.
2. Still unproven end-to-end: even clean paddle positions need to be combined with ball trajectory to detect an actual contact event (the original ask) — detection quality was the blocker being tested here, not the full pipeline.
3. Revisit PIC-31's actual question once contact detection exists: does paddle-contact timing distinguish real rallies from dead-time exchanges any better than the duration/rate threshold already ruled out.

---

## 2026-08-20 — PIC-42 paddle-tracking candidate, follow-up #3: tried a second camera (brickwall) instead of the net-post filter — found different clutter, `court_wedge` solves it only partially

**What this checks.** Follow-up #1/#2 only ever tested one camera (IMG_7744). Before building a filter anchored to IMG_7744's specific false-positive object (the net-post roller), ran the identical Grounding DINO pass against a `brickwall` rally (10s, 300 frames at 30fps, `t=2.55-12.55s`, the session's first labelled rally) — a different camera, different court, different venue entirely. Watched the result as an actual annotated video (all 300 frames re-encoded to mp4 with detection boxes + calibrated net-post markers drawn on, opened in VLC), not stills — this project's own rule for judging real-vs-noise calls.

**Result: brickwall has no net-post roller (checked by eye first — plain black net stand, no equipment) and no false positives near the net posts at all. But it has two different recurring false-positive hot spots, neither related to the net:**

1. **A maintenance pole/squeegee leaning against the wall on the upstairs spectator balcony** (image region ~x=280±60, y=130±60) — 307 detections there across the 300-frame clip. Its rounded white head is genuinely paddle-shaped in silhouette, a real static object, same *category* of mistake as IMG_7744's roller (a fixed off-court object with a paddle-like shape) but a completely different object.
2. **An item near the front check-in desk** (~x=600±60, y=245±60) — 591 detections, persistent across the clip. Possibly a real paddle held by someone off-court, not confirmed a hallucination the way the pole is.

Real paddles were still detected correctly in the same frames (both players' paddles boxed in frame 99, e.g.) — the detector itself keeps working; what it hallucinates is different per venue.

**This ruled out a net-post-specific filter as the next build and motivated trying `court_wedge` (the off-court gate already shipped and validated for ball detections) instead** — the reasoning being that every false-positive source found so far, across two cameras, is a real, static, *off-court* object.

**Built:** `src/paddles.py`'s `filter_paddle_boxes(boxes, calib, area_max=15000.0, **wedge_kwargs)` — area filter for whole-body boxes, then `court_wedge(calib)` applied to each box's center. 5 new tests (`tests/test_paddles.py`), full suite 112/112 (`tests/`; the pre-existing `archive/` collection error is unrelated, retired YOLO path).

**Validated against all 2,289 raw brickwall detections from the video above, not just the spot-checked frames:**

| region | raw count | `court_wedge` @ shipped margin_px=160 | @ margin_px=100 |
|---|---|---|---|
| balcony pole | 307 | 307 survive (untouched) | **0 survive — fully removed** |
| front-desk item | 591 | 591 survive | **591 survive — untouched at any margin, including 0** |
| everything else (likely real) | 1,122 | 1,118 survive | 1,079 survive (~3.5% collateral loss) |

**Mechanism, checked directly rather than assumed:** the balcony pole is only excluded once `margin_px` is tightened well below the shipped 160 (tuned for ball detections, not this) — at 160 the pad is simply wide enough to still include it at that image depth. The front-desk item can't be excluded by `court_wedge` at *any* margin, because at that image height its x-position falls **inside** the court's own reprojected corridor — `court_wedge` only reasons about the court's x-extent at each image depth, with no notion of "behind the baseline fence." A real ball or paddle at that same image position would be geometrically indistinguishable to this gate.

**Conclusion.** `court_wedge` is a real, partial win — it fully solves the balcony-pole-shaped problem (an object off to the side of the court's projected column) once its margin is re-derived for this purpose, but it structurally cannot solve the front-desk-shaped problem (an object that happens to sit inside the column). Reusing the ball-detection gate as-is (shipped margin) does nothing for either case tested here — it must be re-tuned specifically for paddle filtering, not inherited.

**Open question raised by this (not yet answered): there is no single static geometric mask that will generalize across venues.** Two cameras in, already two different confusable objects (net-post roller, balcony pole) plus one filter-proof case (front-desk item) — a real venue will keep introducing new off-court objects a hand-tuned position mask can't anticipate. This argues for a filter based on something that stays true across every venue, not the specific geometry of any one of them — e.g. proximity to an actually-detected player (a real paddle is attached to a person's hand; none of today's three false-positive sources are).

**Same-day addendum: distance-to-nearest-player checked, and it only solves one of the two cases.** Ran `src/players.py`'s existing YOLO person detector (`sample_fps=5.0`, COCO 'person' class, no new training) over the same clip and measured each false-positive/real detection's distance to the nearest detected person box:

| region | n | median dist-to-player |
|---|---|---|
| balcony pole | 307 | 189px |
| front-desk item | 591 | **0px** |
| everything else (likely real) | 1,122 | 0px (p90 = 2px) |

The balcony pole separates cleanly (189px vs. a real-detection band that never exceeds 2px at p90) — a clean binary split, no threshold-picking needed. **The front-desk item does not separate at all** — it sits at the same near-zero distance as genuine paddle detections, because YOLO correctly detects the person standing at the desk holding it; proximity-to-*any*-person can't tell a playing player from a bystander. This is itself informative: it isn't just this instance of the case that fails, it points at *why* the case is hard in a way that generalizes — the missing distinction is "on-court player" vs. "any detected person," which position-based reasoning alone (court_wedge or a simple distance-to-person check) can't supply without also knowing which people are inside the court.

**Follow-up.**
1. Re-derive `margin_px` specifically for paddle filtering (dev-only, same discipline as PIC-43) — the shipped ball-tuned 160 was shown here to do nothing for the one case it can solve.
2. Distance-to-player is a genuine partial win (balcony pole, cleanly), but the front-desk case needs the *on-court* distinction specifically — e.g. gate on distance to a player that itself passes `src/players.py`'s existing `on_court` check, not any detected person. Not yet checked whether that combination actually clears the front-desk case; the desk person may well be standing close enough to the court boundary to pass a loose `on_court` margin too.
3. Both hot spots' `dist_to_post`-style measurements (this file, follow-up #2's net-post radius check) and this margin-based one point the same direction: a purely static, position-based mask is inherently a per-venue patch, not a general solution. Distance-to-player generalizes better (no venue-specific geometry needed) but isn't sufficient alone either — the emerging pattern across `PIC-31`/`PIC-42`'s candidates so far is that no single signal cleanly separates real from spurious; combining weak signals is the likely shape of an eventual answer, not finding the one filter that works.

---

## 2026-08-20 — PIC-42 paddle-tracking candidate, follow-up #4: compound-phrase prompting doesn't fuse concepts (documented, confirmed); explicit on-court-player pairing does, partially — same ceiling as court_wedge, for a confirmed real-world reason

**What this checks.** Two follow-ups on the same open question: does anything cleanly separate a real on-court paddle from the front-desk/balcony false positives without a per-venue geometric mask.

**Attempt 1: prompt Grounding DINO with the compound concept directly** (`"a person holding a paddle."` instead of `"a paddle. a tennis racket."`), on the theory that requiring the joint concept might exclude a real object held by a non-playing person, or a real person standing near a non-paddle object. **Does not work, and the reason is documented, not a quirk of this prompt's wording:** Grounding DINO uses "sub-sentence level text features" specifically to let one query return multiple independently-grounded phrases. Confirmed on the same 300-frame brickwall clip — the compound prompt just adds standalone `"person"`/`"a person"` detections on top of the existing `"paddle"` ones (balcony: 86× "a person", 12× "person", 0 fused detections; desk: 97× "a person", 19× "paddle", 17× "person"). Checked the actual boxes: at the balcony, it now tightly boxes the *real spectator* standing there — a real person, correctly labeled, just not a playing one. The joint concept has to be enforced by code, not by prompt phrasing.

**Attempt 2: explicit fusion in code.** Built `src/paddles.py`'s `filter_paddle_boxes_by_on_court_player(paddle_boxes, player_boxes, calib, max_dist_px=150.0, **on_court_kwargs)` — pairs each paddle box to its nearest detected player box (`src/players.py`'s existing YOLO person detector, already used for `mean_motion`/`n_at_kitchen`), then requires that specific player to pass the existing `on_court` check (via `foot_point` + homography projection), not just any nearby person. 4 new tests added to `tests/test_paddles.py` (9 total in that file, on top of follow-up #3's 5), full suite 116/116 (`tests/`).

**Validated against the same 300-frame brickwall clip and the same three groups (balcony pole, front-desk item, everything else), with real player detections (`detect_players`, `sample_fps=5.0`), not synthetic data:**

| region | raw (paddle-scale) | default (`y_margin=10`) | `y_margin=2.0` |
|---|---|---|---|
| balcony pole | 130 | **1 survives** | 1 survives (unchanged) |
| front-desk item | 591 | 557 survive (barely touched) | **274 survive (54% reduction)** |
| everything else (likely real) | 1,122 | 1,031 survive | 1,031 survive (no extra cost) |

**Balcony: fully and robustly solved** — not near any player, on-court or off, at any margin tested. **Front desk: only partially solved, and the reason was measured directly rather than assumed.** Projected the desk bystander's actual foot point through the calibration: **court coordinates (5.9ft, 53.8ft)** — inside the court's 20ft width, only 9.8ft behind the 44ft baseline. The default `y_margin=10` (deliberately generous — built to keep real players who lunge deep for lobs) lets them through because they are, in real-world feet, that close to the court. Tightening `y_margin` to 2.0 roughly halves the desk survivors with *zero* additional cost to real detections (`rest` holds flat from `y_margin=10` down to `2.0`, then craters past `0.5` — over half of real detections lost below ~1ft margin, a sharp cliff not worth crossing). The remaining 274 desk-area survivors pair with a *different*, genuinely on-court player nearby (plausibly someone near the baseline corner) — not fixable by this lever at all, because the pairing itself is correct; the ambiguity is real.

**Conclusion.** Two independent filters (`court_wedge`'s off-court gate, this on-court-player fusion), tested on two different cameras, hit the *same shape* of ceiling: each fully solves the case that's geometrically/spatially distant, and only partially solves the case that's genuinely close to the court in the real world. This sharpens the open question from the previous entry: it isn't just "every venue has new clutter a hand-tuned mask can't anticipate" — some off-court objects/people are close enough to real play, in actual feet, that position-based reasoning of any kind (geometric mask or player-proximity) structurally cannot separate them from legitimate deep-court play. That's not a bug to keep tuning around; it's a ceiling on what a purely spatial signal can do here.

**Follow-up.**
1. Neither `court_wedge`'s `margin_px` nor this filter's `y_margin` is re-derived/chosen yet — both were spot-checked on one clip. If either direction is pursued further, needs the PIC-43-style dev-only sweep before being called a real default.
2. The next lever that isn't purely spatial: gate on whether the frame falls inside an actual detected rally window (`cluster_crossings`'s own output) — a bystander at the desk has no reason to be active specifically during live points, whereas a real deep-court player does. Untested; would need per-frame rally-window membership, which the pipeline already computes for other purposes.
3. Confirms `PIC-31`/`PIC-42`'s recurring pattern one more time: no single signal (duration/rate, zero-shot detection choice, prompt phrasing, geometric mask, player-proximity) cleanly separates real from spurious on its own.

---

## 2026-08-20 (later) — PIC-10: attempted to score the Gemini rally verifier; blocked before a single clip processed, but the eval-scoring machinery is now real and reusable

**What this attempts.** `PIC-10`'s own spec: standardize clip encoding, run `src/verify.py` over the detector's proposed segments on `IMG_7743`, score its verdicts against the 33 hand labels, compare against just raising `min_crossings`. Motivated by a broader push this session to look past crossing-count arithmetic toward more capable signals.

**Reproduced the detector's segments properly first, and found a real discrepancy worth flagging.** Using the project's own documented split-calibration method for `IMG_7743` (pre/post camera-bump at t=2900s, separate calibration per half, ADR-049) at IoU≥0.5: **91 segments, 26 matches (TP), 65 false positives** — precision 0.286, recall 0.788. This exactly reproduces the *segment count* from the 2026-08-17 split-calibration entry (91), but **not** the precision/recall figure `PIC-43`'s held-out `eval` check reported earlier this session (0.440/0.755) for what should be the same shipped config. Not reconciled — likely an informal-IoU-vs-0.5 difference (the 2026-08-17 entry predates this project's IoU≥0.5 convention per `CLAUDE.md`'s own caveat) or a config difference (`adaptive_gap` on/off) not carried over faithfully here. Flagged, not chased further this session — whoever picks up `PIC-10` next should reconcile which number is right before trusting either for a new comparison.

**Standardized the encoding question `PIC-10` itself asks for**, by fixing it to what's actually true rather than picking a new recipe: clips cut with the exact same `ffmpeg` command production already uses (`src/render.py`'s `clip_command` — libx264, veryfast, no audio) plus the same `pad_sec=3.0` real output gets. This is the fairest test available — it scores the verifier against what a real deployed post-filter would actually see, not an arbitrary third encoding. All 91 clips confirmed well within Gemini's inline-request size limit (max 24.4s + padding ≈ 30s; the earlier project note about a size problem was for a 5-minute clip, not these).

**Blocked immediately, before any real result.** All 6 pilot calls (3 TP, 3 FP) returned `429 RESOURCE_EXHAUSTED — prepayment credits depleted` — the same pre-existing Google AI Studio billing cap already blocking `/committee-review`'s Gemini reviewer all session (`ai.studio/spend`). Zero clips were actually judged; this is not a data point about the verifier's accuracy, just a billing block.

**What's real and reusable from this attempt, despite the block:** the split-calibration segment reproduction + TP/FP labeling (`/tmp/.../img7743_split_segments.py`, not yet moved into `scripts/`) and the resumable scoring script (`/tmp/.../run_gemini_verify.py` — skips already-scored clips, writes incrementally) are both correct and ready to run the moment billing is resolved. Neither is committed to the repo yet (both still in the session's scratch directory).

**Conclusion.** `PIC-10` remains open and blocked on the same operator-only billing issue noted earlier today — not something fixable from a coding session. The segment-count discrepancy against `PIC-43` is a new, small, unresolved loose end worth someone's attention independent of the Gemini question.

**Follow-up.**
1. Resolve the billing cap (`ai.studio/spend`, operator action), then re-run `run_gemini_verify.py` — it will resume from wherever it left off.
2. Reconcile the 0.286/0.788 (this entry, IoU≥0.5, 91 segments) vs. 0.440/0.755 (`PIC-43`, same nominal config) discrepancy before trusting either as *the* current shipped-config eval number.
3. Move `img7743_split_segments.py`'s split-calibration + TP/FP-labeling logic into `scripts/` if this pattern (label detector segments against hand labels for something other than precision/recall — e.g. training data for a classifier, see the same-day direction-setting discussion below) gets reused, which is likely.

---

## 2026-08-20 (end of session) — Direction-setting: moving past crossing-count arithmetic, options researched and scoped, none built yet

**Not a scored experiment — a record of a real planning conversation**, kept here per this project's own convention of recording decisions that change direction, so the next session doesn't re-derive it.

**The question.** Today's whole paddle-tracking arc (this file, follow-ups #1-#4) and the running `PIC-31`/`PIC-42` thread both point at the same ceiling: no single hand-picked signal (duration, crossing rate, geometric masks, player-proximity) cleanly separates a real rally from dead time or clutter. Prompted a broader question: is it time to move from hand-tuned arithmetic to an actual trained model, and if so, which kind.

**Real project history surfaced, not previously connected explicitly:** the current ball-crossing-only approach was not the original design. `ADR-028` (2026-07-30) originally made **player geometry** (direction-reversal rate of player velocity, via the homography) the *primary* rally detector, with ball presence as a secondary refinement. `ADR-047` (2026-08-13) reversed that — but its own text shows this was **retroactive reconciliation of code that had already drifted to ball-first for cost/performance reasons**, not an upfront decision to keep things simple. The player-geometry approach itself was never cleanly validated either way: the one real-footage read available (`ADR-039`, 2026-08-08) suggested it *couldn't* separate rallies from dead time, but that test was confounded by camera zoom, and the direction-reversal hypothesis's own planned ablation test was never run. Net: today's "just arithmetic" state is a real, current fact about the shipped pipeline, but not a settled, deliberate design philosophy the way it was initially characterized in conversation — worth not repeating that overclaim.

**Options researched (web search, not just reasoning from memory), ranked cheapest-to-try:**
1. **Finish scoring the existing Gemini video verifier** (`src/verify.py`, `PIC-10`) — see the entry above. Blocked on billing, not on anything technical.
2. **A small trained classifier** over already-computed per-segment features (duration, crossing count/rate, `mean_motion`/`n_at_kitchen` from `src/events.py`) — realistic at this project's actual data scale (~140 hand-labeled rallies across 4 videos). Not yet built.
3. **A full sequence model (BiLSTM/GRU)**, the shape of approach real badminton research uses for this exact problem (serve-start + rally-end via BiLSTM/CNN + gradient computation, 81% accuracy; hit detection via a GRU fusing court+pose+shuttlecock position, 96% accuracy — closest published precedent found). Requires **an estimated 1,500-3,000+ labeled rallies, ideally from many different venues/cameras**, vs. today's ~140 from 4 videos — roughly 40-100+ additional full sessions at this project's current per-video labeling yield. Not started.
4. **Modern sports action-spotting architectures** (T-DEED and similar, SoccerNet's current state of the art for "rare precise-timing events in long video under class imbalance") — the most powerful, most expensive option; real and current, not started.

**Checked whether option 3 could be fine-tuned from an existing pretrained model instead of trained from scratch, rather than assuming it needs to start from zero.** Found real candidates with actual downloadable weights, not just papers:
- `arthur900530/Automated-Hit-frame-Detection-for-Badminton-Match-Analysis` — pretrained court/pose/hit-detection weights, the exact paper behind the 81%/96% figures above. **Code: MIT.**
- `qaz812345/TrackNetV3` — pretrained shuttlecock-tracking weights, a newer generation than the badminton-derived TrackNet weights this project currently runs. **Code: MIT.**
- `arturxe2/T-DEED` — the soccer action-spotting architecture. **Code: GPL-3.0**, and trained on SoccerNet, whose own dataset carries separate research-use terms — the highest-friction option of the three for eventual commercial use.

**Real gap found in all three: the repos' licenses cover the code, not confirmed to cover the pretrained weights.** Checked each README directly — none disclose usage terms for the weights themselves or the exact dataset they were trained on beyond a name. MIT-licensed code does not, by itself, guarantee the weights are clear to ship in a commercial product; that needs either asking the authors directly, training far enough past the starting weights that the derivative isn't meaningfully "their" model anymore, or accepting a cleaner but less pickleball-specific general-purpose pretrained backbone instead. Not resolved — flagged as the real blocker before committing to this path for anything beyond internal prototyping.

**Also surfaced: the planned 40-100 video data-collection commitment (for option 3, from scratch or fine-tuned) has a real prerequisite that's already sitting open.** This project already found, this session, that its own labeling process had an inconsistency problem (the operator was unconsciously quality-gating which exchanges counted as a rally, contrary to `LABELING.md`'s written binary policy) — recognized and corrected in principle, but the clean re-confirmation test (`PIC-44`, both passes under the now-settled standard, on never-before-labeled footage) hasn't been run. Labeling 40-100 more videos before confirming that fix actually holds risks baking the same inconsistency into a much larger dataset.

**Conclusion.** No new model was built this session. What exists now: a clear-eyed, sourced picture of what's actually achievable at this project's current data scale (option 2, realistic near-term), what a genuinely bigger step would cost in labeled data (option 3, ~1,500-3,000+ rallies, 40-100+ sessions), real fine-tuning candidates for that bigger step with an unresolved licensing gap, and an identified prerequisite (`PIC-44`) that should be cleared cheaply before committing to a large labeling effort.

**Follow-up, in the order they'd actually need to happen:**
1. Run `PIC-44`'s cheap re-test first (one more stretch, labeled twice, under the now-settled binary standard) — the whole large-scale-labeling plan depends on this holding.
2. Resolve the pretrained-weight licensing gap (contact the badminton repo authors, most direct path) before treating fine-tuning as a cleared option, independent of whether it turns out to help.
3. If pursuing the near-term option (2), build the summary-feature classifier described above — it's buildable today, no new data collection required, and provides a real baseline to compare any bigger investment against before committing to it.
4. None of this is committed to Linear as a new tracked issue yet — this entry is the record until that happens.

---

## 2026-08-21 — PIC-47: TrackNetV3 (`qaz812345/TrackNetV3`) first real benchmark, on `brickwall_30fps`

**Hypothesis.** TrackNetV3 is a newer-generation pretrained shuttlecock/ball tracker than the badminton-derived TrackNet weights (k14) this project currently ships. Worth benchmarking as a possible detector replacement, contingent on resolving its weight-licensing gap (2026-08-20 entry above) before shipping — this run is purely a detection-quality data point, not a decision to switch.

**Setup.** `brickwall_30fps` (`dev`), `--eval_mode nonoverlap`, full 25.2-minute video (~15.5 min inference). Scored through the identical shipped pipeline — `court_wedge → track_ball → crossing_times → cluster_crossings → match_intervals`, same `gap_sec=3.0`/`min_crossings=6`, same labels, IoU≥0.5 — as the existing k14 baseline, so the comparison isolates the detector swap.

**Result.**

| Detector | Precision | Recall |
|---|---|---|
| k14 (shipped, fixed `gap_sec`) | 0.64 | 0.80 |
| k14 (adaptive `gap_sec`, PIC-33) | 0.76 | 0.91 |
| **TrackNetV3** | **0.694** | **0.971** |

TrackNetV3 beats the shipped config on both metrics, and beats even the adaptive-gap k14 config on recall (missed only 1 of 35 real rallies) — but trails adaptive-gap k14 on precision.

**Conclusion.** A genuinely promising first data point, not a decision — this is one video, the cleanest one in the project, picked for exactly that reason. It is also a *detector* result, not a downstream one: it cannot touch `PIC-31`'s dominant remaining failure mode (the ball genuinely, correctly crossing the net during dead time), since that's downstream pipeline logic no detector improvement can fix in principle.

**Follow-up.**
1. Run the same benchmark on `pb_draft_cup` and `IMG_7744` before this means anything conclusively — one video is not enough to call it a general win.
2. Before shipping (not before further benchmarking): resolve the weight-license gap flagged in the 2026-08-20 entry above — the checkpoints are pretrained on badminton data, code is MIT, but the weights' own redistribution/usage terms are undisclosed.
3. Filed as Linear PIC-47, with this result as a comment.

---

## 2026-08-21 (later) — Kitchen dinks double-count net crossings: a structural defect of the crossing-count signal itself, not a detector artifact

**What prompted this.** Building a 2-clip highlight reel from the TrackNetV3 brickwall segments (ranked by raw crossing count, the only proxy score `src/cut.py` has), the operator flagged the mechanism directly: near the kitchen, a single return can cross `net_y` twice — once going up and over the net, once again as it drops into the kitchen — before the opponent's return. `crossing_times` (`src/ball.py`) is a 1D signal (image-y vs. one pixel row), blind to court depth, so it has no way to tell "two shots" from "one shot's rise-then-fall through the same row."

**Checked against real tracked-ball data**, not asserted. Pulled `crossing_times` for the two rallies in the reel (TrackNetV3 predictions, same court gate/tracker as shipped) and bucketed the gaps between consecutive crossings:

| gap | count | % |
|---|---|---|
| 0.00–0.15s | 26 | 13% |
| 0.15–0.30s | 34 | 18% |
| 0.30–0.50s | 48 | 25% |
| 0.50–1.00s | 69 | 36% |
| 1.00s+ | 16 | 8% |

193 gaps total, rally 1 (92 "crossings," 41.5s) and rally 2 (106 "crossings," 59.0s). 13% of gaps are under 150ms — not achievable as two independently hit shots — and another 18% sit in a band a fast dink exchange could plausibly explain but a same-shot double-crossing explains just as well. This is exactly the kitchen mechanism described, confirmed on real data rather than assumed from the theory alone.

**This is a property of the crossing-count primitive, not of TrackNetV3 or k14 specifically** — any detector feeding the same `crossing_times`/`cluster_crossings` pipeline inherits it, since it depends only on how the 1D image-y-vs-net_y signal is defined, not on detection quality. **Not a reason to distrust crossing bursts as an activity signal** — a dense burst of crossings still reliably means "something real is happening at the net" — but the raw *count* is not a reliable proxy for shot count, rally intensity, or duration, because the inflation scales with how much kitchen play happened, which varies rally to rally. This is likely why both reel clips (this session) landed on extended dink exchanges rather than a spread of different rally types: ranking by raw crossing count structurally favors kitchen-heavy rallies.

**Considered and rejected a fixed-time debounce (merge crossings within some short window into one) as a fix, per the operator: a real fast exchange with a bounce off the floor before the return can legitimately produce genuine crossings faster than any safe debounce window would allow** — a fixed-gap merge would just trade one systematic miscount for another (now undercounting genuinely fast real exchanges). No time-gap-only fix is safe here; distinguishing the two needs something that looks at trajectory shape (e.g. whether the ball's arc actually goes back over net height, vs. stays low the second time), not just inter-crossing timing.

**Conclusion.** A confirmed, data-backed third failure mode for the crossing-count signal, distinct from `PIC-34`'s phantom crossings (no real rally, ball never crosses) and `PIC-31`'s dead-time crossings (real crossing, wrong context) — this one happens *during* genuine, correctly-detected rally play and just inflates the count. Affects anything treating crossing count as a literal shot-count/intensity proxy: `PIC-46`'s classifier `crossing_rate` feature, `PIC-14`'s stalled ranking-signal question (shot count was supposed to be a ranking input and was never available — this explains why crossing count isn't a clean substitute either), and any future crossing-count-based ranking, including the ad hoc one used for this session's reel.

**Follow-up.**
1. Filed as Linear `PIC-48` — cross-referenced from `PIC-42` (signals beyond ball-crossing), `PIC-46` (classifier features), `PIC-14` (ranking signals).
2. No fix attempted or recommended yet. A trajectory-shape check (real net-height re-crossing vs. a low second dip) is the plausible direction, not a timing threshold — untested.
3. Single-video, two-rally sample (both brickwall, both TrackNetV3). Worth checking whether the same gap-clustering shows up on a non-kitchen-heavy rally, and on k14 predictions for the same clips, before treating the magnitude (not just the mechanism) as general.

---

## 2026-08-22 — Pose-detection sanity check: off-the-shelf YOLO-pose on real footage, before investing in anything trained

**Hypothesis.** Revisiting player-geometry as a rally-boundary signal (superseded direction, `ADR-028`/`ADR-047`, reopened in the 2026-08-20 direction-setting entry above) — specifically whether *pose* (vs. plain bounding-box motion) could separate ready-stance/active-play from relaxed/dead-time posture, addressing the two confounders `STRATEGY.md` §3 names as unsolved (dinks: players barely move but assume a distinct stance; courtesy returns: post-point body language differs from active play). Before investing in anything trained, check the cheap thing first: can an off-the-shelf pose estimator even get usable keypoints at this camera's distance and angle. `STRATEGY.md` §10 (open question 7) already flags far-court pose reliability as an unresolved prototype risk.

**Setup.** `ultralytics` (already installed in `.venv`, no new dependency) — `yolov8n-pose` and `yolov8x-pose`, both pretrained COCO checkpoints, zero-shot, no fine-tuning. Four frames pulled from `brickwall_30fps.mp4` (`dev`, the cleanest footage in the project) via `eval/labels/brickwall_30fps.jsonl` timestamps: two mid-rally (t=15s, t=85s, different rallies), one at a rally's kitchen-line moment (t=20s), and one deliberately picked at a rally *boundary* (t=36s, ~1.5s after rally 1's labeled end) rather than an arbitrary dead-time timestamp, specifically to land on the actually-confounding case (players still on/near the court, not walked off) rather than a trivially-easy one.

**Result.**

| Frame | People detected | Near-player pose quality |
|---|---|---|
| Mid-rally (t=15s, t=85s) | 2 of 4 (near team only) | 12–14/17 keypoints, conf 0.69–0.79 |
| Kitchen-line rally (t=20s) | 2 of 4 (near team only) | 13/17 keypoints, conf ~0.74–0.75 |
| Post-point (t=36s) | 2 of 4 (near team only) | **17/17 and 16/17 keypoints, conf 0.92–0.95** — full clean skeletons |

The t=36s frame landed, unplanned, on a genuinely sharp test case: both near players walking toward each other for a post-point fist-bump, arms flung wide, standing tall — visually and geometrically nothing like the symmetric crouched paddle-up stance in the mid-rally frames. A stance-angle/arm-position feature over these keypoints would very plausibly separate the two classes; this isn't a subtle distinction requiring a trained model to notice.

**The far-court team was never detected, at either model size.** Re-ran the t=15s frame through `yolov8x-pose` (largest variant) with the confidence threshold lowered to 0.15 specifically to surface marginal detections — still only 2 of 4 people found. Cropped and visually inspected the far players directly: they are not badly occluded or too small to make out by eye, which argues this is a net-proximity/occlusion artifact specific to the behind-baseline doubles framing (the net and its signage board partially cut the far team's lower body), not the general "too far, too small" resolution ceiling `STRATEGY.md`'s open question assumed. A model-capacity increase (nano → largest variant) did not fix it, which is itself informative — this needs either a fine-tuned/net-aware detector or a different camera angle for the far team specifically, not just a bigger off-the-shelf model.

**Conclusion.** Pose is a real, cheap, promising signal for the near-court player(s) specifically — reliable keypoints, no fine-tuning, and a visually obvious ready-stance-vs-relaxed contrast at exactly the boundary this project needs to detect. The far-team detection gap is real but matters less for rally-boundary detection than it first appears: both partners on a team transition ready-stance/relaxed together, so even one reliably-detected player's stance is plausibly sufficient for a boundary signal, even though it would matter more for a future all-4-players use case (movement analytics, `STRATEGY.md` §7).

**Follow-up.**
1. Compute an actual stance-angle/geometric feature (e.g. wrist-shoulder angle, knee bend, stance width) across a longer stretch of frames spanning several real rally boundaries, and check whether it tracks the labeled start/end times — this entry only established that keypoints are detectable and visually different, not that a derived feature actually separates the classes at scale.
2. If that holds, investigate the far-team occlusion mechanism properly (net-line geometry vs. camera angle) before ruling out a full-4-player signal.
3. Single-video, four-frame, zero-shot sanity check — not a scored result. No conclusion here should be treated as validated until the above is run.

---

## 2026-08-22 (later) — Near-team pre-serve stillness: a real, sharp, corroborable signal for rally *start* — plus an untested fusion idea for PIC-31

**What prompted this.** Direct follow-up to the pose sanity check above. The operator proposed a specific hypothesis before any measurement was taken: **all 4 players going static (planted, ready) is a signal for rally start** — a sharper, more specific idea than the general "pose looks different during rallies" direction the sanity check above was testing. Scoped down to what's actually measurable today: the far-court team isn't reliably detected by any pose model size (see sanity check above), so this entry tests the **near-team-only proxy** — do the two reliably-tracked players go still right before a serve, even without observing the far team directly.

**Setup.** `yolov8n-pose` run via `ultralytics`' built-in `model.track(..., tracker="bytetrack.yaml")` (not raw per-frame detection — needed actual frame-to-frame identity to compute motion, not just presence) over `brickwall_30fps.mp4`, first 135s, `vid_stride=2` (15fps effective). Per sampled frame, computed each active track's ankle-midpoint position; frame-to-frame Euclidean displacement ("speed") averaged across whichever near-team tracks were active that frame. Track IDs churned every ~30–40s (ByteTrack losing/reacquiring lock, likely during crouches/brief occlusion) — not a problem here since only short-range frame-to-frame continuity was needed, not identity across the whole clip.

**First pass was measured wrong, caught before trusting it.** Initial comparison was "speed in the 1.5s before each labeled rally start" vs. "mean speed during that same rally's middle." Numbers came back inconsistent (rally 2/3 showed the expected dip, rally 1/4 didn't) — looked like a failed hypothesis until the actual time-series plot was inspected. The plot showed why the comparison was wrong: mid-rally speed is *not* uniformly high — during a kitchen-dink exchange, feet stay planted (only arms move), so ankle-speed drops low *during* real play too, for reasons unrelated to the pre-serve moment. "Mid-rally" was the wrong baseline.

**Corrected comparison: immediate pre-serve (last 1s) vs. the general dead-time noise floor right before it (the preceding 4.5s, not mid-rally).**

| Rally | Immediate pre-serve speed (1s) | Preceding dead-time baseline (4.5s) | Ratio |
|---|---|---|---|
| 2 | 0.85 | 10.14 | **0.08** |
| 3 | 1.90 | 11.30 | **0.17** |
| 4 | 0.75 | 10.08 | **0.07** |
| 1 | 5.91 | n/a (video starts at t=0, no prior dead time to baseline against) | — |

For all 3 checkable boundaries, near-team ankle speed drops to **7–17% of the surrounding dead-time activity level** in the final second before serve — a sharp, consistent, visually unmistakable dip in the plotted time series, not a subtle statistical trend.

**Two things the same plot surfaced that the operator's original framing didn't anticipate:**
1. **Dead time is not generally quiet — it's the noisiest part of the signal** (players walking, resetting, ~10 px/frame-step baseline). The pre-serve dip is distinctive precisely because everything around it is loud, not because dead time in general is calm.
2. **Rally *end* shows the opposite pattern**: a sharp motion *spike* right after the labeled end time (post-point ball retrieval, resetting, celebration — the fist-bump frame found in the earlier sanity check entry sits inside the first of these spikes). A second, independently-usable, opposite-polarity signal for the other boundary.

**Conclusion.** The operator's stillness hypothesis holds on the near-team proxy — cleanly and by a wide margin, not marginally. This is meaningfully different from what the earlier player-geometry-era architecture already knew: `DECISIONS.md` ADR-037 ("Two-sided live/stopped evidence; no marker decides alone") already identified that a *dink's* mid-rally stillness is a hard case needing ball-crossing corroboration to correctly read as "live." That's a different physical moment (mid-rally) from what's measured here (pre-serve, before any point activity) — this entry's finding is new, not a rediscovery of ADR-037's case, though it's the same *shape* of idea (pair a motion signal with a ball signal to resolve an ambiguous case).

**Fusion idea raised by the operator, not yet tested: stillness-dip as a rally-start trigger, corroborated by a following net-crossing burst, as a combined "real rally start" detector.** The direct motivation is `PIC-31` — the project's current highest-priority open problem, where crossing-count-alone cannot separate a real rally from a courtesy tap-back/warm-up exchange, because both produce crossing bursts. Every candidate tried against `PIC-31` so far (duration/rate thresholds, geometric masks, player-proximity) failed for the same underlying reason: all of them are still derived from the crossing signal itself. Pre-serve stillness is a genuinely independent signal (player motion, not ball trajectory) — in principle, *stillness-dip → arm a candidate → require a crossing burst within some window after → confirm* could filter out exactly the false positives a crossing-only detector can't, because a real serve requires a formal both-teams-ready pause that a spontaneous courtesy tap generally doesn't have.

**This fusion idea is not yet tested against real false positives — that's the actual next step, not a conclusion.** `PIC-37`'s FP anatomy work already found that 48% of `IMG_7743`/`IMG_7744`'s remaining false positives are confirmed real dead-time crossings (courtesy returns), not phantom ones — those specific, already-known false-positive timestamps are the direct test: do they lack the pre-serve stillness dip this idea predicts they should lack? That would be real evidence the fusion fixes the actual problem, not just a plausible story.

**Follow-up, in the order they'd need to happen.**
1. Not yet run: check the near-team stillness signal at `PIC-31`/`PIC-37`'s known dead-time-crossing false-positive timestamps on `IMG_7743`/`IMG_7744` — do they lack the pre-serve dip, as the fusion hypothesis predicts?
2. Not yet run: confirm the pre-serve dip generalizes past brickwall's 3 boundaries — different rally-length/format regime (singles `pb_draft_cup`, casual doubles `IMG_7743`/`IMG_7744`), and more boundaries within brickwall itself.
3. If both hold, design the actual combined detector (window length between dip and required crossing burst is unpicked; needs a real dev-only sweep, same discipline as `PIC-43`'s parameter work — not eyeballed).
4. Small sample throughout this entry: 3 checkable boundaries, one video, one detector (near-team pose only). Treat the ratio magnitude (0.07–0.17) as a promising first read, not a validated threshold.
5. Not committed to Linear yet — recommend filing under `PIC-31` (it's the problem this is aimed at) or as a new linked issue, whichever the operator prefers next session.

---

## 2026-08-22 (later still) — Near-team court depth at serve splits baseline vs. kitchen line; post-serve transition timing gives a second, corroborating signal for who's serving

**What prompted this.** Direct follow-up to the pre-serve stillness entry above. The operator proposed a second, more specific hypothesis before measurement: **at rally start, the offense (serving) team stands close to the baseline, still; the defense (receiving) team has either both players at baseline or one at the kitchen line** — a positional refinement of the stillness signal, aimed at the same `PIC-31` problem (separating real rallies from courtesy exchanges) but using *where* players stand, not just whether they're moving.

**Setup.** Reused the same near-team ankle tracks from the stillness entry above (`yolov8n-pose` + ByteTrack, `brickwall_30fps.mp4`, first 135s) — no new inference run. Converted ankle pixel positions to real court feet via the video's actual calibration (`calib/brickwall_30fps_calib.json`'s homography: near baseline at y=0ft, near kitchen/NVZ line at y=15ft, net at y=22ft). Checked in three passes of increasing window width, each testing what the previous one couldn't answer.

**Pass 1 — tight window (last 0.7s before each labeled rally start).** Averaged each active track's court depth in this window, for all 4 checkable rally starts (rallies 1–4, the only ones inside the first 135s).

| Rally | Court depth | Court width | Zone |
|---|---|---|---|
| 1 | −1.8 ft | 7.6 ft | baseline |
| 2 | 14.8 ft | 4.8 ft | kitchen line |
| 3 | 14.6 ft | 15.8 ft | kitchen line |
| 4 | −1.8 ft | 6.7 ft | baseline |

A clean binary split, not a gradient — exactly the two positions the hypothesis named. Rally 1 was independently confirmed from the raw frame at t=1.8s: two near-team players at the baseline, one with the ball raised, clearly about to serve. Only one near-team track was found per rally in this tight window, not two — the immediate open question.

**Pass 2 — widened window (6s before serve).** Re-ran the same query over a much wider pre-serve window to check whether the "missing" second player was a tight-window artifact. It wasn't a second player that appeared — the *same single track* turned out to be in transit: in rallies 2 and 3, the one near-team player found was walking the full length from the baseline to the kitchen line over the ~4–5s before serve, arriving right as the point started. In rallies 1 and 4, near-team players were already static at the baseline for the whole window (rally 4 showed two separate tracks, both converging to two different baseline spots — left and right service positions — matching rally 1's confirmed pattern). Cropped and visually inspected the entire near-baseline area at rally 2's exact start: empty, corroborating the tracking result rather than contradicting it.

This directly tested the operator's specific read (that in rallies 2/3 the opposing/far team was serving, so the near-side player *not* at the kitchen line should be a returner planted at the baseline) — and didn't confirm it: no baseline presence, near or far, was found anywhere in the 6s before either rally 2 or 3 started. Three explanations were left open, undistinguished by this data: the labeled "start" timestamp lands after the actual serve (returner already moved before the window begins), the returner is outside this camera's frame entirely (the same camera already can't see the far team at all, per the pose sanity check above), or the near team was serving in rallies 2/3 too and the tracked player is the server's own partner already up at net.

**Pass 3 — post-serve window (13s after serve).** Extended tracking *forward* from each rally's start instead of backward, to see whether a second near-team player would show up running toward the net once the point was live, and whether the timing of that appearance said anything about server identity.

| Rally | Reading | 2nd/other player first seen | Reaches kitchen line | Baseline hold, post-serve |
|---|---|---|---|---|
| 1 | near team serving (confirmed) | t = −2.5s (pre-serve) | +9.7s | ~6.9s |
| 2 | near team receiving (inferred) | t = +1.9s | +3.8s | ~0s (already moving) |
| 3 | near team receiving (inferred) | t = +2.5s | +4.4s | ~0s (already moving) |
| 4 | near team serving (matches R1 pattern) | t = −5.6s (pre-serve) | +5.3 to +6.1s | ~3.4–5.2s |

In rallies 1 and 4, both near-team players are in place before serve and hold the baseline for 3.4–6.9s *after* the point starts before advancing — consistent with a team that just served and has no reason to rush. In rallies 2 and 3, the second near-team player is never seen before the point starts at all; they first appear already near the baseline 1.9–2.5s after serve and reach the kitchen line in under 2s — consistent with a returner who just hit their return and is racing to close the net, the standard aggressive move for a receiving team.

**Conclusion.** Two real, distinct, independently-measured signals came out of this, beyond the original position hypothesis: (1) player court depth at serve is a genuine binary baseline-vs-kitchen-line split, matching real pickleball positioning, not a fuzzy trend; (2) the *tempo* of the post-serve transition to net — hold-then-advance vs. late-arrival-then-sprint — is a second, independent signal that corroborates the operator's serve-direction read for rallies 2/3 without fully proving it. Neither signal identifies a server with certainty on its own; only rally 1 was confirmed by an actual serve-motion frame. Both signals are candidate inputs for the `PIC-31` fusion idea (stillness-dip → armed candidate → crossing-burst confirmation) from the entry above, alongside or instead of the pure stillness ratio.

**Follow-up.**
1. Not yet run: confirm server identity for rallies 2–4 via real playback around the serve moment (motion, not stills) — the project's own established standard for rally/dead-time calls applies equally to a role question like this one.
2. Not yet run: check whether the post-serve transition-timing asymmetry (baseline-hold duration, time-to-kitchen) generalizes past these 4 rally starts and past `brickwall_30fps`.
3. If it holds, fold court-depth-at-serve and transition tempo into the `PIC-31` fusion idea's feature set alongside pre-serve stillness, rather than treating them as a separate signal.
4. Small sample throughout (4 rally starts, one video, near-team pose only, far team never observed). Treat the baseline/kitchen-line split and the timing asymmetry as promising first reads, not validated thresholds.
5. Not committed to Linear yet — same recommendation as the stillness entry: file under `PIC-31`, or as a new issue linked from it, whichever the operator prefers.
6. No new analysis code was written into the repo for any of the three passes above (or for the stillness entry before it) — everything ran from an interactive session against ad hoc scripts in a scratch directory outside the repo, flagged in this session's committee review as a reproducibility gap. Before this direction gets picked up again, the position/timing analysis should be turned into a real `scripts/` entry, not re-derived from scratch.

---

## 2026-08-23 — Pre-serve stillness signal does NOT generalize to IMG_7743: fails the direct PIC-37 test it was proposed to pass

**What this tests.** The 2026-08-22 stillness entry's own next step, run for the first time: check the near-team pre-serve stillness ratio (immediate 1s speed / preceding 4.5s dead-time-baseline speed) at `PIC-37`'s already-known, high-confidence false-positive timestamps — `IMG_7743` post-bump's 12 remaining false positives, all independently confirmed by trajectory-plot read as real dead-time crossings (courtesy returns / between-point practice), none ambiguous. The fusion idea predicted these should *lack* the sharp dip real serves showed on `brickwall_30fps.mp4` (ratio 0.07–0.19, all three checkable boundaries).

**New reusable code.** `scripts/pose_stillness.py` — same method as the 2026-08-22 scratch analysis (`yolov8n-pose` + `model.track(tracker="bytetrack.yaml")`, `vid_stride=2`, ankle-midpoint frame-to-frame displacement in raw pixels, no homography projection), but as a real script instead of interactive scratch code, closing the reproducibility gap the committee review flagged. Re-ran brickwall's 3 known boundaries first as a reimplementation sanity check before trusting it on new data: 0.10 / 0.19 / 0.15 vs. the originally reported 0.08 / 0.17 / 0.07 — same sharp-dip pattern, close enough (different tracker-state history: this run's tracker initializes fresh per window instead of running continuously from t=0) to trust the script measures the same thing.

**IMG_7743 post-bump false positives (n=12, boundary = FP segment start, taken as the candidate "serve" moment):**

| FP start (s) | ratio |
|---|---|
| 11.60 | 1.36 |
| 107.73 | 2.88 |
| 141.10 | 0.58 |
| 199.40 | **0.03** |
| 534.83 | 1.34 |
| 561.33 | 0.80 |
| 587.73 | 1.05 |
| 682.17 | 0.55 |
| 797.10 | 0.67 |
| 885.03 | 0.56 |
| 952.90 | 0.51 |
| 1034.13 | n/a (no pose detected in the pre-window) |

n=11 valid. Mean 0.94, median 0.67 — mostly nowhere near brickwall's <0.2 real-serve range. Only one (199.40s, ratio 0.03) shows a dip as sharp as a real brickwall serve.

**Control: IMG_7743 post-bump's own real rally starts (n=6, first 6 labels), same script, same window:**

| Rally start (s) | ratio |
|---|---|
| 49.75 | 1.36 |
| 88.09 | 1.83 |
| 215.33 | 0.61 |
| 259.53 | 1.47 |
| 340.52 | 2.03 |
| 694.06 | 0.88 |

Mean 1.36, median 1.42 — no dip either. Inspecting the raw per-frame speed series at rally-start 49.75s (the first control point) directly: speed is *rising* through the second before serve (20–35 px/frame-step, vs. brickwall's near-zero), the opposite of the brickwall pattern, not just a weaker version of it.

**Conclusion: this falsifies the fusion idea as originally scoped, not just "needs more data."** Two things distinguish this from an inconclusive result: (1) IMG_7743's real rally starts (mean 1.36) don't show the dip at all — brickwall's <0.2 threshold applied here would reject **6 of 6** real rallies as "not a real serve," a 100% false-negative rate before precision is even measured; (2) IMG_7743's dead-time false positives (mean 0.94, median 0.67) sit in the same range as, if anything slightly *below*, IMG_7743's own real rallies — on this video there is no separation between the two classes on this signal, small-sample caveats aside (n=11 and n=6). The brickwall dip is real (reimplementation confirms it) but appears to be a property of that specific footage/format — likely long-rally tournament doubles with a formal serve pause — not a general pickleball-serve behavior. IMG_7743's casual doubles rallies (per `PROGRESS.md`'s rally-length table, ~10s mean, much shorter than brickwall's ~22s) may simply not have the same ritual pause before serve, or the label `start` timestamp may land at a different point in the serve motion on this video's labels than on brickwall's — undistinguished by this data, would need real playback around 2–3 IMG_7743 serves to settle which.

**This closes out candidate #3's simplest form (raw near-team stillness ratio, brickwall-derived threshold) as a `PIC-31` fix.** It does not close `PIC-31` itself, and does not rule out a per-video-calibrated version of the same signal (the way `gap_sec` and the rate/duration threshold both needed self-calibration, not a fixed constant) — that has not been tried.

**Follow-up.**
1. Not yet run: real playback of 2–3 IMG_7743 serves to check whether the ritual pre-serve pause brickwall shows is genuinely absent on this footage, or whether the label `start` timestamp is landing after it.
2. Not yet run: the same check on `IMG_7744` (this video's dead-time-crossing false positives are less thoroughly anatomized than post-bump's, per the 2026-08-19 FP-anatomy entry — post-bump was chosen here specifically because all 12 were unambiguous).
3. A self-calibrated version (e.g. ratio relative to a per-video baseline distribution rather than a fixed brickwall-derived cutoff) is untested and is the next cheapest thing to try before abandoning the stillness signal entirely — same shape as the `adaptive_gap_sec` fix that rescued `gap_sec` from being a single-video constant.
4. The baseline/kitchen-line position signal and post-serve transition-timing signal (2026-08-22, later still) have not been tested against these same false positives yet — today's result is specific to the stillness-ratio signal, not the whole `PIC-31` fusion direction.
5. Recommend updating `PIC-31` in Linear with this result — the stillness signal is a promising-looking lead that did not survive its first real test, which is exactly the kind of finding that should stop it from being assumed in later work.

## 2026-08-23 (later) — Real playback spot-check of two "confirmed" PIC-37 false positives: both are actual plays, not dead time

**What this tests.** Follow-up item #1 above (playback of real IMG_7743 rally starts) led to also spot-checking the false-positive side while set up to watch: two of PIC-37's 12 "confirmed by trajectory-plot read, no ambiguity" `IMG_7743` post-bump dead-time false positives, rendered as clips in a review artifact and watched directly (`CLAUDE.md`'s video-review-method rule — trajectory-plot reads are not exempt from this; they're a still/aggregate proxy for motion, same failure class as a stills-based verdict).

**Result.** Both spot-checked FPs — **107.73s (stillness ratio 2.88)** and **199.40s (stillness ratio 0.03)** — are, per direct playback, real plays, not dead-time crossings. User's words: "both are actual plays, not deadtime, and they are great." 2 of 2 checked so far have flipped.

**Why this matters, beyond just two mislabeled points.**
1. **PIC-37's confirmation method itself is now suspect.** "All 12 confirmed by trajectory-plot read, no ambiguity" has failed its first real playback check, 2/2. That list should not be treated as ground truth until re-verified by playback, the same way stills-based verdicts were already retired for this reason (see the IMG_7744 false-positive review, referenced in `CLAUDE.md`).
2. **This contaminates ADR-055's negative-class sample.** ADR-055's "no separation" conclusion was computed over IMG_7743's 12 "confirmed" FPs (n=11 valid) as the dead-time/negative class. If some fraction of those are actually real plays, the negative class isn't clean — real plays that leak into what's treated as "dead time" will naturally look statistically like real plays, muddying any separation measurement regardless of whether the underlying signal works.
3. **The specific pattern is not neutral.** 199.40s was the *one* "FP" with a sharp real-serve-like dip (ratio 0.03, the only one under brickwall's 0.2 cutoff) — and it turns out to be a real play, exactly what the fusion hypothesis would have predicted for a real serve. 107.73s (ratio 2.88, no dip) is also a real play, consistent with the already-established pattern that IMG_7743's real rallies mostly don't show the dip. Both reclassifications point the same direction: toward the stillness signal working better than ADR-055 concluded, not worse — but n=2 is not enough to revise ADR-055 on its own.

**Not yet done — this is a lead, not a re-verified conclusion.** The other 10 of PIC-37's 12 "confirmed" FPs haven't been playback-checked. Until they are, neither PIC-37's FP-anatomy numbers (`EXPERIMENTS.md`, 2026-08-19 later) nor ADR-055 should be treated as resting on clean ground truth. See `DECISIONS.md` ADR-056.

## 2026-08-23 (final) — All 12 of PIC-37's "confirmed" IMG_7743 post-bump false positives are real plays. Zero are dead time.

**What this tests.** The remaining 10 of PIC-37's 12 post-bump "confirmed by trajectory-plot read" false positives, rendered as a second review artifact (verdict buttons per clip: real play / dead time / unsure) and watched directly, following up the 2-of-2 flip above.

**Result, in the user's words: "all of them have actual actions in them, just a variety of different duration of start time and end time. none of them are dead time."** Combined with the earlier 2-of-2 check, that's **12 of 12** of PIC-37's post-bump false positives confirmed by real playback to be real plays. Zero confirmed dead time. PIC-37's headline claim for this segment — "post-bump in particular is entirely real dead-time crossings (12/12) — nothing there is a detector flaw at all" — is **fully inverted**: the detector was right all 12 times; the *labels* were incomplete.

**What actually happened, most likely.** These 12 net crossings are real rallies that were never captured by the original hand-labelling pass on `IMG_7743_postbump_2900s-end.mp4`. This is the project's already-named failure mode #2 (`PROGRESS.md`'s three-failure-modes table: "label incompleteness — real play that was never marked scores as a false positive") — just never before confirmed at this scale (12 consecutive misses on one video-half, on top of the 6 rallies that *were* labelled there) or traced back to a specific mechanism (a `fp_anatomy.py` trajectory-plot read that looked confident and was wrong).

**Consequences, worked through:**
1. **IMG_7743 post-bump's true precision is higher than every number computed against its current labels.** All prior precision figures for this video-half (PIC-37's own anatomy, ADR-053's provisional replacement numbers, PIC-33/PIC-43's `dev`-only work doesn't touch `eval` so is unaffected, but any `eval`-scored precision number for IMG_7743 specifically undercounts real detections as false positives.
2. **PIC-31's candidate-#1 rejection (duration/rate threshold, `EXPERIMENTS.md` 2026-08-19 "yet later") partially rests on the same false premise.** Its "sanity check first" table explicitly built the `dead-time junk (n=12)` row from "IMG_7743 post-bump, where all 12 remaining false positives are confirmed real dead-time crossings — no ambiguity." That row is retracted. The broader "unsupervised check across all 4 videos" that actually drove the rejection conclusion scored against the full label set rather than this specific list, so the rejection's headline conclusion is likely still standing on its own legs — but the sanity check that motivated and framed it is not.
3. **ADR-055 and ADR-056 (today, earlier) are further downgraded**, not just "provisional" now — there was **no valid dead-time example anywhere in the sample ADR-055 tested against.** The "no separation between real rallies and FPs" finding was, in hindsight, "no separation between real rallies and *other* real rallies," which is not evidence against the stillness signal at all — it's simply not a valid test of it. `PIC-31` has never yet been tested against a confirmed genuine dead-time example on `IMG_7743`.
4. **Pre-bump's matching numbers are now suspect too.** PIC-37's pre-bump table (14 "real dead-time crossing," 10 "noise/hallucinated," by the same trajectory-plot method) has had zero playback checks. Given the method just failed 12/12 on post-bump, none of the pre-bump classification should be trusted either without the same treatment.

**Recommendation.** This is a labeling-completeness bug on `IMG_7743_postbump_2900s-end.jsonl`, not a detection or `PIC-31` finding — the fix is a proper exhaustive re-label of that segment (`LABELING.md`'s two-layer presence pass), adding the 12 missing rallies with real start/end times, not a code or threshold change. Once relabelled, IMG_7743 post-bump would have a genuine set of dead-time-vs-real examples to test `PIC-31` candidates against for the first time. See `DECISIONS.md` ADR-057.

## 2026-08-23 (postscript) — IMG_7743 postbump exhaustively re-labeled and re-scored: precision is essentially perfect, recall is the real story, and it's a `min_crossings` ceiling, not dead time

**What happened.** Full two-layer presence pass over `IMG_7743_postbump_2900s-end.mp4` (`LABELING.md`), using `label_web.py` over Tailscale. Label count went from **6 to 53** — not just the 12 known FP timestamps, confirming ADR-057's prediction that the false-positive list alone couldn't surface rallies the detector missed entirely. `quality` graded during the same pass: 5 of 53 are `quality:1` (highlight-worthy), 48 are `quality:2` (ordinary).

**Re-scored against the shipped default (`gap_sec=3.0`, `min_crossings=6`, `court_wedge`, `track_ball`), same raw predictions (`cache/IMG_7743_predictions_k14.csv`, offset −2900s), IoU≥0.5:**

| | value |
|---|---|
| labels | 53 |
| predicted segments | 22 |
| matched | 18 |
| missed | 35 |
| false positives | 4 |
| **precision** | **0.818** |
| **recall** | **0.340** |

**The story has flipped: precision is essentially perfect, not 0.82.** All 4 remaining "false positives" were checked against their nearest real label — every one is a near-miss boundary overlap (IoU 0.31–0.47, just under the 0.5 cutoff) with a real, now-labelled rally, not a hallucinated detection. There is **zero genuine junk** left in this segment. This closes the loop `PIC-37`/ADR-057 opened: the whole "false positive" story on IMG_7743 post-bump, from the original 13 down to these last 4, was never a detection-quality problem — it was labels not existing yet to match against.

**The real, newly-visible problem is recall, and it traces cleanly to `min_crossings=6`.** Of the 35 missed labels, 30 have fewer than 6 raw net crossings inside their window — mechanically below the shipped clustering threshold, so `cluster_crossings` never emits a segment for them at all (they were invisible to *every* prior false-positive analysis on this video, including PIC-37's, for the same reason: a rally with no detected segment can't appear on a false-positive list).

**Diagnostic only — `IMG_7743` is `eval`/locked per ADR-052, this is not a parameter pick:**

| `min_crossings` | n predicted | precision | recall |
|---|---|---|---|
| 6 (shipped) | 22 | 0.818 | 0.340 |
| 4 | 49 | 0.490 | 0.453 |
| 3 | 61 | 0.393 | 0.453 |
| 2 | 90 | 0.267 | 0.453 |

Recall plateaus at **0.453 no matter how low `min_crossings` goes** — it does not climb toward 1.0. This means the ceiling isn't purely a badly-tuned constant; a real chunk of these short rallies (failed serves, 1–2-shot points — see the earlier "what counts as a rally" discussion this session) physically produce only 1–2 net crossings, below what *any* crossing-count clustering could ever assemble into a segment. Precision collapses as the threshold drops (0.818 → 0.267) because low crossing counts also admit real background/noise clusters — so this isn't "just lower the constant" either; there's a genuine tradeoff, and part of the gap may need a different mechanism entirely (e.g. detecting a serve event directly, not inferring one from crossing count).

**Practical impact on the current phase is smaller than the raw recall number suggests.** Of the 5 `quality:1` (highlight-worthy) rallies, **4 were matched — only 1 missed** (894.15–906.01s, itself an outlier at only 3 raw crossings for an 11.9s rally). 34 of the 35 total misses are `quality:2` (ordinary, short exchanges). For the project's current phase-1 deliverable (a highlight reel), this gap matters much less than the raw 0.340 recall implies. It would matter more for the longer-term analytics-goal vision (`[[project_vision]]`, counting all real play, not just highlights) — worth keeping both readings in view rather than picking one.

**Open questions this raises, not yet answered.**
1. `min_crossings=6` was originally picked on IMG_7743 itself (ADR-048, 2026-08-16) and re-derived on `dev` only (`PIC-43`, 2026-08-19, landed on the same value). If `dev`'s videos (brickwall, pb_draft_cup, IMG_7744) have the same kind of labeling-completeness gap IMG_7743 just turned out to have, PIC-43's re-derivation would have the same blind spot ADR-048's original pick had — untested.
2. Whether a genuinely different, non-crossing-count mechanism (serve detection, not crossing accumulation) is needed to close the recall ceiling that persists even at `min_crossings=2`, or whether this is an acceptable, even correct, tradeoff given the highlight-reel framing above.
3. Recommend filing both as new Linear issues rather than folding into `PIC-31` (which was about dead-time false positives — now shown to be close to a non-issue on this video) or `PIC-49` (relabeling, now done). See `DECISIONS.md` ADR-058.

## 2026-08-23 (correction) — the "recall ceiling" framing above measured the wrong target. `min_crossings=6` needs no change.

**The catch.** The postscript entry above scored recall against *all* 53 labels uniformly — including the 48 `quality:2` labels, many of which are single failed-return-of-serve points (this session's "what counts as a rally" discussion established these legitimately belong in the presence-pass labels). But the project's actual goal is a highlight reel, not a complete inventory of every point played. Catching a failed return of serve isn't useful even if it's technically a "rally" — the pipeline shouldn't be tuned to chase it.

**Re-run split by quality, same diagnostic sweep:**

| `min_crossings` | n predicted | precision | recall (all 53) | recall (`quality:1` only, n=5) |
|---|---|---|---|---|
| 6 (shipped) | 22 | 0.818 | 0.340 | **0.800 (4/5)** |
| 4 | 49 | 0.490 | 0.453 | 0.800 (4/5) |
| 3 | 61 | 0.393 | 0.453 | 0.800 (4/5) |
| 2 | 90 | 0.267 | 0.453 | 0.800 (4/5) |
| 1 | 132 | 0.182 | 0.453 | 0.800 (4/5) |

**`quality:1` recall is flat at 4/5 across every value down to `min_crossings=1`.** Lowering the threshold recovers zero additional highlight-worthy rallies — it only admits more `quality:2`/noise segments (22→132 predictions) while precision collapses (0.818→0.182). `min_crossings=6` already performs at ceiling on the metric that actually matters, with far better precision than any lower value. **No change to the shipped default is warranted by this data.**

**The one missed `quality:1` rally (894.15–906.01s) is a tracking gap, not a threshold problem.** Its raw crossings are 895.37s, 896.20s, then nothing until 905.37s — a ~9-second stretch with zero detected net crossings in the middle of an 11.86s point. No `min_crossings` value can bridge a gap where the crossings were never detected at all; this is a ball-tracking robustness issue (likely occlusion or a lost-track stretch) during that specific rally, a different problem category entirely.

**Broader methodological point, worth keeping going forward:** presence-pass labels (honest, exhaustive, including trivial points) are the correct *labeling* target per `LABELING.md` — don't curate those. But *evaluation and tuning* should report recall/precision split by `quality` when a `PIC-31`/`min_crossings`-style question is being asked, not just the blended number against all labels — the blended number was actively misleading here. See `DECISIONS.md` ADR-059.

## 2026-08-23 (PIC-51) — IMG_7744 has the same label-completeness gap; relabeled, and ADR-059's correction holds up on a second video

**Motivation.** `IMG_7743`'s original labels missed 47 of 53 real rallies (this file, earlier today). A density sanity-check first: `IMG_7744`'s live-play fraction under its old 20 labels was **8.5%** — a striking outlier against `brickwall` (51.1%) and `pb_draft_cup` (26.7%), despite `IMG_7744` sharing IMG_7743's format (casual doubles) and near-identical mean rally length. Flagged `IMG_7744` as highest-risk for the same gap; `PIC-51` was filed to check.

**Relabeled** (`label_web.py` over Tailscale, full two-layer presence+quality pass): **20 → 75 labels**, live-play fraction 8.5% → **24.2%**. Confirms the same mechanism as `IMG_7743`: 3 `quality:1`, 72 `quality:2`.

**Re-scored against the shipped default and split by quality, same method as the ADR-059 correction:**

| `min_crossings` | n predicted | precision | recall (all 75) | recall (`quality:1`, n=3) |
|---|---|---|---|---|
| 6 (shipped) | 24 | 0.583 | 0.187 | **0.667 (2/3)** |
| 4 | 57 | 0.333 | 0.253 | 0.667 |
| 3 | 86 | 0.244 | 0.280 | 0.667 |
| 2 | 120 | 0.175 | 0.280 | 0.667 |
| 1 | 164 | 0.128 | 0.280 | 0.667 |

Same shape as IMG_7743: `quality:1` recall is flat across every `min_crossings` value — lowering the threshold doesn't recover the missed highlight rally, it only adds junk (predictions 24→164, precision 0.583→0.128). **A second video now confirms ADR-059's correction: `min_crossings=6` is not the bottleneck for what actually matters, and needs no change.** This also strengthens confidence in `PIC-43`'s original `dev`-derived choice — the metric that was contaminated by the labeling bug (blended recall) isn't the one `PIC-43` should have been optimizing anyway.

**Unlike IMG_7743, this video is not fully clean of unexplained false positives.** Precision (0.583) is meaningfully lower than IMG_7743's post-relabel 0.818, and of the 10 residual false positives at `min_crossings=6`, 8 are boundary near-misses (IoU 0.16–0.49) on real labelled rallies — the same fragmentation pattern as IMG_7743 — but **2 have zero relationship to any label** (IoU 0.000, no nearby rally at all): a 10.3s segment at 3.63–13.93s (near the very start of the video) and a very short 1.6s segment at 1203.27–1204.87s. These are either (a) a real short exchange the relabel pass still missed, or (b) genuine noise/hallucinated detection — consistent with the project's existing finding that IMG_7744's false positives were, on 2026-08-17 playback, predominantly real failed exchanges rather than hallucinated clutter (`[[project_second_camera_benchmark]]`), but not confirmed for these two specific segments. **Not yet playback-checked** — flagged as a follow-up rather than resolved here.

**Follow-up.**
1. Playback-check the 2 zero-IoU segments (3.63–13.93s, 1203.27–1204.87s) before treating IMG_7744's precision number as final.
2. `PIC-51` is otherwise answered: yes, `dev` had the same kind of gap. Worth a quick density check on `brickwall`/`pb_draft_cup` too, though their live-play percentages already looked internally consistent (see the earlier density table this session) — lower priority.

## 2026-08-23 (capstone) — the "internally consistent" check on brickwall/pb_draft_cup was circular. Relabeled both; all four videos are now honestly labeled, and the project-wide detection-quality story closes out.

**The check that wasn't a check.** The previous entry deprioritized `brickwall`/`pb_draft_cup` because their live-play percentages matched `PROGRESS.md`'s reference table (~50%, ~27%). User asked "what about the other two dev videos" — prompting a look at where that reference table came from. **It's computed from those same videos' own labels.** Comparing a label-derived density to a label-derived reference is not independent validation; it can't catch the gap IMG_7743/7744 had, because a wrong-but-self-consistent number always matches itself. Corrected in `PROGRESS.md` directly (the whole density table there is now flagged provisional pending relabel-confirmation, not to be trusted as an outlier-detection tool). This is `[[feedback_verify_mechanisms_rigorously]]`'s pattern again, this time about whether a validation check is actually independent.

**Relabeled both properly** (`label_web.py`, full two-layer pass):

| video | labels before | labels after | live % before | live % after |
|---|---|---|---|---|
| brickwall | 35 | **49** | 51.1% | **58.1%** |
| pb_draft_cup | 18 | **34** | 26.7% | **41.8%** |

Real gaps existed on both — smaller in relative terms than IMG_7743/7744's 4–9x jump, but pb_draft_cup's live-play percentage moved by 15 points (a ~57% relative increase), not a minor correction.

**Re-scored, quality-split, same method as ADR-059:**

| video | `min_crossings` | n predicted | precision | recall (all) | recall (`quality:1`) |
|---|---|---|---|---|---|
| brickwall | 6 (shipped) | 44 | 0.705 | 0.633 | **0.923 (12/13)** |
| brickwall | 1 | 103 | 0.340 | 0.714 | 0.923 (flat) |
| pb_draft_cup | 6 (shipped) | 22 | 0.864 | 0.559 | **0.700 (7/10)** |
| pb_draft_cup | 1 | 55 | 0.418 | 0.676 | 0.700 (flat) |

Same shape as IMG_7743/7744 a third and fourth time: `quality:1` recall is flat regardless of `min_crossings` — lowering the threshold recovers zero additional highlight-worthy rallies on either video, it only admits `quality:2`/fragment matches while precision collapses. **`min_crossings=6` is now confirmed adequate for the metric that matters on all four scored videos** (brickwall 12/13, pb_draft_cup 7/10, IMG_7743 4/5, IMG_7744 2/3) — the strongest evidence yet behind `PIC-43`'s original `dev`-derived choice, now checked against honest labels instead of the same kind of gap that motivated re-checking it.

**Residual false positives, checked against nearest label by IoU: all 16 (13 brickwall + 3 pb_draft_cup) are boundary fragments** (IoU 0.18–0.47), none unrelated to a real rally. Combined with IMG_7743 (4/4 fragments) and IMG_7744 (8/10 fragments, 2 unexplained — `PIC-52`), the project-wide false-positive picture is now almost entirely explained by two mechanisms: labeling incompleteness (fixed today, all four videos) and boundary fragmentation (`PIC-33`'s known, already-partially-addressed territory) — not genuine hallucinated junk or unresolved dead-time discrimination. `PIC-31`'s original problem statement (separate real rallies from dead-time junk) has, across every video this project has scored, turned out to be almost entirely a labeling artifact rather than a detection problem.

**`PROGRESS.md`'s density table finalized** with these numbers; no longer flagged provisional.

## 2026-08-23 (PIC-53, part 1) — the duration/rate threshold re-tested against honest labels: duration alone is a real, usable signal now, rate still isn't

**What this re-tests.** `PIC-31` candidate #1 (`EXPERIMENTS.md`, 2026-08-19 "yet later" entry) was rejected: "no video showed a clean separation... would misclassify 24–50% of real rallies as junk." Its sanity-check table was partly built from the now-retracted IMG_7743 post-bump "confirmed dead-time" list, and its broader check scored against the old, incomplete labels on all four videos. Re-run against today's honestly relabeled ground truth (IMG_7743 post-bump, IMG_7744, brickwall, pb_draft_cup — pre-bump excluded, still unverified).

**Method.** All raw crossing-burst candidates generated at `min_crossings=1` (unfiltered — every cluster `cluster_crossings` would ever propose), matched against the new labels at IoU≥0.5 to split real vs. junk, then compared on duration and crossing rate.

**Result: duration separates cleanly by an order of magnitude on medians, though the tails still overlap.**

| video | real median dur | junk median dur | real median rate | junk median rate |
|---|---|---|---|---|
| IMG_7743 postbump | 5.5s | 0.7s | 1.26/s | 1.08/s |
| IMG_7744 | 5.8s | 0.9s | 1.14/s | 1.29/s |
| brickwall | 17.0s | 1.1s | 1.36/s | 1.02/s |
| pb_draft_cup | 7.8s | 0.8s | 1.03/s | 1.34/s |

This is a much bigger gap than 2026-08-19 found (then: real median 11.8s vs. junk median 5.6s — a ~2x ratio with heavy overlap; now: 6–15x ratio). **Crossing rate shows no comparable improvement** — junk's median rate is at or above real's on 3 of 4 videos, because very-short junk clusters (a lone 2-crossing blip in 0.2s) inflate rate by dividing by a tiny duration. Rate is not a usable feature; duration is.

**Real tail overlap still exists — not a clean cut.** Per video, the shortest real rally and the longest junk segment: IMG_7743 postbump (min real 2.4s, max junk 11.6s), IMG_7744 (2.7s / 17.4s), brickwall (3.1s / 17.5s), pb_draft_cup (3.0s / 7.0s). A hard duration cutoff will always trade recall for precision somewhere in this range.

**Pooled threshold sweep (diagnostic — includes `eval`'s IMG_7743, not a parameter pick per ADR-052):**

| duration cutoff | precision | recall |
|---|---|---|
| ≥1.5s | 0.436 | 1.000 |
| ≥2.5s | 0.520 | 0.990 |
| **≥3.0s** | **0.599** | **0.971** |
| ≥4.0s | 0.690 | 0.864 |
| ≥5.0s | 0.775 | 0.767 |

At `≥3.0s`, 97% of real rallies are kept while precision roughly triples over the unfiltered base rate (~23% pooled). This does not match 2026-08-19's "misclassifies 24–50% of real rallies" characterization at any reasonable operating point — the original rejection's numbers were measuring the contaminated-label problem, not a real property of the duration signal.

**But it's largely redundant with what's already shipped.** Checked whether a duration filter would trim any of the current `min_crossings=6` false positives (all previously identified as boundary fragments, this session): almost none are short enough — most residual fragments across all four videos are already ≥3s (the shortest, IMG_7744's `1203.27–1204.87s`, is the one segment flagged as fully unexplained in `PIC-52`, not a typical fragment). **A duration filter does not further clean up the false positives `min_crossings=6` already leaves behind** — it's a comparably effective gate to crossing-count when applied from scratch, not an additive improvement on top of the current pipeline.

**Conclusion.** The 2026-08-19 rejection was a contamination artifact, not a correct negative result — duration (not rate) has real, substantial signal once tested against honest labels. Doesn't change the shipped default (min_crossings=6 already captures the same information this signal would provide), but corrects the project's record: `PIC-31` candidate #1 should not be cited as "tried and failed" going forward. Filed as part of `PIC-53`.

## 2026-08-23 (PIC-53, part 2) — the stillness ratio can't be re-tested: there's no confirmed genuine dead time left anywhere in the project's relabeled footage

**What this re-tests.** The other half of `PIC-53`: re-run `scripts/pose_stillness.py` against genuine dead-time examples, now that all four videos are honestly labeled.

**There's nothing to run it against.** Across all four videos' residual false positives at the shipped `min_crossings=6` (the natural place a sustained courtesy-return/dead-time exchange would show up — short 1–2-crossing noise blips don't cluster this high), the count is **30 total, 28 confirmed boundary fragments (real rallies, ADR-060), 2 unconfirmed (`PIC-52`, IMG_7744), 0 confirmed genuine dead time.** This holds across every format the project has footage for — casual doubles (IMG_7743, IMG_7744), tournament doubles (brickwall), and singles (pb_draft_cup).

**This is itself the finding, not a null result to work around.** `PIC-31`'s founding question — distinguish real rallies from dead-time crossings — doesn't currently have a valid test set anywhere in this project's labeled footage. Not "the stillness signal failed again"; there is no dead-time example left to fail against. Two ways this could change: (1) `PIC-52`'s playback check on the 2 unconfirmed IMG_7744 segments finds real dead time there, giving n=1 or 2 — thin, but something; (2) new footage is captured and labeled with genuine dead time correctly distinguished from missed short rallies from the start (the two-layer presence pass, applied by someone who's now seen today's failure mode, should naturally produce this).

**Conclusion.** `PIC-53` is answered for both halves: the duration signal deserves un-rejecting (part 1), and the stillness signal can't be re-tested at all for lack of material (part 2) — which is a stronger, more informative answer than "still inconclusive." Recommend closing `PIC-53` on this basis rather than leaving it open pending a test that has nothing to run against.

## 2026-08-23 (follow-up, off the back of PIC-53) — does the stillness dip actually mark the rally start? Localization test on brickwall, plus a labeling-convention finding that reframes it

**What this tests.** A different question than PIC-53's presence/absence check: given the stillness dip exists, does its *timing* land on the labeled rally start, or somewhere else? Tested on brickwall specifically (the video with the cleanest established dip) since it now has 49 honest labels spanning the whole video, not just the 3–4 boundaries in the first 135s checked in the original 2026-08-22 entry.

**Method.** 17 rally starts sampled evenly across the full video (every 3rd label). For each, pulled the raw per-frame ankle-speed series (`scripts/pose_stillness.py`'s `track_speeds`) over a `[start−6s, start+1.5s]` window, found the timestamp of minimum speed within a `[start−5s, start+0.5s]` search band, and compared it to the labeled `start`.

**Result: the dip is reliably present, but its timing does not land on the label.**

| | value |
|---|---|
| dip present (ratio < 0.2 at the minimum) | 15 / 17 (88%) |
| offset (dip time − label start), mean | −1.29s |
| offset, median | −1.07s |
| offset, std | 1.31s |
| within ±0.5s of label | 5 / 17 (29%) |
| within ±1.0s of label | 8 / 17 (47%) |
| within ±2.0s of label | 12 / 17 (71%) |

Full per-rally numbers in scratch output (not committed — reusable via `scripts/pose_stillness.py`'s `track_speeds`, this specific windowed-minimum search wasn't turned into a script). The two rallies without a sharp dip: the video's very first labeled rally (no prior dead time to baseline against, same edge case the original entry flagged) and one late-video rally at ratio 0.22 (a near-miss, not a clear failure).

**Then a labeling-convention finding reframed the whole result.** Asked the operator directly why the dip consistently lands *before* the label rather than on it — confirmed today's relabeling pass (`PIC-49`/`PIC-51`) intentionally sets `start` a few seconds before actual serve contact, for viewer lead-in, varying by feel (roughly 0–3s) rather than a fixed or tracked offset (`DECISIONS.md` ADR-062, which also codifies this in `LABELING.md` v4). This median-1.07s/1.3s-spread "imprecision" is consistent with — and largely or fully explained by — that same variable padding, not the dip itself wandering relative to true serve contact.

**Conclusion, properly scoped.** The dip is a reliable *presence* signal (88% of rally starts show it, at scale, across the whole video — not just a handful of early examples) but was never validated as a precise *boundary* marker, and the "imprecision" measured here is now understood to be confounded with an intentional labeling convention, not necessarily a property of the signal itself. Re-measuring against literal serve-contact timestamps (not available in the current labels) would be needed to know how tight the dip-to-contact relationship really is. As originally proposed (2026-08-22 entry), this remains best suited as a **leading-indicator trigger** ("dip fires → watch for a confirming net-crossing burst in the following few seconds") rather than a boundary marker in its own right — this test gives real lead-time numbers (median ~1s+ before the labeled, padded start; true lead before actual contact likely somewhat more) for that window design, still to be picked deliberately rather than guessed.

**Follow-up.**
1. Not yet done: the same localization test on `IMG_7743`, which showed no dip at all in yesterday's test — would help settle whether the pause is genuinely absent there or whether that earlier null result was also a labeling-convention artifact.
2. Not yet done: re-run at the full 49-label scale on brickwall rather than the 17-sample subset.
3. `eval/harness.py`'s IoU matching needs a real design decision for the intentional `start` lead-in (ADR-062) before boundary-sensitive numbers like this one can be fully trusted.

## 2026-08-23 (follow-up) — a first quantitative answer to PIC-55: `src/render.py` already pads clips 3s before cutting them; `eval/harness.py` never sees it. About a third of ADR-060's "boundary fragments" are this, not `gap_sec` imprecision.

**What prompted this.** Direct question: if labels intentionally lead in a few seconds before serve contact, why doesn't the pipeline already do the same for its output? It does — `src/render.py`'s `cut_clips(..., pad_sec=3.0)` subtracts 3s from every segment's start (and adds 3s to `end`) before cutting the actual viewer-facing clip. This has existed the whole project; it was never applied to the scoring path (`eval/harness.py` matches raw, unpadded `rally_segments_from_predictions` output against labels), so the two never lined up.

**Quick check: re-IoU'd all 28 of today's fragment-classified false positives** (ADR-060, IMG_7743/7744/brickwall/pb_draft_cup combined) with the predicted segment's start shifted `max(0, start − 3.0)`, end unchanged (matching `LABELING.md` v4 — `end` isn't padded, only `start` is):

| | count |
|---|---|
| now cross IoU≥0.5 (would flip from FP to matched) | 9 / 28 (32%) |
| IoU improved at all | 21 / 28 (75%) |
| IoU got worse (predicted segment already started before the label) | 7 / 28 (25%) |

**Both explanations are real, not one replacing the other.** Roughly a third of what ADR-060 attributed to `gap_sec`-clustering fragmentation was actually just the scoring path not applying the pipeline's own existing lead-in convention. The rest — including the 7 cases that got *worse* under a flat pad, where the predicted segment already starts earlier than the label — is genuine boundary imprecision, still `PIC-33`'s territory, not resolved by this.

**Consequence.** `PIC-55`'s open question is now partially answered empirically, not just in principle: a flat 3s start-shift is a real, measurable improvement but not a full fix — it's the wrong shape for at least a quarter of cases (should be adaptive per-segment, not a flat constant, the same lesson `gap_sec` and `min_crossings` already learned). Still needs a real implementation decision in `eval/harness.py`, not just this diagnostic.

## 2026-08-23 (selection signals, part 1) — with detection quality resolved, testing candidate quality-ranking signals against today's honest quality grades: duration confirmed, crossing rate confirmed with a caveat

**Motivation.** `PROGRESS.md` has listed selection/ranking ("competitive vs. casual") as **not built**, explicitly gated on precision — which ADR-060 just closed out. Today's relabeling also produced, for the first time, a reasonably-sized set of human quality grades (`quality:1`/`quality:2`) across four independent videos/formats to test candidate signals against, instead of the single small brickwall sample PIC-45 had before.

**Duration.** Median rally duration, `quality:1` vs `quality:2`, all four videos: IMG_7743 postbump 11.8s vs 6.8s (1.7x), IMG_7744 10.6s vs 7.0s (1.5x), brickwall 20.7s vs 11.5s (1.8x), pb_draft_cup 9.1s vs 6.7s (1.4x). Consistent direction on all four, independently. Real signal, small per-video `quality:1` samples (n=3–13).

**Crossing rate — the operator's direct challenge to ADR-054.** ADR-054 rejected raw net-crossing *count* as a shot-count proxy (kitchen dinks double-count, inflating the number relative to true shots hit). Operator's counter: even if inflated, a shorter average time between crossings still indicates a real burst of activity, and that's worth ranking on regardless of exact shot count. Tested directly: crossings-per-second (count within the labelled window ÷ duration), split by quality, all four videos.

| video | `quality:1` crossings/s | `quality:2` crossings/s |
|---|---|---|
| IMG_7743 postbump | 0.80 | 0.71 |
| IMG_7744 | 0.76 | 0.61 |
| brickwall | 1.20 | 0.91 |
| pb_draft_cup | 0.78 | 0.67 |

**Higher for `quality:1` on all four, independently — a real, reproducible signal.** A secondary check (median gap between consecutive crossings, a more direct "tempo" measure than the aggregate rate) was inconsistent — 2 of 4 videos went the wrong direction — so it's specifically the aggregate rate that correlates, not necessarily "burstiness" in a tight tempo-spike sense.

**Caveat, not resolved either way:** can't distinguish from this data whether crossing rate is tracking genuinely more shots exchanged, or tracking kitchen-dink-heavy sequences specifically (which ADR-054's double-counting mechanism would inflate) that happen to often be graded `quality:1` because `LABELING.md`'s checklist names "an extended dinking/kitchen-line battle" as a valid highlight factor in its own right. Doesn't block using the signal for ranking — ADR-054 ruled out crossing count as an *exact shot-count* claim, which this isn't attempting to be — but the causal story is genuinely unresolved.

**Follow-up.** Test ball/player velocity spikes next (not yet run). File this whole thread as tracked selection-signal work rather than leaving it in `EXPERIMENTS.md` only, once velocity is tested too.

## 2026-08-23 (selection signals, part 2) — ball velocity spikes: doesn't survive, and the reason is a duration confound worth naming as a general trap

**Method.** Ball pixel-space frame-to-frame speed within each labelled window, gated the same way the rest of the pipeline gates ball position (`court_wedge`, plus rejecting jumps >150px or across a >0.15s gap — the same teleport-rejection threshold `track_ball` uses elsewhere, applied inline since `track_ball` only returns image-y, not a full (x,y) track). Two statistics per rally: **peak** (single fastest frame-to-frame movement) and **p95** (95th-percentile speed — a "sustained high end," less sensitive to one noisy frame).

**First pass used raw, ungated predictions and produced nonsense** (median "peak" speeds of 9,000–28,000 px/s — physically impossible at 30fps on this frame size) — background/adjacent-court clutter detections, not real ball motion. Caught before reporting it, re-run with the same `court_wedge` + jump-rejection gating every other analysis today used. Flagging this explicitly: it's the same mistake this project has hit before (ADR/EXPERIMENTS history, `PIC-2`/court-wedge work) — an ungated detection stream produces confidently wrong numbers that look like real signal until checked.

**Gated result — peak and p95 disagree in direction:**

| video | q1 peak | q2 peak | q1 p95 | q2 p95 |
|---|---|---|---|---|
| IMG_7743 postbump | 1572 | 1526 | 875 | 935 |
| IMG_7744 | 1931 | 1399 | 975 | 980 |
| brickwall | 3042 | 2535 | 741 | 891 |
| pb_draft_cup | 3762 | 3329 | 1521 | 1672 |

**Peak is higher for `quality:1` on all four videos — but this is very likely a duration confound, not a real velocity effect.** `quality:1` rallies are already established (this file, selection-signals part 1) to run 1.4–1.8x longer than `quality:2`, which means proportionally more frames and more chances to sample one extreme fast frame — the maximum of a larger sample is expected to be higher even under an *identical* underlying speed distribution, independent of anything about quality. **p95 (a statistic much less sensitive to this sample-size effect) shows no positive signal at all — it's lower for `quality:1` on all four videos.** The two statistics point opposite directions, and the more trustworthy one (p95) doesn't support the hypothesis.

**Conclusion: ball velocity does not survive as a candidate ranking signal from this test**, unlike duration and crossing rate. Not ruled out forever — a properly duration-normalized measure (e.g. top-k mean speed with k held constant, or a bootstrap-adjusted peak) might behave differently — but the naive "does the ball move fast at some point" version doesn't hold up, and the reason it looked like it did (raw peak) is a specific, nameable statistical trap worth remembering for any future rally-level feature: **a longer window will show a more extreme max of anything, so raw max/peak features need duration-normalization before they can be trusted as quality signals, separate from duration itself.**

**Player velocity spikes (skill-display moments — a dive, a sprint recovery) were not tested** — this analysis used ball tracking only; player pose tracking would need the same `pose_stillness.py`-style YOLO pipeline used for the stillness signal, not yet run for this purpose.

**Correction, immediately after — the duration-normalized version does survive.** Applied the fix named above: mean of the top-5 fastest frame-to-frame ball speeds within each rally (`K=5`, fixed regardless of rally length, same gating as above), instead of the raw single max.

| video | `quality:1` top-5 mean | `quality:2` top-5 mean | difference |
|---|---|---|---|
| IMG_7743 postbump | 1204 | 1112 | +8% |
| IMG_7744 | 1346 | 1118 | +20% |
| brickwall | 1755 | 1494 | +17% |
| pb_draft_cup | 2566 | 1993 | +29% |

Higher for `quality:1` on all four videos, without the duration-count artifact — this statistic doesn't grow with rally length the way a raw max does. **Ball velocity is a real candidate signal after all; it needed the right statistic, not a different feature.** Third signal validated today (alongside duration and crossing rate), same caveat as the others: real, consistent across four independent videos, small `quality:1` samples per video.
