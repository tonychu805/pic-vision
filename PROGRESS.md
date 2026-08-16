# Progress Log

Plain-language record of what's been built and decided, newest first. Git history has the detail; this is the map. Metric-producing runs go in [`EXPERIMENTS.md`](./EXPERIMENTS.md); decisions in [`DECISIONS.md`](./DECISIONS.md).

## Phase gate tracker → [`CHECKLIST.md`](./CHECKLIST.md)

## ▶ NEXT SESSION — start here

**Status (2026-08-16): the clean-footage gate is CLEARED and the project has its first trustworthy numbers.** The old blocker ("capture one clean fixed-mount clip") is done — IMG_7743 is labelled, scored, and the detector has been measurably improved against those labels.

**Where the numbers stand** (33 hand labels on IMG_7743, IoU≥0.3, k14 pickleball weights):

| | precision | recall | segments |
|---|---|---|---|
| what shipped this morning | 0.10 | 0.61 (20/33) | 201 |
| what ships now (capped trapezoid, `min_crossings=6`) | **0.29** | **0.61 (20/33)** | **69** |

**The one thing to work on next: recall is stuck at 20/33 under every gate shape, every threshold, masked or unmasked.** The 13 missed rallies are missed because the ball is barely detected during them at all — a detection failure, not a gating one. Nobody has looked at them yet. Do what cracked the false-positive question: render those windows with detections drawn on and *look*. Occlusion, motion blur, and ball-vs-floor contrast each imply a different fix.

**Runnable now (all local — no RunPod needed; the RTX 2000 Ada does ~58 fps, faster than real time):**
1. Inference env: `/mnt/fast_scratch/tf215_env/venv` (TF 2.15), weights at `/mnt/fast_scratch/tracknet_weights/weights_k14_epoch19`. Export `LD_LIBRARY_PATH` to the venv's `nvidia/*/lib` dirs first.
2. `python3 scripts/pod_infer.py --video game.mp4 --output predictions.csv` (do NOT pass `--calib`: masking before inference measured worse, see EXPERIMENTS)
3. Score any change in seconds: `predictions.csv` → `rally_segments_from_predictions(..., in_court=court_wedge(calib), min_crossings=6)` → `eval/harness.py` vs `eval/labels/IMG_7743.jsonl`

**Two traps that cost time today, both now guarded:**
- **Source `.MOV` files are corrupt.** IMG_7743/7744 have localized HEVC damage that makes OpenCV stop decoding *silently* — a full run returned 930 of 121,013 frames with exit code 0. Use the repaired `videos/*_fixed.mp4`; `pod_infer.py` now aborts below 98% of expected frames.
- **A calibration without `net_image_points` gives a biased net line**, ~130px too low (it returns the net's base, not its tape). IMG_7652 has this; `net_line_y` now warns. Any past IMG_7652 crossing result is suspect.

**Labelling is now browser-based** (`label_web.py`) because the workstation is driven over SSH — X11 forwarding ships raw frames and is unusable for video. Two passes: mark every rally with `s`/`e` (no judgement), then `g` to grade each one with hindsight (`1` highlight / `2` ordinary / `3` not a rally). Grade ordinary play as `2` rather than deleting it, or the detector gets charged for correctly finding real play.

**Known-unproven:** the trapezoid gate's shape adapts to any camera via calibration, but its height cap is a fraction of court *image* height and silently disables itself on a higher mount (lands off-frame on IMG_7652). Redefine it in real ball height — the marked net tape is a free ruler (~100 px/m on 7743). Cross-camera generalisation is untested: IMG_7744 has a calibration but no labels; IMG_7655 has 36 labels but no calibration (calibrating it is the cheapest real test).

## Benchmark cases (real-footage pass/fail targets)

Concrete windows from the compromised clips, human-verified, to check any detector change against. Net line was hand-measured per window (the camera zooms — no single line holds); a clean fixed clip will replace these with one calibration. Scores below are current v1 (yolov8x + size filter + correct net line).

| Window | Type | Verified | Current crossings | Target |
|---|---|---|---|---|
| IMG_7652 58–77.5s (net y=260) | RALLY | yes (play dead at end) | 33 | high ✅ |
| IMG_7652 620–638s (net y=170) | RALLY | yes | 12 | high ✅ |
| IMG_7655 86–101s (net y=210) | RALLY | yes | 20 | high ✅ |
| **IMG_7652 659–666s (net y=160)** | **DEAD** | **yes (not a rally)** | **0 (tracked) ✅** | **~0 ✅** |

**The 659–666s dead-time regression now PASSES (2026-08-11, EXPERIMENTS).** With the tracker wired in (`src/pipeline.py`), tracked crossings drop to **0** on this window (naive best-per-frame was 22), while the 58–77.5s rally keeps **16** — the tracker suppresses phantom crossings without erasing the rally signal. Note the RALLY-row crossing counts above are from the pre-tracker naive path; tracked counts are lower (rally 58–77.5s: 36 naive → 16 tracked) but still cleanly separated from dead-time's 0.

## Status at a glance

- **Built + tested (57 tests):** eval harness · calibration (order-independent, **now marks the net**) · player detection front-end (`src/players.py`, `src/events.py`) · **v1 ball detector + net-crossing counter + auto-annotator** (`src/ball.py`: `detect_ball` yolov8x + size filter, `detect_candidates`, `net_line_y`, `crossing_times`, `cluster_crossings`) · gap-tolerant `segment.py` · **single-ball spatial tracker** (`src/track.py`: `track_ball`, teleport-rejection, auto-reset) · **v1 rally pipeline** (`src/pipeline.py`: `rally_segments_from_candidates`, `detect_rallies` — chains detect→track→crossing→cluster, validated on real footage) · **cut module** (`src/render.py`: `cut_clips`, H.264 + manifest) · **end-to-end orchestrator** (`src/cut.py`: `cut_rallies` + CLI — footage→clips in one pass, `gap_sec=3.0`/`max_jump=150` as validated defaults) · scoring against labels.
- **Not built (Phase 1, after the gate):** selection/ranking (competitive vs casual). All detection→segment→cut wiring is now complete (`pipeline.py` + `cut.py`).
- **Decided:** ADR-035 (order-independent calibration), ADR-036 (court coords; calibration absorbs pose not occlusion), ADR-037 (two-sided live/stopped markers), LABELING.md v2, prior art assessed (beat, don't adopt — EXPERIMENTS.md).
- **Capture:** wifi/RTSP (tested, ~90–96% delivery, bursty drops; PTS handles drops). microSD skipped.
- `main` pushed to `origin`. v1 pipeline work on branch `feat/rally-pipeline`.

---

## 2026-08-12 — TrackNet-Pickleball on RunPod RTX 3090: 25 crossings vs YOLO's 5

- **RunPod experiment** to test whether AndrewDettor's TrackNet-Pickleball (3-frame heatmap) outperforms yolov8x for net-crossing detection. RTX 3090, $0.22/hr.
- **Result: 25 crossings** in rally #3 window (58–77.5s) vs **YOLO's 5**, using old badminton-trained weights (pickleball fine-tuned weights couldn't load: TF 2.21 Keras 3 broke legacy TF 2.11 SavedModel format). Clustering at gap=2s gives ~4 distinct events. Full numbers in EXPERIMENTS.md.
- **Key finding:** the 3-frame heatmap architecture sees the ball across the net on footage where YOLO largely misses it. Even with mismatched badminton weights, 5× more crossing evidence.
- **Key caveat:** dead-time FP rate not yet measured for TrackNet (only ran the rally window). 54.5% detection rate is higher than expected — likely some false positives from domain-mismatched badminton model.
- **Follow-up items:** (1) Load pickleball fine-tuned weights with TF 2.13 + Python 3.10 or by re-exporting to `.keras`. (2) Run dead-time segment (659–666s) through TrackNet to confirm FP rate. (3) TrackNet is CUDA-only so the production deployment on Mac mini/N100 still uses yolov8x; TrackNet is the cloud-GPU inference path (ADR-043).

## 2026-08-12 — CoreML acceleration + false-positive root cause + cloud architecture

- **Root cause of "players walking, no ball" clips:** `max_ball_px` was not set → YOLO `sports ball` class latched onto player bodies (heads/torsos = 30–60 px) instead of the ball (10–21 px). Fixed by `--max-ball-px 25`. Also raised `--conf` to 0.25 (from 0.10) to cut the worst player-body hits before the size filter. This was the primary false-positive source for all earlier bad clips (ADR-045).
- **CoreML export:** `yolov8x.mlpackage` (imgsz=1280, 130.5 MB) exported and validated — 216 ms/frame ANE vs 365 ms/frame CPU = **1.7× faster** (ADR-044). Lives in project root. Use `--weights yolov8x.mlpackage`.
- **Best working params (13-min handheld IMG_7652.MOV, 10 fps scan):** `--conf 0.25 --max-ball-px 25 --band 10 --max-jump 100 --gap-sec 2.0 --sample-fps 10 --weights yolov8x.mlpackage`. Found 3 candidates: 00:05 (3 crossings), 01:06 (4 crossings), 02:33 (3 crossings). 02:33 confirmed false positive (camera pan); 00:05 and 01:06 candidates, user verification pending.
- **New diagnostic scripts:** `scripts/scan_crossings.py` (fast scan, prints crossing clusters without cutting) and `scripts/debug_detections.py` (renders annotated JPEG frames with YOLO boxes + net_y overlaid — red=NEAR, blue=FAR side).
- **`pad_sec=3.0` added to `cut_clips`** — clips were 3.8s and 0.6s (unusable) without it. Fixed by adding pre/post padding. Wired through `src/render.py` and `src/cut.py` with `--pad-sec` CLI arg.
- **Cloud-hybrid architecture discussed** (ADR-043): N100 mini PC + RunPod serverless GPU. Proxy video trick: send 720p 2Mbps (~90 MB/hr) for detection instead of full-res (~750 MB/hr). N100 cuts from full-res local footage using returned timestamps. LINE Messaging API for delivery. Local POC continues on MacBook with CoreML; N100+cloud is the production direction.
- **`clips_v2/`** (5 fps scan): rally_01 + rally_02 are real; rally_03 (04:30) is camera-pan false positive suppressed by `--band 10 --max-jump 100`. **`clips_v3/`** (10 fps, best params): 3 clips produced; user verification in progress.

## 2026-08-11 — Wired the v1 pipeline; tracker validated on real footage

- **Found the gap:** `track_ball`/`detect_candidates` were called only from tests — no runnable path from video → segments through the tracker, and a shape mismatch (`detect_candidates` pairs times, `track_ball` drops them, `crossing_times` needs them back). So PROGRESS's "tracker fixes dead time" was an **unvalidated assumption** — the tracker had never been run on the 659–666s benchmark that motivated it.
- **Shipped `src/pipeline.py`** (branch `feat/rally-pipeline`): `rally_segments_from_candidates` (pure) + `detect_rallies` (video), chaining detect→track→crossing→cluster. TDD, 2 new tests (smooth rally; phantom-crossing rejection). 55 tests.
- **Validated on IMG_7652** (compromised footage, per-window measured net line): dead-time 659–666s **22 → 0** tracked crossings; rally 58–77.5s keeps **16** (naive 36). End-to-end with `gap_sec=3s`: rally → 1 segment, dead time → 0. Clean separation — the v1 mechanism works on real footage for the first time. Full run in EXPERIMENTS.md.
- **Two recipe findings:** `max_jump` 100–200 safe (300 starts dropping real crossings); **`gap_sec=1.0` too tight** (crossings up to ~2s apart) → use ~3s.
- **Still the gate:** one rally + one dead window on zoomed footage validates the mechanism, not a benchmark number. Clean fixed footage remains required for a real recall/FP measurement and non-overfit tuning.

## 2026-08-10 — Diagnosed v1 on real footage; ball recipe + net marking

- **Watched v1's segments — they aren't real rallies, even where they "matched" labels.** Overlaid ball boxes + net line on a labeled rally: two bugs, both visual — (1) the derived **net line sits below the actual net** (calibration made on a differently-zoomed frame), (2) the **nano model tags heads/bodies as "ball."** So the 9/9 recall was hollow (coincidental overlap of noisy crossings). Detail + frames in EXPERIMENTS.md.
- **Fix 1 — bigger model.** yolov8x finds the *real* ball (0.91 on a mid-court ball) and pushes junk to low confidence — BUT the ball *at the net* (small, far from a behind-baseline camera) scores only 0.2–0.3. **The crossing moment is the hardest detection from this angle.** Confidence alone won't do it; needs the size filter + a tracker (TrackNet-style) for the far ball, and/or a better camera angle/resolution.
- **Shipped (branch `feat/ball-recipe`):** `detect_ball` defaults to **yolov8x** + tested `ball_box_ok` size filter; `calibrate.py` now **marks the net** (2 clicks) and `net_line_y` prefers it over the derived line. 47 tests. All build-ready but **unvalidated until clean footage** (can't tune the size threshold or trust the net line on zoomed clips).
- **Capture routine change:** clean-footage calibration is now **12 court points + 2 net-tape clicks**.

## 2026-08-09 — v1 auto-annotator runs on full 7652

- Built the **raw-footage auto-annotator** (`src/ball.py`: `crossing_times` + `cluster_crossings`, `sample_fps` on `detect_ball`; 9 ball tests). This is the v1 detector end-to-end: point it at a raw clip → cluster dense crossing-bursts → emit rally segments.
- **Full 7652 run (10 fps, compromised footage):** covered **9/9 labeled rallies (100% recall)**, proposed **96** total (78 "spurious"). But 10 of those "spurious" have ≥10 crossings = real sustained play not in the curated competitive-9; ~31 are ≤3-crossing noise. So the crossing signal is real; the 81% spurious rate is confounded by competitive-only labels + zoom noise. Detail in EXPERIMENTS.md.
- **Takeaway:** the "find rallies" step works (catches everything). What's missing is a **ranking layer** (competitive vs casual — needs rally length/intensity, not crossings alone) and the render/cut back half. Still not validated (compromised footage).

## 2026-08-09 — v1 net-crossing core built + smoke test

- Built the v1 rally-signal core (`src/ball.py`, merged): `count_crossings` (image-space net-crossing counter w/ hysteresis, 4 tests), `net_image_y` (net line from calibration, 1 test), `detect_ball` (dense per-frame sports-ball detector). 38 tests total.
- **Smoke test on IMG_7652 (compromised footage):** ball detectable (85% of rally frames), and crossing count **discriminates the right way** — longest rally 22 crossings (1.16/s) vs a dead gap 5 crossings (0.63/s). **Opposite of v0's inverted markers** → supports the ball-crossing pivot. NOT validated (compromised footage; the 5 dead crossings are noise — false-positive balls + net line moving with the zoom).
- Also curated `IMG_7652.jsonl` labels via `--review` (32 → 9 competitive rallies) as a tool test-drive.
- Next: clean fixed footage → sharpen v1 (ball false-positive filters) → compose the full v1 detector (crossings → segment → rallies.json) → the real **v0-vs-v1** comparison via the harness.

## 2026-08-09 — v0 segmenter + v0/v1 plan

- Built `src/segment.py` — signal-agnostic, gap-tolerant, min-duration rally segmenter (4 tests). Proved the v0 loop closes end-to-end (tracks → activity → segment → `rallies.json` → harness) **on `IMG_7652.MOV` (the zoom-compromised clip)** — a **plumbing check only**: it produced rally **timestamps, not a highlight video** (99 junk segments, recall 0.16, on compromised footage + inverted signal). **No render/cut module exists yet** — `rallies.json → highlights.mp4` is unbuilt (Phase 1 back half); no meaningful or persisted output was produced.
- **ADR-039:** frozen **v0 (player, ADR-026/028)** baseline kept intact; **v1 (ball net-crossings)** to be built as additive new modules; harness compares both on the same labels. Rally definition under review → moving toward **exchange-based** (≥ N net crossings, crossing count = ranking score).
- Next: on clean fixed footage, build **v1 ball detector + net-crossing counter**, run both, compare.

## 2026-08-08 — First real footage; pivot to the ball

- Captured 2 real indoor clips (IMG_7652/7655) but **compromised by camera zoom/pan** → calibration invalid, players off-frame. Confounded read, not a fair test.
- Real footage exposed: player detection is **noisy/occluded** on real footage (median 2–3/frame), and **player-activity markers are inverted** on casual play (dead time more active than low-energy rallies).
- **Ball is detectable indoors** (5/6 in-play frames, noisy) → the ball-net-crossing count is a viable rally signal.
- **Decisions:** target = competitive rallies; domain = casual drop-in; fixed camera non-negotiable (no zoom/pan); **pivot to the ball-net-crossing rally counter** as the next build; tracking + ball needed earlier than planned. Full run in EXPERIMENTS.md.
- Tooling held up: order-independent calibration worked on real footage (RMSE 0.45).

## 2026-08-06 — First detection pipeline + preliminary read

- Built the detection pipeline end-to-end (branch `feat/detection`): YOLOv8n person detection → foot point → **court coordinates** → **court-region filter** (drops crowd/line-judges; 89% of frames = 4 players) → **motion + kitchen-formation markers** → scored against hand-labeled rallies. 10 tests green.
- **Preliminary read on `austin_rally2`** (dev-scaffold, not eval — see EXPERIMENTS.md): single motion/position markers separate rallies from dead time only weakly; the hard low-motion rally moments here are **serves** (players still behind the baseline), positionally like dead time → **ball/pose may be needed earlier than Phase 2**. Directional only (one broadcast clip); stopped to avoid overfitting.
- Uses the 2023 Austin PPA match; 3 single-camera rally clips carved from it as the test bed.

## 2026-08-06 — Calibration hardened

- **`calibrate.py` is now order-independent and orientation-safe** (ADR-035). Clicking the 12 court points in any order works; a real 28.2 ft mis-ordered calibration recovered to **0.36 ft**. Verified on a fresh run (0.356 ft, orientation correct). 15 tests green. Merged to `main`.
- **Decision:** detection runs in court coordinates; per-court calibration absorbs camera pose (incl. elevation) but not occlusion — track players by their feet (ADR-036).
- **Decision:** two-sided detection — a live-play marker list weighed against the stopped-play list, no marker decides alone (ADR-037). Motivated by lob/wide chases tripping "left court" and dinks tripping "all stationary" during live play. Phase 0.6 now measures both marker directions.
- The 2023 PPA highlights clip served as the calibration test bed only. It stays unusable for rally *detection* (edited, dead time removed).

## 2026-08-05 — Phase 0 eval harness

- Built `eval/harness.py`: temporal-IoU one-to-one matching → detection metrics (recall, FP/10 min, boundary error) + selection metrics (budget, utilization, count, keep rate), per PRD §5 / TECH_SPEC §11. `make eval` + `make test`.
- Proven on a hand-written stub — **Phase 0 exit criterion met**. 12 tests, built test-first. Merged to `main`.
- Repo scaffolded to TECH_SPEC §12 (`src/`, `eval/`, `README.md`, `config.yaml`, `requirements.txt`).

## 2026-08-04 — Capture bring-up

- Camera capture validated: **90–96% frame delivery** over wifi RTSP (n=4), losses bursty (1–4 s stalls), on a clean network. Audio codec `pcm_alaw` → MKV container required.
- Decisions: wallclock timestamps (ADR-030), clean-stop recordings (ADR-031), prefer microSD once available (ADR-032), plus post-prototype ADRs 033–034.
- Added `STRATEGY.md` (multi-venue direction, exploratory). Sharpened the Phase 0.6 gate to name the two confounders (dink rallies, courtesy returns) and added far-court pose-reliability as a risk.
