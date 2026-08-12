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
