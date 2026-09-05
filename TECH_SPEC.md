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
│   │                              # imports webapp/, so its own CLI/isolation is unchanged.
│   │                              # desktop/electron/pipeline.js (PIC-68, 2026-09-02) is a
│   │                              # second caller, one level up: it invokes
│   │                              # run_desktop_job.py, which imports webapp/pipeline.py's
│   │                              # run_cloud_job(job_dir)/cancel_job(job_dir) -- reusing
│   │                              # that job_dir/status.json/log.txt contract rather than
│   │                              # inventing a second one, so desktop/'s the only new
│   │                              # import direction (desktop -> webapp, still never
│   │                              # webapp -> desktop or cloud_pipeline -> either)
│   ├── run_cloud_job.py            # orchestrator: local drift+CFR -> 1080p proxy -> R2 upload
│   │                                # -> RunPod runs pod_infer.py unmodified, then pod_cut.py
│   │                                # (ADR-074, 2026-09-04) -> R2 upload of the finished reel(s).
│   │                                # predictions.csv never leaves the pod; only the finished
│   │                                # mp4(s) + a small stats.json come back (ranked only per
│   │                                # reel, no chronological version at all -- same-day
│   │                                # operator request, build_reel()'s include_chronological=
│   │                                # False). ADR-076 (same day): mints THREE uuids now, not
│   │                                # one -- reel_id (full), burst_reel_id, and share_id (the
│   │                                # public grouping id both reels are reported under, see
│   │                                # pod_cut.py/run_desktop_job.py below)
│   ├── pod_cut.py                     # ADR-074, extended ADR-076 (2026-09-04): runs ON the pod
│   │                                # right after inference -- thin wrapper around BOTH
│   │                                # scripts/rank_and_reel.py's build_reel() (full rally,
│   │                                # reel/full/) and scripts/burst_moment_reel.py's
│   │                                # build_burst_reel() (each rally's peak-intensity moment
│   │                                # only, "quick hits", reel/burst/, fixed 30s target --
│   │                                # burst clips are ~5s each, the caller's own --target-sec
│   │                                # is a full-reel number). stats.json is now
│   │                                # {"full": {...}, "burst": {...}|null} -- null when
│   │                                # burst's own candidate pool comes up empty. Deployed via a
│   │                                # small tarball (run_cloud_job.py's POD_REEL_DEPS) since
│   │                                # the pod has no other way to get src/'s modules
│   ├── run_desktop_job.py            # PIC-68: CLI wrapper for desktop/'s pipeline.js --
│   │                                # writes job.json then calls webapp.pipeline's
│   │                                # run_cloud_job(job_dir) on a background thread so a
│   │                                # SIGINT/SIGTERM from the Electron parent can call its
│   │                                # cancel_job(job_dir) (terminates any RunPod pod already
│   │                                # created, not just this process); on success, with
│   │                                # --console-url/--api-token (from cloud.js's stored
│   │                                # connection), _report_reels() (ADR-076, was _report_reel)
│   │                                # POSTs each finished reel (1 or 2) to the cloud console's
│   │                                # /api/agents/reels, all sharing one shareId -- best-effort
│   │                                # per reel, a failure doesn't fail the job, the reel
│   │                                # already exists in R2 either way
│   ├── r2_storage.py                 # thin boto3 wrapper for Cloudflare R2 (incl.
│   │                                    # generate_presigned_url, ADR-074)
│   ├── runpod_pod.py                  # RunPod pod lifecycle (create/SSH/exec/terminate)
│   ├── pod_r2_helper.py                # standalone script copied onto the pod for its R2 I/O
│   ├── setup_venue_calibration.py        # ONE-TIME per-venue calibration (not per-job --
│   │                                    # run_cloud_job.py has no calibration logic of its own)
│   ├── save_calibration.py               # 2026-09-03: computes+writes calib.json from 14
│   │                                    # clicked points against a snapshot image -- the
│   │                                    # desktop client's live-camera calibration flow
│   │                                    # (calibration.js) spawns this rather than
│   │                                    # reimplementing calibrate.py's homography fit in JS
│   └── jobs/                            # runtime per-job data -- gitignored, regenerable
│
├── desktop/                     # venue owner-facing local agent (2026-09-01,
│   │                              # STRATEGY.md §5; ADR-071 as of 2026-09-02) --
│   │                              # Electron + React, POC scope: camera discovery/
│   │                              # management, a per-camera weekly booked-session
│   │                              # schedule (config only, not wired to capture
│   │                              # yet), and -- as of 2026-09-02, PIC-66 -- real
│   │                              # manual recording (RTSP pull via ffmpeg,
│   │                              # capture.js) and -- as of 2026-09-02, PIC-68 --
│   │                              # a "send to cloud" trigger (pipeline.js) that
│   │                              # invokes cloud_pipeline/run_desktop_job.py as a
│   │                              # subprocess (concatenating capture.js's segments
│   │                              # first) rather than reimplementing R2 upload/
│   │                              # RunPod dispatch/reel-cutting in JS, per ADR-071.
│   │                              # Court calibration itself IS now built into the
│   │                              # client (2026-09-03, superseding PIC-68's original
│   │                              # "pass an existing calib.json path in" scope):
│   │                              # CalibrationControl (CameraDetailPage.jsx) takes a
│   │                              # live snapshot from the camera's own stream
│   │                              # (capture.js's grabSnapshot) and lets the operator
│   │                              # click the 12 court + 2 net points in the app --
│   │                              # calibration.js then spawns
│   │                              # cloud_pipeline/save_calibration.py (calibrate.py's
│   │                              # homography fit, not reimplemented in JS) to write
│   │                              # calib.json to that camera's own recordings folder
│   │                              # and record its path via store.js's setCalibPath.
│   │                              # The native file picker (system.js's pickCalibFile)
│   │                              # stays as a secondary "import an existing file"
│   │                              # option. Also 2026-09-03: ManualAddDialog
│   │                              # (CamerasPage.jsx) can add a "sample clip"
│   │                              # camera -- an uploaded local video file
│   │                              # (store.js's addCameraFromSampleClip) standing
│   │                              # in for a live one, so calibration/the cloud
│   │                              # pipeline can be exercised without a real,
│   │                              # court-facing camera (neither one on this
│   │                              # network has reliably been that). PIC-67's
│   │                              # CFR-encode NVIDIA-only gap is
│   │                              # still open (handled inside run_desktop_job.py's
│   │                              # call into the existing Python, not by desktop/
│   │                              # itself). CDN
│   │                              # delivery is NOT this app's scope -- ADR-071
│   │                              # moved it to the (also unbuilt) cloud web app.
│   │                              # Visual design (all 5
│   │                              # pages, "Nocturne" design system) implemented
│   │                              # from a Claude Design handoff bundle
│   │                              # (desktop-utility-by-claude-design.zip, repo
│   │                              # root) -- real backend wired only for the
│   │                              # Cameras page; Alerts/Credentials/Settings are
│   │                              # pixel-matched but illustrative. See
│   │                              # desktop/README.md.
│   ├── electron/
│   │   ├── main.js                  # frameless BrowserWindow (custom HTML title
│   │   │                              # bar, mockup-driven) + the ipcMain.handle
│   │   │                              # calls the renderer can reach
│   │   ├── preload.cjs                # contextBridge boundary -- .cjs, not .js
│   │   │                              # (Electron's preload loader ignores
│   │   │                              # package.json's "type": "module"; see
│   │   │                              # the file's own comment for how this was
│   │   │                              # found -- CDP against the real renderer,
│   │   │                              # not guessed)
│   │   ├── system.js                   # real local network CIDR (os.networkInterfaces)
│   │   │                              # for the sidebar's Network panel, plus (PIC-68)
│   │   │                              # pickCalibFile -- native file dialog, now the
│   │   │                              # secondary "import an existing calib.json" path
│   │   ├── calibration.js               # 2026-09-03: live-camera calibration --
│   │   │                              # takes a snapshot (capture.js's grabSnapshot),
│   │   │                              # spawns cloud_pipeline/save_calibration.py with
│   │   │                              # the renderer's 14 clicked points, records the
│   │   │                              # result via store.js's setCalibPath; the
│   │   │                              # homography fit itself stays in Python
│   │   │                              # (calibrate.py), per ADR-071
│   │   ├── pipeline.js                  # PIC-68: spawns cloud_pipeline/run_desktop_job.py
│   │   │                              # per recording, concatenating capture.js's
│   │   │                              # 10-min segments first (ffmpeg concat, stream
│   │   │                              # copy); polls/relays the same status.json
│   │   │                              # contract webapp/pipeline.py's dashboard route
│   │   │                              # already uses; cancel sends SIGINT, same
│   │   │                              # "never a hard kill" convention as capture.js;
│   │   │                              # passes cameraId/cameraLabel + the paired
│   │   │                              # agent's console-url/api-token (cloud.js's
│   │   │                              # getCloudConnection()) so run_desktop_job.py
│   │   │                              # can report the finished reel (ADR-074)
│   │   ├── capture.js                   # manual start/stop recording -- spawns
│   │   │                              # ffmpeg per TECH_SPEC §1.2's spec (RTSP pull,
│   │   │                              # -c copy, 10-min segments, wallclock
│   │   │                              # timestamps), .mkv not .mp4 (a real bug: the
│   │   │                              # spec's own .mp4 example silently fails on
│   │   │                              # pcm_alaw audio, which real cameras stream);
│   │   │                              # clean SIGINT stop only (ADR-031), incl. on
│   │   │                              # app quit; also (PIC-68) listRecordings,
│   │   │                              # scanning its own RECORDINGS_ROOT layout for
│   │   │                              # pipeline.js to list and send to the cloud;
│   │   │                              # also (2026-09-03) grabSnapshot -- one still
│   │   │                              # frame from the live stream for
│   │   │                              # calibration.js (`-frames:v 1` + a 10s
│   │   │                              # connect timeout; SIGKILL-safe, unlike
│   │   │                              # stopRecording, since there's no in-
│   │   │                              # progress container to corrupt); also
│   │   │                              # probeDuration/grabFrameFromFile, the
│   │   │                              # same for a "sample clip" camera (a
│   │   │                              # frame seeked out of its uploaded file
│   │   │                              # instead of a live pull); and
│   │   │                              # discardAllSnapshots, called from
│   │   │                              # main.js's before-quit so a snapshot
│   │   │                              # left over from a modal closed
│   │   │                              # mid-flow doesn't linger in /tmp
│   │   │                              # indefinitely -- real gap found the
│   │   │                              # same day, where one such leftover
│   │   │                              # was a live, private frame
│   │   ├── pythonBin.js                 # 2026-09-03: resolves .venv/bin/python3 if
│   │   │                              # present (falls back to bare "python3")
│   │   │                              # -- calibration.js/pipeline.js's spawned
│   │   │                              # subprocess previously used a bare
│   │   │                              # "python3", which silently resolved to
│   │   │                              # the system interpreter (no cv2/numpy)
│   │   │                              # when the app wasn't launched from a
│   │   │                              # shell that had activated the repo's
│   │   │                              # .venv -- root cause of a real "cannot
│   │   │                              # save calibration" report
│   │   ├── cloud.js                    # 2026-09-03: first outbound connectivity
│   │   │                              # to pic-vision-cloud-console (ADR-071) --
│   │   │                              # registerAgent (2026-09-05, ADR-079 --
│   │   │                              # takes the signed-in operator's own
│   │   │                              # access token, exchanges it for a
│   │   │                              # long-lived API token, electron-store;
│   │   │                              # replaced the original pairAgent/
│   │   │                              # pairing-code exchange the same day) +
│   │   │                              # a 30s heartbeat loop reporting online
│   │   │                              # status.
│   │   │                              # Same day: also reports the real camera
│   │   │                              # list -- cameraStatuses() runs
│   │   │                              # cameras/store.js's testConnection
│   │   │                              # against every configured camera in
│   │   │                              # parallel each tick (the same check
│   │   │                              # CamerasPage.jsx's own renderer-only
│   │   │                              # status check already does, just now
│   │   │                              # also from the main process on a
│   │   │                              # schedule). Sends label/connectionType/
│   │   │                              # manufacturer/model/status plus
│   │   │                              # (2026-09-03) firmwareVersion/
│   │   │                              # serialNumber/addedAt (identity, already
│   │   │                              # non-sensitive) and isRecording
│   │   │                              # (capture.js)/isCalibrated (derived
│   │   │                              # boolean from calibPath)/recordingCount/
│   │   │                              # lastRecordingAt (from listRecordings) --
│   │   │                              # never hostname/port/username/password/
│   │   │                              # streamUri, nor the raw calibPath/
│   │   │                              # sampleClipPath (local filesystem paths).
│   │   │                              # Court/reel data still doesn't cross this.
│   │   ├── auth.js                     # 2026-09-05: account sign-in (Supabase Auth
│   │   │                              # REST, same project as the console) --
│   │   │                              # signIn/signOut/getSession/getBrand, plus
│   │   │                              # registerDevice(), which calls cloud.js's
│   │   │                              # registerAgent() right after a successful
│   │   │                              # sign-in (ADR-079) -- there is no separate
│   │   │                              # pairing-code step anymore; signing in IS
│   │   │                              # what connects this device to the console.
│   │   └── cameras/
│   │       ├── discovery.js             # ONVIF WS-Discovery probe (`onvif` pkg);
│   │       │                              # filters by the responder's own declared
│   │       │                              # <wsd:Types> -- the library itself doesn't
│   │       │                              # (real false positives found+fixed 2026-09-01)
│   │       ├── networkSweep.js            # RTSP-port (554) subnet sweep + a real
│   │       │                              # RTSP OPTIONS handshake to confirm the
│   │       │                              # protocol, not just that the port is
│   │       │                              # open -- finds cameras that don't answer
│   │       │                              # WS-Discovery at all (a real one didn't)
│   │       ├── vendorLookup.js             # MAC (via ARP) -> manufacturer (IEEE OUI
│   │       │                              # registry, `oui-data` dep, no network
│   │       │                              # calls); generic, not vendor-curated
│   │       ├── rtspProbe.js                # confirms a real RTSP stream (DESCRIBE +
│   │       │                              # Digest auth, no ffmpeg dep) -- the
│   │       │                              # fallback for cameras whose ONVIF doesn't
│   │       │                              # work at all but a stream exists anyway
│   │       └── store.js                  # persisted camera list + connect/test,
│   │                                       # incl. an optional ONVIF path override
│   │                                       # and addCameraViaRtsp (the RTSP fallback),
│   │                                       # and setCalibPath -- a per-camera
│   │                                       # calib.json path, set either by
│   │                                       # calibration.js's live snapshot-and-click
│   │                                       # flow or the pickCalibFile import fallback,
│   │                                       # not computed here itself; also
│   │                                       # (2026-09-03) addCameraFromSampleClip --
│   │                                       # a "sample clip" camera (an uploaded
│   │                                       # video file, connectionType
│   │                                       # "sampleClip", no hostname/credentials)
│   │                                       # for exercising calibration/the cloud
│   │                                       # pipeline without a real camera
│   │                                       # (electron-store; POC stores camera
│   │                                       # passwords in plaintext, see README)
│   ├── scripts/
│   │   └── benchmark-decode.sh            # real N-camera decode/proxy-encode
│   │                                       # capacity test for target hardware
│   │                                       # (N100 etc.) -- checks real Intel
│   │                                       # GPU PCI vendor ID, refuses to run
│   │                                       # on non-Intel/no-iGPU machines
│   └── src/                          # React (Vite) renderer
│       ├── App.jsx                      # TitleBar + Sidebar + page switch
│       ├── index.css                     # "Nocturne" design tokens, ported from
│       │                                  # the handoff bundle's styles.css
│       ├── components/                    # TitleBar, Sidebar, CameraCard (WeekGrid/
│       │                                    # DayActivityStrip moved to the cloud
│       │                                    # console 2026-09-04, see below -- Schedule
│       │                                    # no longer lives here at all)
│       ├── pages/                          # CamerasPage (real -- ManualAddDialog's
│       │                                    # "Add" dropdown, 2026-09-03, offers "a
│       │                                    # live camera" or "a sample clip" --
│       │                                    # the latter uploads a local video file
│       │                                    # via cameraAPI.addSampleClip instead of
│       │                                    # connecting to anything), CameraDetailPage
│       │                                    # (real -- incl. a real Start/Stop
│       │                                    # recording control, capture.js, manual
│       │                                    # button only, not triggered by the cloud
│       │                                    # console's Schedule yet -- PIC-72, needs
│       │                                    # the cloud->agent command channel
│       │                                    # ADR-073 flagged as not yet built
│       │                                    # (hidden for a sample-clip camera, which
│       │                                    # has no live stream to record);
│       │                                    # plus, PIC-68, a "Cloud pipeline" panel --
│       │                                    # CalibrationControl (2026-09-03: live
│       │                                    # snapshot + click-14-points modal, calling
│       │                                    # calibration.js; a file-picker "import"
│       │                                    # fallback stays available) + a "Send to
│       │                                    # cloud" row per past recording, polling
│       │                                    # pipeline.js's job status). Schedule
│       │                                    # (ScheduleOverviewPage/ScheduleEditorPage)
│       │                                    # migrated to the cloud console entirely
│       │                                    # 2026-09-04 (ADR-071/PIC-73) -- removed
│       │                                    # from here, not kept in both places.
│       │                                    # Alerts/Credentials/Settings (mock data,
│       │                                    # illustrative), CloudPage (2026-09-03,
│       │                                    # real -- shows connection status +
│       │                                    # cloudAPI.register retry (ADR-079,
│       │                                    # 2026-09-05 -- registration itself
│       │                                    # now happens automatically right
│       │                                    # after sign-in, this page just
│       │                                    # reports the result), "Connected
│       │                                    # as <brand>" status, Disconnect,
│       │                                    # account email + Sign out),
│       │                                    # SignInPage (2026-09-05, real --
│       │                                    # gates App.jsx's whole render;
│       │                                    # mirrors pic-vision-cloud-console's
│       │                                    # own sign-in page's layout/copy)
│       ├── lib/cameraView.js                # real-camera -> mockup card/detail
│       │                                    # view-model (STATE_META, buildCards)
│       └── data/mockData.js                  # sample data for the 3 mock pages,
│                                              # ported verbatim from the handoff
│
├── pic-vision-cloud-console/     # ADR-071's "cloud web app" side, first real code
│   │                              # 2026-09-03 -- its OWN separate git repo (github.com/
│   │                              # tonychu805/pic-vision-cloud-console), just nested
│   │                              # here, not a submodule/subtree; `git status` at the
│   │                              # pic-vision root never sees its changes. Bootstrapped
│   │                              # via v0.app (Next.js App Router, Supabase for DB+
│   │                              # auth, hosted on Netlify not Vercel -- matches
│   │                              # picvisionai.com). public/claude-design.html is the
│   │                              # original static design mockup, still an iframe at
│   │                              # "/", untouched -- but every one of its screens
│   │                              # (Overview/Cameras/Courts/Reels/Members/Team/
│   │                              # Settings + sign-in) is now ALSO ported to a real
│   │                              # page below, pixel-matched against a live
│   │                              # screenshot of that mockup (Playwright, since no
│   │                              # browser-automation MCP tool was available). Only
│   │                              # Overview (agents/heartbeat data) and sign-in
│   │                              # (Supabase Auth) are wired to real data; Cameras/
│   │                              # Courts/Reels/Members/Team/most of Settings show
│   │                              # the mockup's own sample data verbatim
│   │                              # (lib/mockData.ts) -- operator's own scope call,
│   │                              # not something to assume is real without checking.
│   ├── app/
│   │   ├── globals.css                 # the "Nocturne" design system (same tokens
│   │   │                              # as desktop/src/index.css, confirmed
│   │   │                              # byte-identical to the mockup's own computed
│   │   │                              # styles) ported in as a `.nocturne`-scoped
│   │   │                              # addition -- doesn't touch the pre-existing
│   │   │                              # light --background/--foreground the "/"
│   │   │                              # mockup wrapper still uses
│   │   ├── sign-in/page.tsx            # Supabase Auth email/password, rebuilt to
│   │   │                              # match the mockup's split-screen design;
│   │   │                              # creates a venues row on first sign-in (1:1
│   │   │                              # owner:venue for now)
│   │   ├── (app)/                      # route group sharing one auth-gated shell
│   │   │   ├── layout.tsx                 # redirects to /sign-in if signed out;
│   │   │   │                             # fetches venue+agents once, passes to
│   │   │   │                             # AppShell (components/app/)
│   │   │   ├── overview/                  # REAL data: page.tsx (server fetch) +
│   │   │   │                             # overview-client.tsx (client, 10s poll) --
│   │   │   │                             # only shows stats with real data behind
│   │   │   │                             # them (agents online, cameras reporting
│   │   │   │                             # summed from heartbeat camera_count); the
│   │   │   │                             # mockup's "Reels delivered"/"Jobs in
│   │   │   │                             # flight" cards are left out rather than
│   │   │   │                             # faked
│   │   │   ├── cameras/                   # REAL as of 2026-09-03 (was mock) --
│   │   │   │                             # page.tsx (server fetch) + cameras-
│   │   │   │                             # client.tsx (10s poll), same split as
│   │   │   │                             # overview/. Table: label/status/
│   │   │   │                             # connection type/model/last synced.
│   │   │   │                             # Clicking a row opens a right-side
│   │   │   │                             # detail sheet (CameraDetailSheet,
│   │   │   │                             # matches public/claude-design.html's
│   │   │   │                             # "CAMERA DETAIL" panel layout) adding
│   │   │   │                             # serial number/firmware/calibration
│   │   │   │                             # state/recording state/recording
│   │   │   │                             # session count+last-started/paired
│   │   │   │                             # date -- all real `cameras` columns
│   │   │   │                             # as of this date, sourced from
│   │   │   │                             # cameras/store.js + capture.js via
│   │   │   │                             # cloud.js's heartbeat. Still no
│   │   │   │                             # Buffer/Queued/pipeline-stage -- none
│   │   │   │                             # of those correspond to any real
│   │   │   │                             # per-camera state yet, dropped rather
│   │   │   │                             # than faked. A Calibration column
│   │   │   │                             # too (2026-09-04) -- see below, Courts
│   │   │   │                             # was merged in here, not kept separate.
│   │   │   │                             # Detail sheet also gets a Start/Stop
│   │   │   │                             # recording button (ADR-077, 2026-09-05,
│   │   │   │                             # disabled for sampleClip cameras) --
│   │   │   │                             # posts to api/commands/route.ts, waits
│   │   │   │                             # for is_recording to flip on the next
│   │   │   │                             # heartbeat sync like every other field
│   │   │   │                             # here, no faster poll invented for it
│   │   │   ├── schedule/, schedule/[cameraId]/  # REAL as of 2026-09-04
│   │   │   │                             # (ADR-071/PIC-73 -- migrated wholesale
│   │   │   │                             # from desktop/, not rebuilt from
│   │   │   │                             # scratch). Overview lists every camera's
│   │   │   │                             # booked-session count + DayActivityStrip
│   │   │   │                             # (components/app/), links to the per-
│   │   │   │                             # camera editor (WeekGrid -- drag to book,
│   │   │   │                             # click a booked session to remove it).
│   │   │   │                             # lib/schedule.ts's createSession mirrors
│   │   │   │                             # desktop's old schedule.js subtractRange
│   │   │   │                             # exactly (overlap-safe: booking a new
│   │   │   │                             # range trims/splits any existing session
│   │   │   │                             # it overlaps). Runs client-side straight
│   │   │   │                             # against Supabase (schedule_sessions
│   │   │   │                             # table, RLS scoped to the venue owner --
│   │   │   │                             # select+insert+delete, unlike reels/
│   │   │   │                             # cameras' select-only policies, since this
│   │   │   │                             # is edited directly in the browser, not
│   │   │   │                             # agent-reported). Data/UI migration only --
│   │   │   │                             # not wired to actually trigger local
│   │   │   │                             # recording (PIC-72, needs the cloud->agent
│   │   │   │                             # command channel ADR-073 flagged as not
│   │   │   │                             # yet built)
│   │   │   ├── reels/                      # REAL as of 2026-09-04 (ADR-074, was
│   │   │   │                             # mock) -- queries the real `reels`
│   │   │   │                             # table (agent_id -> agents.venue_id,
│   │   │   │                             # same scoping as every other agent-
│   │   │   │                             # owned table). ADR-076 (same day):
│   │   │   │                             # rows are grouped by share_id into
│   │   │   │                             # one card per SESSION (a session can
│   │   │   │                             # have a "full" row and a "burst" row
│   │   │   │                             # now, both showing their own stats
│   │   │   │                             # on the card), one "Open reel page"
│   │   │   │                             # link per card
│   │   │   │                             # (share.picvisionai.com/r/[share_id],
│   │   │   │                             # not /api/reels/[id]/video directly --
│   │   │   │                             # see reel-page/ below, that's the
│   │   │   │                             # actual venue-goer-facing artifact).
│   │   │   │                             # No status filter (a reel row only
│   │   │   │                             # exists once its job
│   │   │   │                             # already finished, no partial state
│   │   │   │                             # to filter on) and no thumbnail (no
│   │   │   │                             # frame capture exists anywhere in
│   │   │   │                             # the pipeline) -- dropped rather than
│   │   │   │                             # faked, same as Courts/Cameras above.
│   │   │   │                             # Courts itself (real as of 09-04
│   │   │   │                             # morning, then merged into Cameras
│   │   │   │                             # that afternoon -- one camera is one
│   │   │   │                             # court in this system, a separate
│   │   │   │                             # page was redundant) no longer exists
│   │   │   ├── members/, team/             # still mock data (lib/mockData.ts),
│   │   │   │                             # disabled action buttons with a title
│   │   │   │                             # tooltip explaining why (same
│   │   │   │                             # PreviewBanner-style honesty
│   │   │   │                             # convention as desktop/'s mock pages)
│   │   │   └── settings/page.tsx          # mostly mock form fields, EXCEPT brand
│   │   │                                 # name/timezone (PATCH /api/brand) --
│   │   │                                 # the "Pairing code" tab that used to
│   │   │                                 # live under Desktop utility here is
│   │   │                                 # gone (ADR-079, 2026-09-05): a device
│   │   │                                 # registers itself automatically on
│   │   │                                 # sign-in now, nothing left to generate
│   │   └── api/agents/
│   │       ├── register/route.ts       # ADR-079 (2026-09-05) -- Bearer-token
│   │       │                          # authenticated, but the token is a raw
│   │       │                          # Supabase session access token (the
│   │       │                          # signed-in operator's own), not an
│   │       │                          # agent apiToken; find-or-creates this
│   │       │                          # device's own agents row (by deviceId)
│   │       │                          # under that account's brand and returns
│   │       │                          # a long-lived API token (hash stored
│   │       │                          # only). Replaced pairing-code/route.ts
│   │       │                          # + pair/route.ts, both deleted.
│   │       ├── heartbeat/route.ts        # Bearer-token authenticated -- updates
│   │       │                            # status/camera_count/last_seen_at; as of
│   │       │                            # 2026-09-03 also upserts a `cameras` array
│   │       │                            # if the desktop agent sent one (label/
│   │       │                            # connectionType/manufacturer/model/status/
│   │       │                            # firmwareVersion/serialNumber/addedAt/
│   │       │                            # isRecording/isCalibrated/recordingCount/
│   │       │                            # lastRecordingAt -- hostname/port/
│   │       │                            # username/password/streamUri never leave
│   │       │                            # the agent) into public.cameras, then
│   │       │                            # deletes whatever's NOT in that payload
│   │       │                            # anymore (handles a removed camera, or
│   │       │                            # the whole list going empty)
│   │       └── reels/route.ts             # ADR-074, extended ADR-076, 2026-09-04.
│   │                                    # Bearer-token authenticated, same pattern
│   │                                    # as heartbeat -- cloud_pipeline/
│   │                                    # run_desktop_job.py's _report_reels()
│   │                                    # posts here once PER REEL after a cloud
│   │                                    # job finishes (1 or 2 calls, not polled).
│   │                                    # Inserts one `reels` row (agent_id from
│   │                                    # the token, camera_id/cameraLabel/
│   │                                    # sessionId/bucket/rankedKey/duration/
│   │                                    # rallyCount from the body -- ranked only,
│   │                                    # no chronologicalKey field). kind
│   │                                    # ('full'/'burst') and shareId now also
│   │                                    # accepted -- shareId falls back to this
│   │                                    # reel's own id (resolved server-side, not
│   │                                    # left to a Postgres default) when
│   │                                    # omitted, so an older caller or a
│   │                                    # burst-less session still gets a working
│   │                                    # single-reel share page at its own id
│   │       ├── commands/route.ts            # ADR-077 (2026-09-05), Bearer-token --
│   │       │                             # GET returns an agent's pending
│   │       │                             # agent_commands rows; the desktop
│   │       │                             # agent's heartbeat loop polls this on
│   │       │                             # its own existing ~30s cadence, no new
│   │       │                             # timer/connection
│   │       └── commands/[id]/route.ts        # ADR-077, Bearer-token -- the agent
│   │                                     # reports a command's done/error result
│   │                                     # here right after executing it locally
│   ├── api/commands/route.ts               # ADR-077 (2026-09-05), venue-owner
│   │                                    # session -- first real cloud->agent
│   │                                    # command (the gap ADR-071/ADR-073 both
│   │                                    # flagged as missing). Cameras page's
│   │                                    # Start/Stop recording button POSTs here;
│   │                                    # only inserts an agent_commands row,
│   │                                    # never runs anything itself -- recording
│   │                                    # (ffmpeg pulling RTSP) still has to
│   │                                    # execute wherever the camera actually is
│   ├── api/reels/[id]/video/route.ts       # ADR-074. Redirects to a stable
│   │                                    # cdn.picvisionai.com R2 URL (lib/r2.ts,
│   │                                    # ADR-075 -- no presigning) for the
│   │                                    # reel's one video (ranked -- no
│   │                                    # [which] segment, 2026-09-04) --
│   │                                    # user-session Supabase client, not
│   │                                    # admin, so `reels`' own RLS policy
│   │                                    # is the actual access boundary
│   ├── components/app/                 # Sidebar (nav groups matching the mockup,
│   │   │                              # real collapse toggle), TopBar (title +
│   │   │                              # real Sign out), AlertBanner (REAL --
│   │   │                              # renders only when an actual agent has
│   │   │                              # gone stale, unlike the mockup's
│   │   │                              # always-on fake "CAM-05 offline" banner),
│   │   │                              # AppShell (client, wires the three above +
│   │   │                              # usePathname()-derived page title),
│   │   │                              # PageHeader, Pill (tone from
│   │   │                              # lib/pillTone.ts), StatCard, WeekGrid +
│   │   │                              # DayActivityStrip (2026-09-04, ported
│   │   │                              # from desktop/src/components/ -- see
│   │   │                              # app/(app)/schedule/)
│   ├── lib/
│   │   ├── supabase/{client,server,admin}.ts  # browser (RLS), server-session (RLS),
│   │   │                                    # and service-role (bypasses RLS -- only
│   │   │                                    # for heartbeat/reels/commands routes,
│   │   │                                    # which authenticate via api_token_hash,
│   │   │                                    # not a Supabase session)
│   │   ├── supabase/bearer.ts                 # 2026-09-05 (ADR-079) -- RLS-scoped
│   │   │                                    # client for a raw Supabase access
│   │   │                                    # token arriving as a bearer header
│   │   │                                    # instead of a cookie session; used
│   │   │                                    # only by api/agents/register (the
│   │   │                                    # desktop agent's own sign-in session)
│   │   ├── agentToken.ts                     # API-token generation/hashing, shared
│   │   │                                    # by register.ts/heartbeat.ts (the
│   │   │                                    # pairing-code generator that used to
│   │   │                                    # live here was removed with ADR-079)
│   │   ├── r2.ts                              # ADR-074, 2026-09-04; rewritten same
│   │   │                                    # day for ADR-075. reelVideoUrl(bucket,
│   │   │                                    # key) -> stable cdn.picvisionai.com
│   │   │                                    # URL -- no signing, no SDK client,
│   │   │                                    # no CLOUDFLARE_R2_* credentials
│   │   │                                    # needed here anymore (the presigned-
│   │   │                                    # URL version this replaced did)
│   │   ├── schedule.ts                        # ADR-071/PIC-73, 2026-09-04. Client-side
│   │   │                                    # CRUD against schedule_sessions --
│   │   │                                    # createSession's overlap-trim logic
│   │   │                                    # ported from desktop/electron/schedule.js's
│   │   │                                    # subtractRange. Runs straight from the
│   │   │                                    # browser (not an API route) since RLS is
│   │   │                                    # the access boundary and this is the
│   │   │                                    # venue owner editing their own data
│   │   ├── mockData.ts                        # sample data for the not-yet-real
│   │   │                                    # sections, ported verbatim from the
│   │   │                                    # mockup's own content, not invented
│   │   └── pillTone.ts                         # maps a mockup status label (e.g.
│   │                                          # "Offline"/"Uploading"/"Enabled") to
│   │                                          # Pill's neutral/progress/alert tone
│   ├── netlify.toml                    # Next.js Runtime plugin -- v0.app's own
│   │                                  # auto-deploy-on-merge is Vercel-only, doesn't
│   │                                  # apply here. Live 2026-09-04 at
│   │                                  # console.picvisionai.com (Netlify CLI --
│   │                                  # site created/deployed/env vars set from
│   │                                  # here, no dashboard needed; custom domain
│   │                                  # set via the Netlify API, DNS CNAME added
│   │                                  # by hand in Cloudflare since no Netlify MCP
│   │                                  # tool exists to drive that piece either)
│   └── .env.local.example              # NEXT_PUBLIC_SUPABASE_URL/ANON_KEY pre-filled
│                                      # (from the provisioned project); SUPABASE_
│                                      # SERVICE_ROLE_KEY deliberately blank -- has to
│                                      # be pulled from the Supabase dashboard by hand
│
├── reel-page/                    # Public share page a venue-goer gets once their
│   │                              # highlight is ready (ADR-074's "watch my clips"
│   │                              # promise's actual delivery surface) -- its OWN
│   │                              # separate git repo, same reasoning as
│   │                              # pic-vision-cloud-console/: different domain
│   │                              # (share.picvisionai.com), different audience
│   │                              # (public, unauthenticated venue-goers, not venue
│   │                              # owners). Received 2026-09-04 via Taildrop as a
│   │                              # v0.app mockup the operator built, wired to real
│   │                              # data the same day, live on Netlify same day too.
│   ├── netlify.toml                 # same minimal config as the console's -- Next.js
│   │                              # Runtime plugin handles the app/r/[shareId] dynamic
│   │                              # route as a Netlify Function automatically
│   ├── app/r/[shareId]/page.tsx      # server component -- ADR-076 (2026-09-04):
│   │                              # renamed from [reelId] -- one page per SESSION
│   │                              # now, not per reel, since a session can produce
│   │                              # two reels (full + burst-moments/"quick hits").
│   │                              # Fetches every `reels` row sharing this share_id
│   │                              # (up to 2, oldest-first) via the "anyone with the
│   │                              # id can read" RLS policy (public, no session --
│   │                              # unguessable-UUID access, same pattern as Notion/
│   │                              # Figma/Loom links; share_id is a THIRD id, not
│   │                              # session_id -- that's built from camera label +
│   │                              # recording timestamp, guessable, unsafe as a
│   │                              # public gate), builds each one's stable CDN video
│   │                              # URL server-side (lib/r2.ts, ADR-075 -- no
│   │                              # presigning), 404s when none match
│   ├── app/r/[shareId]/reel-share-client.tsx  # the real interactive page. Hero is a
│   │   │                          # horizontal scroll-snap carousel (ADR-076) when
│   │   │                          # 2 reels exist -- one slide per reel, badge
│   │   │                          # ("Full reel"/"Quick hits"), dot indicators, an
│   │   │                          # IntersectionObserver-driven activeIndex. Every
│   │   │                          # slide's video is prefetched into a Blob on
│   │   │                          # mount (not lazily per-slide -- would reintroduce
│   │   │                          # the exact awaited-fetch-mid-gesture bug fixed
│   │   │                          # the same day) so navigator.share() can fire
│   │   │                          # synchronously off the tap. Instagram/TikTok/
│   │   │                          # Download retarget to the active slide; Copy
│   │   │                          # link and the link-based tiles below don't (one
│   │   │                          # page URL regardless of slide). Download all
│   │   │                          # (ADR-076, after Copy link) shares every slide's
│   │   │                          # video via one multi-file navigator.share() call,
│   │   │                          # falling back to sequential plain downloads. The
│   │   │                          # "Repost it"/"Send to" tiles split into two
│   │   │                          # genuinely different mechanisms, decided after
│   │   │                          # verifying against Meta's own developer docs
│   │   │                          # (not assumed): Facebook/X/WhatsApp/LINE/SMS have
│   │   │                          # real web share-intent URLs (plain links, filled
│   │   │                          # in with the real share URL); Instagram/TikTok do
│   │   │                          # NOT -- Meta's real "Sharing to Reels/Stories" API
│   │   │                          # passes content via native UIPasteboard keys
│   │   │                          # (`com.instagram.sharedSticker.*`) that only
│   │   │                          # compiled native app code can write, confirmed
│   │   │                          # directly from developers.facebook.com, not
│   │   │                          # assumed -- no browser, on any platform, can do
│   │   │                          # this. Built instead: `navigator.share()` with the
│   │   │                          # actual video attached as a File (surfaces "Save
│   │   │                          # Video" in the OS's own native share sheet), then
│   │   │                          # best-effort opens the app right after -- one
│   │   │                          # extra tap instead of zero, everything else
│   │   │                          # automatic. Needs R2 bucket CORS (set 2026-09-04)
│   │   │                          # since attaching a File means fetching the bytes
│   │   │                          # first, not just linking to them
│   ├── lib/supabase.ts              # public anon-key client, no session/cookie
│   │                              # handling at all (unlike the console's
│   │                              # lib/supabase/{client,server}.ts) -- this page has
│   │                              # no logged-in user, ever
│   └── lib/r2.ts                     # reelVideoUrl(bucket, key) -> stable
│                                    # cdn.picvisionai.com URL (ADR-075, no signing/
│                                    # expiry) -- same helper as the console's, copied
│                                    # not imported (genuinely separate deployable app)
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
│   ├── render.py                         # clip rendering
│   └── job_log.py                         # shared timestamped log.txt writer -- used by both
│                                            # webapp/pipeline.py and cloud_pipeline/run_cloud_job.py
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
│   ├── burst_moment_reel.py               # ADR-076 (2026-09-04): cuts just each top-ranked
│   │                                      # rally's own peak-intensity window (src/select.py's
│   │                                      # peak_window), not the whole rally -- "quick hits".
│   │                                      # Was dev-only until this ADR; build_burst_reel() is
│   │                                      # now also called by cloud_pipeline/pod_cut.py
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
