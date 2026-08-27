# Tech Spec — Pickleball Rally Cutter

**Status:** Draft · **Owner:** Tony · **Last updated:** 2026-08-12

Requirements and success criteria: [`PRD.md`](./PRD.md). Rationale for the choices below: [`DECISIONS.md`](./DECISIONS.md).

Dev machines:
- **RTX 2000 Ada workstation** (16 GB VRAM, Ada Lovelace, Ubuntu 26.04 LTS) — primary for TrackNet fine-tuning and GPU training. Spec: ASRock X299E-ITX/ac · Corsair H80i · SF450 · MONTECH TEN ITX · NVMe + SATA SSDs.
- **MacBook Air M2** — CoreML (ANE inference, yolov8x.mlpackage) and MLX where applicable. Still in use for lightweight iteration and on-device inference experiments.

Camera: Tapo C200 V3. Production target: N100 edge box + RunPod GPU (ADR-043).

---

## 1. Capture and ingest

Processing operates on a local file. Nothing reads the camera stream live (ADR-013).

**Current camera: Tapo C200 V3, fixed at 1080p / 30 fps.** Its remaining weakness is no manual shutter control (ADR-002), partly mitigated by the fixed frame rate capping exposure at 1/30 s (ADR-025). It satisfies the requirement that outranks everything else: it records standalone at a court with no network. Selection criteria and rejected alternatives are in ADR-029 — that table is the shopping list if Phase 0 shows the blur is fatal.

Judge any replacement on **pixels-on-ball at the far baseline**, not sensor resolution — a wide lens can cancel a resolution gain entirely.

### 1.1 Preflight — before every session

```bash
ffprobe -v error -select_streams v:0 -count_frames \
  -show_entries stream=avg_frame_rate,width,height,nb_read_frames \
  -i "rtsp://user:pass@<cam-ip>/stream1"

ffprobe -v error -select_streams a:0 \
  -show_entries stream=codec_name,sample_rate,channels \
  -i "rtsp://user:pass@<cam-ip>/stream1"
```

**The camera is fixed at 1080p / 30 fps** (ADR-025). This also caps exposure at 1/30 s, since a camera cannot expose longer than its frame interval — a partial mitigation of the blur problem, though lighting is still the binding constraint.

Asserts: 1920×1080. Audio presence is **recorded, not required** (ADR-004) — its absence disables §5.1b and nothing else. **Trust `avg_frame_rate`, not `r_frame_rate`** — the latter is a guess FFmpeg derives from timestamp arithmetic, and it inflates wildly on any irregularity.

**Confirm the rate once, in Phase 0.** Probe a short recording rather than the live stream — on RTSP there is no duration, so `avg_frame_rate` is frequently `0/0`:

```bash
ffmpeg -rtsp_transport tcp -i "rtsp://user:pass@<ip>/stream1" -t 30 -c copy probe.mp4
ffprobe -v error -select_streams v:0 -count_frames \
  -show_entries stream=avg_frame_rate,nb_read_frames,duration -of default=nw=1 probe.mp4
```

`nb_read_frames / duration` is the trustworthy figure. Then confirm the deltas are uniform:

```bash
ffprobe -v error -select_streams v:0 -show_entries frame=pkt_pts_time \
  -read_intervals "%+#300" -of csv=p=0 -i probe.mp4 | \
  awk -F, 'NR>1{d=$1-p; printf "%.4f\n", d} {p=$1}' | sort -n | uniq -c
```

This reads the raw stored timing rather than any derived field. Uniform ≈ 0.0333 deltas confirms CFR at 30. Once confirmed, this is settled — it is not a per-session gate.

Two rules stand regardless, because both are free and both remove classes of silent bug:

1. **All timestamps come from PTS, never `frame_index / fps`.**
2. **All temporal parameters are configured in seconds**, converted to frames at runtime — never hard-coded frame counts. Prior art bakes in "0.6 s = 18 frames @ 30 fps," which breaks the moment anything about capture changes.

### 1.2 Recording

```bash
ffmpeg -rtsp_transport tcp -i "rtsp://user:pass@<cam-ip>/stream1" \
  -c copy -f segment -segment_time 600 -reset_timestamps 1 \
  session-%03d.mp4
```

`-c copy` avoids re-encoding, so this is nearly free on CPU. Segmenting every 10 minutes means a crash or Wi-Fi drop costs one segment, not the session. Concatenate with the concat demuxer before processing.

Rejected: recording to microSD and exporting via the Tapo app — many small segments, manual export, and no certainty about what frame rate and audio actually got written. Pulling RTSP means the file processed is the file preflight validated.

**Timestamps and clean stop.** Include `-use_wallclock_as_timestamps 1` in the capture invocation — the camera's RTP timestamps are unreliable and non-monotonic (ADR-030). End recordings with ffmpeg's own `-t <duration>` flag or SIGINT; never stop with an external hard kill (`timeout`/SIGKILL) — that was observed to corrupt the output container (ADR-031). If the audio codec is `pcm_alaw`, the container **must** be MKV — MP4 does not support that codec tag.

---

## 2. Prior art

Surveyed 2026-07-30. **Benchmark these against `eval-set-A` before writing a detector** (ADR-021).

| Project | What it is | Take from it | Watch out for |
|---|---|---|---|
| [vinod-polinati/pickleball-rally-detection](https://github.com/vinod-polinati/pickleball-rally-detection) · MIT | Roughly our Phases 1–2 in ~200 lines. YOLOv8x @ 1280, conf 0.15, COCO `sports ball` — **no custom training**. Size / shoe / physics filters → binary ball-present timeline → 0.6 s gap tolerance → FFmpeg stream-copy clips. | **The whole approach.** Ball *presence* as the rally signal (ADR-022). The shoe filter — bottom 45% of a player box — addresses the most common false positive in court sports. Physics filter rejecting > 300 px/frame doubles as scene-cut detection. | **Zero accuracy numbers.** "87 rallies found" with no ground truth. YOLOv8x every frame is ~1 TFLOP/frame — hours on an M2. README references `rally_detector.py`; repo contains `rallysplitv.py` (3 commits). |
| [ryan-tolone.com/projects/pickleball](https://ryan-tolone.com/projects/pickleball) | Highest-quality reference. Analytics overlay — speed, distance, shot count, minimap — not rally cutting. YOLOv8 + ResNet50 court keypoint regressor + iterative homography refinement to ~0.2 ft residual. | **Independently confirms three of our decisions** (see below). Anchor-based ball linker with per-frame max-step constraint, "the ball cannot teleport" — halves ID switches vs nearest-neighbour. Detection caching so reruns skip inference. Pure-Python test suite running without torch in < 1 s. | Different product; the rally-segmentation logic isn't there. Not packaged as a library. |
| [5urabhi/Pickle_ball_tracking](https://github.com/5urabhi/Pickle_ball_tracking) · MIT | Thin (2 commits). Bounce detection and in/out calls, Kalman filtering via `filterpy`. | Calibration is **"click the four corners"** — a third vote for manual calibration, and a reminder that **4 points suffice** for a homography. Our 12 buy redundancy and a RANSAC fit; worth asking whether 4 is enough for the prototype. | Minimal, unmaintained, no metrics. |
| [Roboflow: liberin-technologies/pickleball-vision](https://universe.roboflow.com/liberin-technologies/pickleball-vision) | Public dataset, 2023. | Could remove most of the labelling in §11.4. | **Unassessed.** Image count, class list, and licence were not visible; the listed "use cases" are auto-generated filler. **Check camera angles first** — broadcast or mixed-angle footage won't transfer to a fixed baseline mount, and a domain-mismatched dataset is worse than none. |

### What prior art confirms

- **ADR-006 (never 640).** Tolone measures ball detection at **~60% @ 640 → ~100% @ 1280**. This is the number that forced the ADR-005 revision.
- **ADR-007 (hand-click the court).** Tolone's *priority-1* strategy is manual keypoint override — "most accurate option for fixed-camera shots" — after noting a trained ResNet regressor lands 30–100 px off on unfamiliar angles. 5urabhi clicks 4 corners. Three projects, same conclusion.
- **§5.3 trajectory-based association.** Tolone's anchor linker and vinod's physics filter are both the max-step constraint specified here, arrived at independently.

### What none of them do — the actual differentiators

1. **Audio.** Not one uses it. Everyone reaches for CV by reflex.
2. **Selection under a duration budget.** All produce *every* rally. Nobody produces a 10-minute reel.
3. **Any measurement at all.** No recall, no false-positive rate, no boundary error published anywhere. Our harness could evaluate their work — which is a decent sign it was the right thing to build first.

---

## 3. Architecture

> **Current primary approach (2026-08-09): v1 — ball net-crossings.** Real footage showed player dead-time markers inverted on casual play (ADR-039). v0 (T1′ player geometry as primary detector, described below) is frozen as a baseline. v1 wires `detect_candidates → track_ball → crossing_times → cluster_crossings → segment → render`. Both paths share `segment.py`, `render.py`, and the eval harness. The v0 architecture below remains the spec for the frozen baseline.

**Detection is video-primary and works with audio entirely absent** (ADR-004, ADR-028). Rallies are found by detecting *dead time* and taking the complement (ADR-026). *(v0 architecture — frozen baseline)*

```
                    ┌─────────────────────────────────────┐
  session.mp4 ─────►│ T0′ Motion energy in court ROI      │──► coarse regions
   (local)          │     CPU · no model · skips dead     │    (~30–40% skipped)
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │ T1′ Player detection + geometry     │──► DEAD-TIME MASK
                    │     YOLOv8n @ 2 fps · ANE           │    complement = rallies
                    │     PRIMARY DETECTOR                │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │ T2′ Ball presence + side-alternation│──► fewer FPs,
                    │     optional · no trajectory        │    tighter bounds
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │ (opt) Audio onsets, gated on motion │──► boundary precision
                    │     only if the usability gate pass │    (ADR-027)
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │ Invert mask → state machine → pad   │
                    │ → merge overlaps → rallies.json     │
                    └──────────────┬──────────────────────┘
                     ┌─────────────┴─────────────┐
                     ▼                           ▼
         ┌───────────────────────┐  ┌────────────────────────────┐
         │ render all            │  │ rank + budget select (§7)  │
         │ → rallies_full.mp4    │  │ → render → highlights.mp4  │
         └───────────────────────┘  └────────────────────────────┘
```

Every tier below the primary is optional; the pipeline degrades rather than failing (ADR-003). Detection runs once. `rallies.json` is the contract between detection and rendering, and the only artifact the eval harness reads.

### Why this shape

| Modality | Spatial selectivity | Temporal precision |
|---|---|---|
| **Video** | Confined to the calibrated court | Poor — ~500 ms at 2 fps |
| **Audio** | **None** — hears the whole building | Excellent — tens of ms |

A venue has many courts producing acoustically identical impacts, so spatial selectivity is the property that cannot be given up. Video is therefore primary, and audio — where usable — contributes only timing (ADR-027).

---

## 4. Court calibration

Manual, once per camera mount (ADR-007). `calibrate.py`:

1. Grab a clean frame from the session.
2. **Undistort first.** The C200's wide lens has radial distortion a planar homography cannot absorb. Estimate coefficients once with a checkerboard → `camera_intrinsics.json`.
3. Operator clicks 12 court intersections in a fixed prescribed order:
   - 4 outer corners
   - 4 non-volley-zone line × sideline
   - 2 centerline × baseline
   - 2 centerline × NVZ line
4. `cv2.findHomography(..., method=cv2.RANSAC)` → canonical 20 × 44 ft court.
5. Persist `court_calibration.json`. Reprojection RMSE > 5 px fails and prompts a re-click.
6. Emit the **court ROI polygon** (court + 5 ft margin) used to mask T0's motion path and crop T1's input.

Per-session check: re-verify reprojection against the stored calibration; warn if the mount shifted.

---

## 5. Tier specifications

### 5.1 T0′ — motion energy pre-filter

Cheap, model-free, and used only to skip stretches where nothing is happening at all (between games, empty court). It does **not** decide rally boundaries.

- Decode at 5 fps, grayscale, downscale to 480×270, hardware-accelerated:
  ```bash
  ffmpeg -hwaccel videotoolbox -i session.mp4 -vf "fps=5,scale=480:270,format=gray" -f rawvideo -
  ```
- `cv2.absdiff` between consecutive frames, masked to the court ROI polygon, sum of absolute differences → per-timestep motion energy.
- ~0.05 ms/frame. Decode dominates entirely.
- Output: coarse regions where motion exceeds a low threshold. Expect ~30–40% of the session to be skipped, cutting T1′'s frame count proportionally.

Threshold deliberately loose — this stage may over-include freely, but must never exclude a real rally. It is a cost optimization, not a detector.

**Do not use dense optical flow.** Farnebäck at this resolution is 10–20 ms/frame — ~9 minutes per session, making CV the bottleneck instead of decode, for information this stage doesn't need. If direction is ever required, use sparse Lucas-Kanade on a grid (~1–2 ms/frame).

### 5.1b Audio path — optional, gated

Runs only if the usability gate in §1.1 passes (ADR-004).

```bash
ffmpeg -i session.mp4 -vn -ac 1 -ar 22050 audio.wav
```

Onset detection via **spectral flux**, band-limited to roughly 1–8 kHz. Spectral flux rather than an amplitude threshold because a dink is a soft touch shot and a drive is loud — amplitude varies hugely *within* a single rally, so onsets must key on spectral change. STFT with hop 512 at 22.05 kHz gives ~23 ms resolution; ~310k windows per 2-hour session, 20–60 s of compute.

**Cross-modal gating (ADR-027):** an onset counts as an impact only if court-ROI motion is simultaneously above threshold. This rejects adjacent-court impacts, which are acoustically identical to ours and cannot be separated any other way with a single omnidirectional mic.

Audio contributes **boundary precision only** — tens of milliseconds, versus ~500 ms from 2 fps video. It never gates whether a rally exists.

**Audio usability gate.** Measure onset density during a stretch labelled dead time. Dense onsets while nothing is happening on our court means the audio is contaminated; set its weight to zero for that recording and log it. Automatic, not a judgement call.

### 5.2 T1′ — player detection + geometry (PRIMARY)

- YOLOv8n, `person` class, pretrained COCO weights. **No custom training** — off-the-shelf person detection on 1080p is already reliable.
- Input: court-ROI crop, ~1280 px on the long edge (ADR-006).
- **Sample at 2 fps, not 5.** T1′ only answers "are players in serve formation, how fast are they moving" — positions are slowly varying. This is the single biggest cost lever: 2 fps over ~48 min of candidates is ~5,800 frames (~3–6 min) versus ~29,000 at 10 fps (~30 min). Runs across the whole session, not just candidates (ADR-028) — the motion pre-filter is what keeps that affordable.
- **Export to ONNX, then convert to CoreML and run on the Neural Engine** (ADR-023) — not PyTorch/Metal. Small conv nets are memory-bandwidth bound, not compute bound; per-kernel launch overhead leaves the Metal path at 15–30% utilization. The ANE is typically 2–4× faster here.
- Ground position: bounding-box bottom-center ≈ foot contact → project through the homography. **Valid only because feet are on the ground plane** (ADR-009).
- No tracking, no player IDs (ADR-008). Every feature below is computed from per-frame positions plus frame-to-frame differences.

#### 5.2.1 Dead-time events — the primary output

Each fires on geometry, is high-precision on its own, and is unioned into a dead-time mask. Rallies are the complement (ADR-026).

| Event | Test | Default |
|---|---|---|
| **Net crossing** | Any player's court-space y crosses the net line | — |
| **Court exit** | Any player's foot position leaves the court polygon | — |
| **Ball held** | Ball box inside a player box continuously | > 0.5 s |
| **All stationary** | Every player's speed below threshold | > 1.5 s, < 0.5 ft/s |
| **Player shortfall** | Fewer than expected players inside the court | tolerance ≥ 1 frame gap |

**Occlusion tolerance is mandatory.** From a baseline camera the near player regularly occludes the far one, so player count drops spuriously. Require an event to persist over several consecutive samples before it fires; never trigger on a single frame.

#### 5.2.2 Supporting features

Both discriminate better than raw motion magnitude, which conflates "playing hard" with "walking briskly" (ADR-028).

- **Direction-reversal rate** — sign changes in each player's velocity vector, in court feet, over a sliding window. Ball retrieval is smooth and unidirectional for seconds; rally movement reverses constantly (split-step, lateral, forward-back).
- **Bilateral motion coupling** — split the court ROI at the net, compute motion energy per side, cross-correlate over a 2–3 s window with a short lag. During a rally the sides are coupled because players react to each other; during retrieval or discussion they are independent.
- Serve formation: one player behind the baseline, opponents in position.
- Aggregate player speed.

### 5.3 T2′ — ball detection (optional; daylight only)

**Superseded 2026-08-17 (see [`DECISIONS.md`](./DECISIONS.md) ADR-046/047).** This section describes the original design — ball detection as an optional boundary-refinement layer (§5.3.2) on top of a player-primary detector (T0′/T1′), running only on short windows around already-found rallies, with TrackNet as a last-resort rung behind two YOLO tiers. That is not what got built. What actually ships: **TrackNet, on the full video, is the primary and only active detector** (`src/tracknet.py`, GPU inference via `scripts/pod_infer.py`); the YOLO ball path below is archived (`archive/yolo_pipeline.py`, `archive/yolo_detect.py`) and the player-primary path (`src/players.py`/`src/events.py`) is frozen, not the spine. Left in place as a historical record of the reasoning, not as current instructions — do not build against §5.3.1/5.3.2 as written.

Entered only if T0′+T1′ miss the PRD targets (ADR-011). Daylight only — the camera has no manual shutter control, so in low light the ball smears past recovery (ADR-002).

**Two distinct uses, with very different quality bars.** Conflating them is what made the original estimate wrong.

#### 5.3.1 Ball *presence* — a fusion feature, cheap

Per ADR-022, a binary "is a ball visible this frame" signal is a strong rally indicator on its own, and detection misses are bridged by the same debouncing the state machine already applies. It needs no trajectory quality at all.

- Off-the-shelf YOLOv8 on the COCO `sports ball` class, `imgsz=1280`, low confidence (~0.15)
- Three filters, from prior art (§2):
  - **Size** — reject detections above ~65×65 px (net posts, equipment, torsos)
  - **Shoe** — reject detections in the bottom ~45% of a player box plus a small buffer; the most common false positive in court sports
  - **Physics** — reject frame-to-frame jumps above ~300 px; doubles as scene-cut detection
- No labels, no training.

Derived features, none needing trajectory:

- **Ball side-alternation** — detected left of the net at *t*, right at *t+k*, means play is in progress. A weak trajectory in the only dimension that matters.
- **Ball-to-nearest-player distance** — a held ball sits at ~0 px from a person box; a ball in play is far from everyone most of the time. Feeds the "ball held" dead-time event (§5.2.1).
- **Ball visible fraction** over a sliding window.

**Courtesy-return suppression.** After every point someone taps the ball back to the server, producing a net crossing, one side-alternation, and a motion burst. This is systematic, not rare — it happens after *every* rally. Require several side-alternations plus minimum duration: a real rally has several crossings, a courtesy return exactly one (ADR-028). *The **≥ 2** figure below is the original design intent, historical.* The shipped `min_crossings` default is tuned by direct measurement, not restated here — see `src/tracknet.py`'s docstring and DECISIONS.md ADR-048 for the current value and its evidence.

#### 5.3.2 Ball *trajectory* — boundary refinement, expensive

Only for tightening timestamps. Climb this ladder and stop as soon as the boundary target is met (ADR-005 revision):

1. Off-the-shelf YOLOv8 @ 1280 — no labels, no training
2. YOLOv8 fine-tuned on pickleball footage — Tolone reports ~100% detection this way
3. TrackNet-family (3 frames → heatmap) — **fallback only**, if 1–2 miss the target

Applies to all rungs:

- **Boundary windows only** — ±3 s around each detected rally start and end (ADR-015). ~14,000 frames per session instead of ~86,000.
- **Association is trajectory-based, never IoU or nearest-neighbour.** At 30 fps a 40–60 mph ball moves 2–3 ft per frame — 100–200 px, or 15–25× its own diameter. Predict from velocity, search a window around the prediction. Prior art calls this an anchor linker: seed on high-confidence detections, propagate forward and backward under a max-step constraint.
- Gap interpolation: bridge dropouts up to 5 frames with constant-velocity fill.
- **Bounce detection in image space**, from trajectory curvature — not in court space (ADR-009).
- **Auto-disable:** if recall over the first 2 minutes falls below 40%, log a warning, skip refinement, fall back to T1′ boundaries. Lighting was inadequate; the run must still produce output.

**Training** (rungs 2–3 only) runs on the RTX 2000 Ada workstation (16 GB VRAM) — preferred over cloud for iteration speed and zero cost. Use Docker `tensorflow/tensorflow:2.11.0-gpu` for TrackNet fine-tuning (pickleball weights require TF 2.11). Fallback: RunPod (~$0.10–0.30/run) or Kaggle P100 (30 h/week free). Export to ONNX (ADR-023); TensorRT export for Jetson must be done on the Jetson itself.

---

## 6. Segmentation

### 6.1 Mask inversion

Primary path (ADR-026). Inputs are the dead-time events from §5.2.1, not a continuous score.

```
1. dead[t] = OR of all dead-time events at t
2. Debounce: an event must persist N_persist samples to set dead[t]
             (occlusion and detection noise fire single-frame events)
3. Close small holes: dead runs shorter than min_dead_gap (default 1.0 s)
   are filled — a brief detection dropout is not a rally
4. rally[t] = NOT dead[t]
5. Discard rallies shorter than min_rally_duration (default 2.0 s)
6. Require >= 2 ball side-alternations if ball presence is available
   (courtesy-return suppression, §5.3.1)
```

Far fewer parameters than score thresholding, and each one has a physical meaning rather than being a tuned constant.

### 6.2 State machine — fallback path

Retained for the case where the §5.2.1 validation experiment fails and positive scoring is necessary after all. Replaces the unshippable conditions in ADR-010.

```
States: IDLE → ARMED → ACTIVE → COOLDOWN → IDLE

IDLE     → ARMED:     score(t) > enter_threshold
ARMED    → ACTIVE:    score sustained above enter_threshold for N_enter steps
                      (else → IDLE; kills single-event false positives)
ACTIVE   → COOLDOWN:  score < exit_threshold
COOLDOWN → ACTIVE:    score recovers above enter_threshold within N_cool steps
                      (rescues mid-rally dropouts instead of splitting the rally)
COOLDOWN → IDLE:      N_cool steps elapse → emit interval [start, last_active]
```

Requirements: `exit_threshold < enter_threshold` (hysteresis, mandatory); `N_enter`, `N_cool`, and both thresholds fit on `dev-set-B` only; discard intervals shorter than `min_rally_duration`.

### 6.3 Boundary refinement

Coarse sampling finds rallies; dense sampling places their edges. Video at 2 fps gives ~500 ms granularity, which makes the 1.0 s boundary target tight (ADR-028).

Re-run player detection at full frame rate in **±3 s windows around each boundary** — the same trick as ADR-015. About 40 rallies × 2 boundaries × 6 s × 15 fps ≈ 7,000 extra frames.

Where audio passed the usability gate, gated onsets (§5.1b) sharpen boundaries further, to tens of milliseconds.

### 6.4 Learned alternative

The eval labels are also training data: each labelled interval sampled at 5 Hz yields ~6,000 labelled timesteps per 20-minute set over a ~10-dimensional feature vector. Logistic regression or gradient boosting over that would likely beat hand-tuned weights, with **zero new image labelling**.

**Only valid with strict separation: fit on `dev-set-B`, evaluate on `eval-set-A`.** Fitting on the acceptance set turns recall into fiction. This is the trap ADR-016 exists to prevent, and it gets considerably easier to fall into once a model is involved. Treat as a Phase 2.5+ upgrade, never a starting point — an interpretable mask is debuggable, a fitted model is not.

---

## 7. Interval post-processing and selection

One detection pass feeds two renders; only selection differs (ADR-017).

### 7.1 Post-processing — order matters

1. **Pad:** `start -= pre_pad` (1.5 s), `end += post_pad` (2.0 s)
2. **Clamp** to `[0, duration]`
3. **Merge overlaps:** sort by start, merge where `next.start <= current.end`. **Mandatory** — without it, rallies less than 4 s apart produce overlapping clips and duplicated frames.
4. **Drop** intervals below `min_rally_duration`
5. **Emit** `rallies.json`

```json
{
  "source": "session-2026-07-30.mp4",
  "source_fps": 30.0,
  "tier_used": "T1",
  "rallies": [
    {
      "id": 1, "start": 14.53, "end": 28.21, "duration": 13.68,
      "n_impacts": 9, "peak_motion": 0.74,
      "score": 0.81, "selected": true
    }
  ]
}
```

Holds **every** detected rally; `selected` marks the reel. Nothing is discarded, so re-running selection with a different budget or weights never re-runs detection (ADR-018).

### 7.2 Ranking

**Superseded 2026-08-23 (ADR-063) — the features below (`n_impacts`, `peak_motion`) belonged to the pre-`ADR-046` player-signal design and were never produced by the TrackNet pipeline that replaced it.** Current implementation: `src/select.py`'s `rank_segments`, three hand-weighted features already produced by detection — still no model, no new labels, same spirit as the original ADR-019 decision, different feature set:

```
score = w_d · norm(duration) + w_p · norm(peak_crossing_rate) + w_s · norm(n_spikes)
```

- `duration` — the segment's raw length. Used directly, not as a rate denominator, so it's rewarded rather than fought.
- `peak_crossing_rate` — the highest net-crossings/sec in any 3-second sliding window inside the segment, **not** the segment's flat average rate. A flat average was tried first and found to *penalize* long rallies (correlation with duration: -0.53, on `brickwall-SEMI`) — a slower stretch anywhere in a long rally dilutes its average below a short rally's lucky burst. The peak-window version fixes that (correlation +0.82) by asking "was there a fast moment," not "was the whole thing fast."
- `n_spikes` — count of frame-to-frame ball speeds in the top decile observed anywhere in the source video, within the segment. Raw count, not a rate, so a longer rally gets more chances to earn credit rather than being penalized for length.
- Raw net-crossing *count* (uncorrected for duration or peak-vs-average) is explicitly excluded — `DECISIONS.md` ADR-054, confirmed by the 2026-08-21 TrackNetV3 reel it produced (over-selected kitchen-heavy dink exchanges).

Starting weights `1/3, 1/3, 1/3` (`config.yaml`'s `selection.weights`), chosen live against `brickwall-SEMI` playback, not yet checked against the `quality:1`/`quality:2` hand grades that exist for the four other scored videos. Revisit if that check turns up a problem.

### 7.3 Selection — greedy under budget

```
1. Sort by score, descending.
2. Take rallies while cumulative duration + next ≤ budget (default 600 s).
3. Skip-and-continue: if one doesn't fit, try the next — don't stop.
   Fills the budget more completely.
4. Enforce min_selected (default 12). If fewer fit, warn and relax to the
   12 highest-scored that fit.
5. Re-sort CHRONOLOGICALLY before rendering (ADR-020). Not optional.
```

Hard assert on rendered output duration ≤ budget; fail the run rather than emit a non-conforming file.

### 7.4 Config surface

| Flag | Default | Purpose |
|---|---|---|
| `--budget` | `600` | Hard ceiling on the reel, seconds |
| `--min-selected` | `12` | Floor on rally count |
| `--weights` | `0.4,0.4,0.2` | `w_d, w_i, w_m` |
| `--full` | `true` | Also emit `rallies_full.mp4` |
| `--mode` | `accurate` | Rendering path, §8 |

---

## 8. Rendering

**Seeking.** `-ss` before `-i` is fast but keyframe-aligned, and the C200's H.264 GOP can exceed 2 s — fast seeks drift by seconds, unacceptable against a 1.0 s boundary target. Two modes:

- **`accurate`** (default): single ffmpeg invocation, `trim`/`atrim` + `concat` filter graph, one encode pass. Frame-accurate.
- **`fast`**: build a keyframe-dense intermediate (`-g 15`) once, then stream-copy segments and join with the concat demuxer.

Use `h264_videotoolbox` for encoding — the M2's hardware encoder does 1080p at many times realtime.

**Do not use moviepy.** Slow and fragile at 200k-frame scale. ffmpeg directly, via `ffmpeg-python` or `subprocess`.

**Audio must carry through.** Impact sounds are most of what makes the cut watchable.

`--full=false` skips the second render, which is usually what you want — the complete cut is ~3× the encode time for a file that gets watched rarely.

---

## 9. Compute budget

Estimates from FLOPs-and-utilization arithmetic, **not measurement** (ADR-014). Phase 0 replaces this table with benchmarks. Per 2-hour session.

| Stage | Where | Estimate |
|---|---|---|
| Motion pre-filter (VideoToolbox decode) | Media engine + CPU | 4–7 min |
| **T1′ players @ 2 fps over the whole session** | ANE | **10–16 min** |
| Boundary refinement (±3 s windows, full rate) | ANE | +2–3 min |
| Segmentation + selection | CPU | seconds |
| Render 10-min reel | Media engine | 1–2 min |
| **Video-only pipeline** | | **~20–30 min → ~0.2× realtime** |
| Audio onsets (optional) | CPU | +2–4 min |
| Ball presence (optional) | ANE | +5–8 min |
| **Full pipeline** | | **~30–40 min → ~0.3× realtime** |

**v1 ball-net-crossing POC measurements (2026-08-12, MacBook Air M2):**

| Config | Per-frame | 13-min clip @ 10 fps |
|---|---|---|
| yolov8x @ imgsz=1280, PyTorch CPU | ~365 ms | ~70 min |
| yolov8x.mlpackage @ imgsz=1280, CoreML ANE | **~216 ms (1.7×)** | **~14–28 min** |

At 10 fps with CoreML, a 2-hour session takes ~260–520 min — well above realtime on the MacBook. This is why the N100+cloud shape (ADR-043) is the production direction; the MacBook is viable for POC iteration on short clips only.

Notes:

- **Player detection is now the dominant cost**, because it runs across the whole session rather than on candidates (ADR-028). The motion pre-filter clawing back 30–40% of frames is what keeps it affordable.
- **Fanless.** Sustained loads throttle; add 20–40% to any peak figure.
- **Decode is the other half of the budget.** Enabling hardware decode/encode matters far more than a faster GPU.
- **Sampling rate is the lever, and trajectory doesn't have one.** Motion, player position, and ball presence all subsample temporally because their signals are slowly varying. A 3-frame trajectory model needs every consecutive frame by construction — that structural fact, not model size, is why it is ~100× the cost, and why it is restricted to boundary windows (ADR-015). Dropping trajectory is what makes the ~0.2× figure reachable.
- **8 GB RAM:** stream frames through, accumulate only per-timestep scalars. Never hold frame arrays.
- **Storage:** ~6–8 GB per session round (source + intermediates + two renders). Clean up or keep sources on an external drive.
- **If a stage ever does need cloud GPU**, upload candidate segments only (~40% of the session), never the whole file (ADR-012). Cut and render locally from the original.

---

## 10. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR1 | Meet the wall-clock target in `PRD.md` §5 (currently ≤ 0.5× source duration). Single-sourced there — do not restate the number. |
| NFR2 | T0′ runs CPU-only, no GPU dependency |
| NFR3 | Idempotent and resumable — every stage writes `cache/{stage}/{content_hash}.json`; a killed run resumes from cache |
| NFR4 | Deterministic — same input + config + seed → byte-identical `rallies.json`. Non-negotiable for the eval loop to mean anything. |
| NFR5 | Peak GPU memory ≤ 8 GB, keeping free cloud tiers viable for training |
| NFR6 | Local-only storage by default; nothing retained in the cloud past a processing window |
| NFR7 | Single command: `python cut.py session.mp4 --budget 600` |
| NFR8 | Hard budget assert — `ffprobe` the render; fail if duration > budget |
| NFR9 | Structured logging to `run.log`: per-stage timings, detection rates, tier used, rallies detected/selected, budget used |

Deliberately absent (prototype scope, ADR-001): SLOs, alerting, retries with backoff, concurrency, model versioning. Single run, single user, fail loudly.

### 10.1 Portability

Two config keys, no hard-coded accelerators (ADR-023):

| Key | Apple Silicon | Windows | Linux/NVIDIA |
|---|---|---|---|
| `hwaccel` (ffmpeg decode) | `videotoolbox` | `d3d11va` | `cuda` |
| `encoder` | `h264_videotoolbox` | `h264_qsv` / `h264_nvenc` / `h264_amf` | `h264_nvenc` |
| `inference_backend` | CoreML → ANE | ONNX Runtime + DirectML, or OpenVINO | TensorRT / CUDA |

Models are trained anywhere and exported to **ONNX** as the canonical format; per-platform conversion is a deployment step, not a training decision. ~20 lines now versus a rewrite later. Everything else — ffmpeg, OpenCV, librosa, numpy, the state machine, selection — is already cross-platform.

### 10.2 Venue deployment (post-prototype sketch)

Not built now. Recorded so the shape is known if it happens (ADR-024, ADR-043).

**Preferred shape — N100 edge box + cloud GPU (ADR-043):**

```
N100 mini PC (~$150–300, on-site):
  capture full-res → encode 720p 2Mbps proxy (~90MB/hr)
  ── upload proxy only ──►
RunPod serverless GPU (~$0.34/hr):
  yolov8x detection → return timestamps JSON
  ◄── timestamps.json ──
N100:
  cut full-res local footage → assemble highlight
  ── push to S3 ──► LINE Messaging API delivery
```

The **proxy video trick** (ADR-043): upload 720p for detection (~90 MB/hr) instead of full-res (~750 MB/hr) — 8× upload reduction while keeping ball detectable. All cutting happens from the locally-held full-res copy.

**Correction (2026-08-26, twice-revised same day — see `DECISIONS.md` ADR-043 update for the full reasoning):** the "upload proxy only" arrow above (N100 → RunPod serverless direct) doesn't fit RunPod's real payload limits — 10MB (`/run`) / 20MB (`/runsync`) against a ~90MB/hr proxy, checked against RunPod's own docs. The fix is to land the chunk in storage first and pass the worker a reference — **two real options, both checked against primary docs:** RunPod's own Network Volume (platform feature, mounted at `/runpod-volume`, no external-provider integration — confirmed RunPod's S3-compatible gateway is scoped to its own storage only), or **Cloudflare R2, reached directly by the worker's own code via a standard S3 client** (`boto3` + `endpoint_url`/`region_name="auto"`, confirmed against Cloudflare's R2 docs) — this needs no RunPod-side integration since it's just outbound networking from inside the pod. R2 is the more attractive of the two here since the same account/pricing also covers the highlight-delivery leg to end users, which a RunPod Network Volume can't do. Not yet built.

**Alternative: all-local on Jetson Orin / Mac mini**

```
venue: capture + full pipeline on a dedicated edge box
   → render locally → push highlight to delivery channel
```

Viable if the venue has the compute (Jetson Orin NX can run yolov8x in real-time; Mac mini M-series is the zero-port option matching the prototype). No cloud GPU bill; fleet-management (OTA updates) is the main operational cost.

Constraints that apply to both shapes:

- **Bandwidth is the ceiling, not compute.** Full-res upload (~2.7 GB per 2-hour session) stops working at ~6+ courts on a typical venue uplink. The proxy trick pushes this to ~50+ courts on a 50 Mbps line.
- **Do not use the venue's PC.** Hardware is unknown and varied. A dedicated box removes the variable rather than routing around it.
- **Privacy:** raw footage stays on-site with both shapes. With the cloud shape, the proxy (lossy 720p, no faces identifiable at detection resolution) is the only thing leaving the building, plus timestamps. Still requires a data processing agreement and retention policy.
- Indoor venues largely rule out ball trajectory (ADR-002), so audio and player motion carry the product at indoor venues.

---

## 11. Evaluation harness

Metric definitions and targets live in `PRD.md` §5. This is the mechanism.

### 11.1 Datasets

| Set | Content | Labels | Use |
|---|---|---|---|
| `eval-set-A` | 20 min, daylight | Rally start/end only | Acceptance. **Locked — never tuned against.** |
| `dev-set-B` | 20 min, *different* session | Rally start/end only | All threshold and weight fitting |
| `eval-set-C` | 10 min, poor light | Rally start/end only | Graceful-degradation check |

Labeling a rally interval takes a few seconds in any editor. All three ≈ one hour (ADR-016).

### 11.2 Matching

Temporal IoU between predicted and labeled intervals:

```
IoU = overlap / (dur_pred + dur_gt - overlap)
```

Match at IoU ≥ 0.5, with **one-to-one assignment** — greedy by descending IoU. Without it, one prediction spanning two rallies could claim credit for both. Leftover labeled intervals are misses; leftover predictions are false positives.

### 11.3 Harness

`make eval` reads `rallies.json` (never rendered video) and prints both PRD tables. Detection metrics ignore `selected`; selection metrics read it.

Stand this up in Phase 0 against a hand-written `rallies.json` so the harness is proven before any detector exists.

### 11.4 Ball labels — only if Phase 3 is entered

- 800–1200 frames from daylight footage, sampled **from within rallies**. Uniform sampling across the session yields mostly dead-time frames with no ball in flight, and is highly redundant from a fixed camera.
- Consecutive frame **triplets**, since the model consumes 3 frames.
- Ball **center points**, not boxes — matches the heatmap formulation.

---

## 12. Repository layout

Actual layout as of 2026-08-21 — this section had drifted badly behind the
real repo (it still described the pre-pivot, player-signal design from
before ADR-046). Keep it in sync going forward: when a new top-level tool or
directory lands, update the tree below in the same change, not later.

```
pic-vision/
├── PRD.md                    # what and why
├── TECH_SPEC.md              # this file
├── DECISIONS.md              # decision log (ADRs, append-only)
├── STRATEGY.md               # post-prototype direction (exploratory)
├── EXPERIMENTS.md            # append-only run log
├── PROGRESS.md               # pointer to progress/ + standing reference material
├── progress/                 # plain-language status, one file per day (MM.DD progress overview.md)
├── CHECKLIST.md              # phase-gate tracker for Phase 0-1 only; Linear is
│                              # authoritative for anything after (see CLAUDE.md)
├── LABELING.md               # rally-labeling + highlight-worthy grading protocol
├── README.md                 # how to run
├── AGENTS.md                 # agent-facing pointers
├── requirements.txt          # Python dependencies
├── config.yaml               # thresholds and weights
├── Makefile                  # `make test` / `make eval` / `make process`
├── sessions.jsonl            # eval/dev session-role assignments (ADR-052)
│
├── calibrate.py               # 12-point court calibration, local X11 click UI
├── calibrate_web.py           # same, browser-click UI (for SSH/no-display)
├── label.py                   # rally interval labeller, local X11
├── label_web.py                # same, browser UI + GRADE mode (highlight-worthy pass)
├── webapp.py                    # web UI launcher: upload -> calibrate -> pipeline -> preview/download
│
├── webapp/                     # the web UI (Flask) -- purely additive, CLI tools above unaffected
│   ├── app.py                     # routes: home (choose local/cloud) -> upload -> calibrate ->
│   │                                # status polling -> preview/download; cloud route (2026-08-26)
│   │                                # picks a saved per-venue cloud_pipeline/venues/*/calib.json
│   │                                # instead of calibrating fresh
│   ├── pipeline.py                  # background job orchestration: run_job() (local, drift check ->
│   │                                  # CFR convert -> TrackNet inference -> build_reel) and
│   │                                  # run_cloud_job() (2026-08-26, same status.json/log.txt
│   │                                  # contract, dispatches to cloud_pipeline.run_cloud_job instead)
│   ├── templates/                     # Jinja2 pages (home/upload/cloud_upload/new_venue/
│   │                                     # calibrate/status/preview)
│   └── jobs/                           # runtime per-job data -- gitignored, regenerable
│
├── cloud_pipeline/              # R2 + RunPod path (2026-08-26), isolated from webapp/'s
│   │                              # local-GPU inference -- see cloud_pipeline/README.md.
│   │                              # webapp/app.py's cloud route calls into this one-way
│   │                              # (webapp -> cloud_pipeline); cloud_pipeline still never
│   │                              # imports webapp/, so its own CLI/isolation is unchanged
│   ├── run_cloud_job.py            # orchestrator: local drift+CFR -> R2 upload -> RunPod runs
│   │                                # pod_infer.py unmodified -> R2 -> local build_reel()
│   ├── r2_storage.py                 # thin boto3 wrapper for Cloudflare R2
│   ├── runpod_pod.py                  # RunPod pod lifecycle (create/SSH/exec/terminate)
│   ├── pod_r2_helper.py                # standalone script copied onto the pod for its R2 I/O
│   ├── setup_venue_calibration.py        # ONE-TIME per-venue calibration (not per-job --
│   │                                    # run_cloud_job.py has no calibration logic of its own)
│   └── jobs/                            # runtime per-job data -- gitignored, regenerable
│
├── src/                        # the production pipeline
│   ├── cut.py                    # entry point: `python3 -m src.cut` (see Makefile)
│   ├── tracknet.py                # TrackNet prediction parsing (RunPod GPU inference)
│   ├── calib.py                    # calibration geometry incl. court_wedge
│   ├── track.py                     # ball tracker (teleport/re-acquisition confirmation)
│   ├── ball.py                       # crossing_times / cluster_crossings / adaptive_gap_sec
│   ├── select.py                       # rally ranking for reel selection (§7.2)
│   ├── drift.py                       # camera-bump/creep detection
│   ├── players.py                      # player/court-position helpers
│   ├── events.py                        # motion_series / kitchen_series signals
│   └── render.py                         # clip rendering
│
├── scripts/                    # one-off analysis, diagnostics, parameter sweeps --
│                                # not part of the operator's core run-a-session flow
│   ├── pod_infer.py               # RunPod TrackNet inference driver -- calls the model via
│   │                                # a tf.function direct call, not .predict() (ADR-065)
│   ├── check_drift.py              # camera-drift CLI -- run before calibrating new footage
│   ├── fp_anatomy.py                # false-positive mechanism classifier + plots
│   ├── review_gaps.py                # gap-candidate review/merge tool
│   ├── make_review_reel.py            # cut a reel of flagged candidates for playback review
│   ├── compute_quality_signals.py      # feature extraction, feeds quality_dashboard.py
│   ├── quality_dashboard.py             # highlight-worthy signal-exploration dashboard
│   ├── rank_and_reel.py                  # ranks candidates (src/select.py) + cuts a reel
│   │                                      # in both chronological and rank order; its
│   │                                      # build_reel() is also called by webapp/pipeline.py
│   ├── rank_and_reel_split.py             # same, for a session whose calibration is only
│   │                                      # valid in pieces (e.g. IMG_7743's camera bump)
│   ├── validate_ranking.py                 # checks rank_segments' score against real
│   │                                      # quality:1/quality:2 grades (§7.2, ADR-063)
│   ├── search_margin_px.py               # dev-only margin_px sweep
│   └── search_wedge_shape.py              # dev-only court_wedge shape sweep
│
├── eval/
│   ├── harness.py               # IoU matching, detection + selection metrics (§11.3)
│   └── labels/                   # hand labels -- ground truth, committed
├── calib/                       # per-camera calibration JSON, committed (expensive to redo)
├── archive/                     # retired code and process, kept for reference, not maintained
├── docs/                        # misc planning docs
├── tests/                       # pytest suite
│
├── videos/                      # source/derived footage -- gitignored
├── clips/                       # cut rally clips + review reels -- gitignored
├── cache/                       # pipeline stage artifacts -- gitignored, regenerable
└── weights/                     # model weights not covered by the *.pt/*.h5 gitignore rules
```

---

## 13. Build order

Mirrors the PRD milestones. Each phase ends with a working artifact and a number from `make eval`.

| Phase | Work | Gate |
|---|---|---|
| **0** | Preflight, record 50 min, label 3 eval sets, `calibrate.py`, eval harness on a stub | Harness reports both tables |
| **0.5** | **Benchmark prior art** (ADR-021): run vinod-polinati against `eval-set-A`, score with our harness | A baseline number exists. Decides whether Phase 1 improves it or replaces it. |
| **0.6** | **Validate the inversion** (ADR-026): measure how often each dead-time event fires *during* a labelled rally | Net crossings and court exits near zero. **If they aren't, the inversion is unsound** — fall back to §6.2 positive scoring before building the segmenter. |
| **1** | `motion.py` + `players.py` + §5.2.1 events + `segment.py` + `select.py` + `render.py` | Watchable ≤10-min reel; recall and FP measured; subjective gate once |
| **1.5** | Boundary refinement windows (§6.3) | Boundary error ≤ 1.0 s |
| **2** | Ball presence (§5.3.1) + side-alternation + courtesy-return suppression | FP improves, recall doesn't regress — else revert |
| **2.5** | *(conditional)* Audio path (§5.1b) + usability gate + cross-modal gating | Only if the gate passes. Boundary error improves. |
| **3** | *(gated)* trajectory refinement (§5.3.2), climbing the ladder only as far as needed | Only if 1.5 and 2.5 both miss the boundary target |
| **3.5** | Weight sweep, subjective gate × 3 sessions | 2 of 3 pass; utilization ≥ 0.85; ≥ 12 rallies |
| **4** | Resumability, config surface, README | Re-runnable a month later without reading the code |

**Phase 0.6 is the new gate.** The whole detection design rests on dead-time events being clean; one hour of measurement confirms or kills it before any segmenter exists. Occlusion and detection noise are the likely failure mode.

**Phase 0.5 exists so we don't rebuild something that already works.** A day of work with two good outcomes; the harness result governs, not the README (ADR-021).

**Audio moved from Phase 1 to conditional Phase 2.5.** It is no longer load-bearing (ADR-004), so it can't block a working pipeline. There are now three independent routes to boundary precision — dense-sampling windows, ball side-alternation, gated audio — and the system needs none of them individually.
