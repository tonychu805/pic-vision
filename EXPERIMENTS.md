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
