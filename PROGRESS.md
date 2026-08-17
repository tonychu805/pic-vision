# Progress Log

Plain-language record of what's been built and decided, newest first. Git history has the detail; this is the map. Metric-producing runs go in [`EXPERIMENTS.md`](./EXPERIMENTS.md); decisions in [`DECISIONS.md`](./DECISIONS.md). Doc-authority map (which file governs what) lives in [`CLAUDE.md`](./CLAUDE.md).

## Phase gate tracker → [`CHECKLIST.md`](./CHECKLIST.md)

## ▶ NEXT SESSION — start here

**Status (2026-08-17): three cameras now have real, comparable numbers, and the binding constraint has flipped from recall to precision.**

The old blocker (IMG_7743's 13-rally recall ceiling) turned out to be a mid-session camera bump silently invalidating `net_y` for the back half of the recording — not a detection problem (ADR-049). Per-segment recalibration recovered recall 0.52→0.79. Two more cameras (IMG_7744, `pb_draft_cup`) have since been independently calibrated, hand-labeled, and scored.

**Where the numbers stand** (IoU≥0.5 — the real `TECH_SPEC.md` §11 threshold; see the IoU trap below before trusting any number from before today):

| video | precision | recall | labels |
|---|---|---|---|
| IMG_7743 (post-bump-fix, split calibration) | 0.29 | 0.79 (26/33) | 33 |
| IMG_7744 | 0.25 | 0.60 (6/10) | 10 |
| `pb_draft_cup` | 0.27 | 0.86 (6/7) | 7 |

**The one thing to work on next: precision is pinned at 0.25–0.29 across all three cameras/venues, while recall varies a lot per video.** That pattern means precision is a property of the pipeline's gating logic itself, not a calibration or footage-quality problem — further per-camera calibration work has a shrinking payoff from here. Two *different*, already-diagnosed root causes are open, and neither is fully closed:
- **IMG_7743:** false positives surviving `court_wedge` were traced (2026-08-16) to TrackNet *hallucinating* ball-shaped detections in background clutter (adjacent court, wall, ceiling fixtures) — no real ball there at all. Not re-characterized since the camera-bump fix changed the segment set.
- **IMG_7744 (Linear PIC-31, open):** false positives are the opposite — real ball, real crossings, real court, but the exchange itself was a quick or failed point, not what a human calls a rally. No geometric gate or size/confidence filter can tell this apart from a real rally, because the signal is identical. Needs a new kind of signal (sustained-exchange duration tuned for this, or a point-outcome/dead-time-after signal) — not yet designed.
- **`pb_draft_cup`:** not yet FP-reviewed at real playback speed — unknown which of the two failure modes above it belongs to, or a third one.

**Tried and rejected today: PIC-2** — using the detector's own already-computed blob-size and confidence numbers to filter clutter. Checked the real distributions (real-rally vs. outside-rally detections look almost identical: size median 15.0px both, confidence median 0.642 vs 0.627) and ran a full threshold sweep against the 33 IMG_7743 labels. No combination beat geometry (`court_wedge`) alone — the best precision found cost recall dropping from 0.79 to 0.52. Full sweep table in `EXPERIMENTS.md`. Don't re-attempt this without new evidence the detector's confidence signal has changed.

**Runnable now (all local — no RunPod needed; the RTX 2000 Ada does ~57 fps):**
1. Inference env: `/mnt/fast_scratch/tf215_env/venv` (TF 2.15), weights at `/mnt/fast_scratch/tracknet_weights/weights_k14_epoch19`. Export `LD_LIBRARY_PATH` to the venv's `nvidia/*/lib` dirs first — the project's own `.venv` cannot run inference (no GPU-capable TF).
2. `python3 scripts/pod_infer.py --video game.mp4 --output predictions.csv`
3. Score: `predictions.csv` → `src.tracknet.rally_segments_from_predictions(..., in_court=court_wedge(calib), gap_sec=3.0, min_crossings=6)` → `eval/harness.py`'s `match_intervals(..., threshold=0.5)` vs the matching `eval/labels/*.jsonl`. `court_wedge` isn't wired into `src/cut.py`'s CLI yet (still `court_x_range`, the flatter/worse gate) — scoring with the real gate is a one-off script today.

**Traps that have cost real time, all now guarded or at least documented:**
- **Source `.MOV` files can be corrupt.** IMG_7743/7744 had localized HEVC damage that made OpenCV stop decoding *silently* (930 of 121k frames returned, exit code 0). Use the repaired `videos/*_fixed.mp4`; both inference paths now abort below 98% of expected frames.
- **A calibration without `net_image_points` gives a biased net line** (~130px too low — the net's base, not its tape). `net_line_y` now warns.
- **IoU≥0.3 vs IoU≥0.5.** Every IMG_7743 number logged between 2026-08-16 and the split-calibration fix used the looser, non-spec IoU≥0.3 informally. `TECH_SPEC.md` §11 specifies 0.5; the table above uses 0.5. Check which threshold produced any older number before trusting it.
- **A mid-session camera bump silently invalidates calibration for everything after it** — no amount of threshold tuning recovers it (ADR-049). Automatic drift detection still isn't built (Linear PIC-29); per-segment recalibration today is a manual, one-off process (split the video/labels by hand, calibrate each half separately).

**Labelling is browser-based** (`label_web.py`) — the workstation is driven over SSH, so X11-forwarded video is unusable. Two passes: mark every rally with `s`/`e`, then `g` to grade with hindsight (`1` highlight / `2` ordinary / `3` not a rally — grade ordinary play `2`, don't delete it, or the detector gets charged for correctly finding real play). `calibrate_web.py` is the matching browser calibration tool (12 court + 2 net points, order-independent).

## Status at a glance

- **Active detection path: TrackNet** (`src/tracknet.py`, local GPU or RunPod via `scripts/pod_infer.py`). The YOLO path (`src/pipeline.py`, `archive/yolo_pipeline.py`) is retired — ADR-046.
- **Pipeline:** `predictions.csv` → court gate (`src/calib.py`'s `court_wedge`, perspective-aware trapezoid — prefer over the flatter `court_x_range`) → `track_ball` (teleport/re-acquisition confirmation, `src/track.py`) → `crossing_times` → `cluster_crossings` (`src/ball.py`). Shipped default `gap_sec=3.0`, `min_crossings=6` (ADR-048).
- **Built + tested (83 tests):** eval harness (IoU matching at 0.5, detection + selection tables) · calibration (order-independent, browser + CLI, marks the net) · TrackNet prediction parsing (including per-detection blob size/confidence) + court-wedge gating + tracker confirmation · scoring against hand labels on 3 independent camera angles.
- **Not built:** automatic camera-bump/calibration-drift detection (PIC-29); a signal that tells a real rally apart from a quick failed exchange (PIC-31 — IMG_7744's open problem); selection/ranking (competitive vs. casual — Phase 1, still gated on precision).
- **Tried and rejected:** blob size/confidence as a clutter filter (PIC-2, today) — doesn't separate real balls from junk on this footage.
- **Decided recently:** ADR-046 (TrackNet is the active detection path), ADR-048 (`min_crossings=6` is the one canonical default, reconciled across code+docs), ADR-049 (a camera bump invalidates calibration going forward — detect it, don't tune around it).
- `main` pushed to `origin`, no open branches.

---

## 2026-08-17 — Camera-bump root-cause fix, two more cameras scored, PIC-2 tried and rejected

- **Diagnosed and fixed the real cause of IMG_7743's recall ceiling** (PIC-1): not a detection problem — the camera was physically bumped ~47 minutes into a 67-minute recording, shifting the net's image position and silently invalidating `net_y` for the rest of the session. Confirmed four independent ways (hard time boundary in the miss pattern, visible net-tape shift in frames, far-wall signage ruling out a tilt, and recall recovering when `net_y` is patched for the tail). Recorded as ADR-049. Built the real fix (split calibration, not a rough patch) and recovered recall 0.52→0.79 at the correct IoU≥0.5 threshold. Along the way, found and fixed a real regression in `calibrate_web.py` (the order-independent calibration solver had never been wired into the browser tool, only the CLI one).
- **Scored a second full camera angle, IMG_7744, from scratch** (PIC-11): new calibration, new hand labels (10 rallies), full-video inference. 0.25 precision / 0.60 recall. Found and fixed a real bug in `label_web.py` along the way (a single-threaded server could hang on video streaming and silently lose a labeling session).
- **Watched IMG_7744's false positives at real playback speed** (not stills — this project got burned once trusting stills for a rally-vs-not call) and found a second, different false-positive failure mode from IMG_7743's: real ball, real crossings, but a quick/failed exchange rather than a rally. Filed separately as PIC-31 — geometric gating can't fix this, because the signal it's built to catch (a real ball where none should be) isn't what's happening here.
- **Scored a third camera, `pb_draft_cup`**: 0.27 precision / 0.86 recall. Confirms precision sitting in the same 0.25–0.29 band across all three cameras regardless of recall — a strong signal that precision is a pipeline property, not a per-camera issue.
- **Ran the PIC-2 spike to completion and rejected it with real numbers**: blob size and detection confidence, now wired end-to-end (parsed, filterable, tested), don't separate real balls from background clutter on this footage. Full distribution comparison and threshold sweep in `EXPERIMENTS.md`.
- **Removed OpenWiki entirely** (the generated `openwiki/` tree, its CI workflow, and the boilerplate it left in `CLAUDE.md`/`AGENTS.md`) — it wasn't being read and had gone stale after the TrackNet switch. Rewrote both files with real, doc-grounded project conventions instead.

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
