# Progress Log

Plain-language record of what's been built and decided, newest first. Git history has the detail; this is the map. Metric-producing runs go in [`EXPERIMENTS.md`](./EXPERIMENTS.md); decisions in [`DECISIONS.md`](./DECISIONS.md). Doc-authority map (which file governs what) lives in [`CLAUDE.md`](./CLAUDE.md).

## Phase gate tracker → [`CHECKLIST.md`](./CHECKLIST.md)

## ▶ NEXT SESSION — start here

**Status (2026-08-18): the "precision ceiling" was a measurement artefact. Two videos re-measured against corrected labels both roughly doubled.**

Yesterday's headline — precision pinned at 0.25–0.29 across three cameras, therefore precision is a property of the pipeline's gating logic — **does not survive contact with playback review.** Reviewing false positives at real speed and correcting the labels moved both videos that were checked:

| video | precision (published 2026-08-17) | precision (after review) | what changed |
|---|---|---|---|
| pb_draft_cup | 0.27 | **0.59** | labels 7 → 18; 8 of 15 "false positives" were real rallies |
| brickwall (new, 4th camera) | — (0.59 first pass) | **0.64** | labels 33 → 35 |
| IMG_7743 | 0.29 | **not re-reviewed** | — |
| IMG_7744 | 0.25 | **not re-reviewed** | — |

**Do this first: re-review IMG_7743 and IMG_7744 the same way.** Cut their false positives into a review reel, watch at real speed, correct the labels, rescore. They are the last two data points holding up the ceiling claim, and their labels have never been checked for completeness — IMG_7743's 33 labels over 67 minutes (8.8% density) look sparse by the same standard that flagged pb_draft_cup. The recipe is in `EXPERIMENTS.md` (2026-08-18 entries); the reel-building is a few lines of ffmpeg.

**Three failure modes are now distinguished — they need different fixes and should not be lumped together as "precision":**
1. **Fragmentation.** `gap_sec=3.0` was tuned on ~10s rallies and splits long ones, which charges the detector *twice* (a miss plus a false positive). Cost brickwall 10 of its 18 false positives. `gap_sec=4.0` gives brickwall 0.73/0.91 but degrades the others — **do not ship it**; the real fix is a gap that tracks observed rally length.
2. **Label incompleteness.** Real play that was never marked scores as a false positive. Cost pb_draft_cup 8 of 15. Root cause is the old "curate to competitive rallies" habit, which `LABELING.md` already warns against.
3. **Genuine junk**, of two distinct kinds — *phantom crossings* (a tossed ball whose image-y crosses `net_y` without the ball crossing the net; the `band` parameter does **not** fix this, tested) and *courtesy returns* (ball really crosses, but it is dead time — the same problem as PIC-31, named as a risk in `PRD.md` §0.6 back in August and still open).

**Rally length is the hidden variable behind most of this**, and it is driven by format, not camera: brickwall is doubles tournament play (21.8s mean rally, ~50% of the video live); pb_draft_cup is a **singles** match (9.3s, 27%); IMG_7743/7744 are casual doubles (~10s, 4–9%). Raw precision is **not comparable across videos with different densities** — a spurious segment lands on real play far more easily when half the video is live. Use the chance-adjusted lift in `EXPERIMENTS.md` when comparing.

**New this session:** `scripts/check_drift.py` (camera-bump/creep detection, closes PIC-29 — run it on any new footage *before* calibrating or labelling) and a video picker in `label_web.py` (run it with no arguments to choose a video and auto-load its labels).

**Runnable now (all local — the RTX 2000 Ada does ~28 fps with court masking):**
1. Inference env: `/mnt/fast_scratch/tf215_env/venv` (TF 2.15), weights at `/mnt/fast_scratch/tracknet_weights/weights_k14_epoch19`. Export `LD_LIBRARY_PATH` to the venv's `nvidia/*/lib` dirs first.
2. `python3 scripts/pod_infer.py --video game.mp4 --calib calib/<name>_calib.json --output cache/<name>_predictions_k14.csv` — pass `--calib`, it masks outside the court *before* inference.
3. Score: `rally_segments_from_predictions(..., in_court=court_wedge(calib), gap_sec=3.0, min_crossings=6)` → `match_intervals(..., threshold=0.5)`. **Note `match_intervals` returns a dict** (`matches`/`missed`/`false_pos`) — unpacking it as a tuple silently yields string lengths as metrics, which looks plausible and is entirely wrong.
4. **Tests run as `.venv/bin/python -m pytest -q tests/`** — system `python3` has neither pytest nor cv2, and `archive/tests/` fails collection.

**Traps that have cost real time, all now guarded or documented:**
- **Source `.MOV` files can be corrupt** — IMG_7743/7744 silently decoded 930 of 121k frames, exit 0. Both inference paths now abort below 98%.
- **A calibration without `net_image_points` gives a net line ~130px too low.**
- **A mid-session camera bump invalidates calibration from that instant on** (ADR-049) — now detectable with `scripts/check_drift.py`.
- **IoU≥0.3 vs IoU≥0.5** — numbers logged before 2026-08-17 may use the looser threshold. `TECH_SPEC.md` §11 specifies 0.5.
- **Judge rally-vs-dead-time from playback, never stills or aggregate statistics** — both have produced confidently wrong answers on this project.

## Status at a glance

- **Active detection path: TrackNet** (`src/tracknet.py`, local GPU or RunPod via `scripts/pod_infer.py`). The YOLO path (`src/pipeline.py`, `archive/yolo_pipeline.py`) is retired — ADR-046.
- **Pipeline:** `predictions.csv` → court gate (`src/calib.py`'s `court_wedge`, perspective-aware trapezoid — prefer over the flatter `court_x_range`) → `track_ball` (teleport/re-acquisition confirmation, `src/track.py`) → `crossing_times` → `cluster_crossings` (`src/ball.py`). Shipped default `gap_sec=3.0`, `min_crossings=6` (ADR-048).
- **Built + tested (94 tests):** eval harness (IoU matching at 0.5, detection + selection tables) · calibration (order-independent, browser + CLI, marks the net) · TrackNet prediction parsing (including per-detection blob size/confidence) + court-wedge gating + tracker confirmation · scoring against hand labels on 4 independent camera angles.
- **Not built:** a signal that tells a real rally apart from a quick failed exchange (PIC-31 — IMG_7744's open problem); selection/ranking (competitive vs. casual — Phase 1, still gated on precision).
- **Camera-drift detection built** (`src/drift.py`, `scripts/check_drift.py`, PIC-29 closed) — run `check_drift.py` on any new footage *before* calibrating or labelling it.
- **Tried and rejected:** blob size/confidence as a clutter filter (PIC-2, 2026-08-17) — doesn't separate real balls from junk on this footage.
- **Decided recently:** ADR-046 (TrackNet is the active detection path), ADR-048 (`min_crossings=6` is the one canonical default, reconciled across code+docs), ADR-049 (a camera bump invalidates calibration going forward — detect it, don't tune around it), ADR-050 (a precision number is not admissible until its false positives have been reviewed at playback speed).
- `main` pushed to `origin`, no open branches.

---

## 2026-08-18 — Camera-drift detection built; footage triage

- **Built `scripts/check_drift.py` + `src/drift.py`** (6 tests, suite 83 → 89 green) — the "detect it, don't tune around it" half of ADR-049. It phase-correlates sampled frames against the first one and reports two things separately: **bumps** (a step between consecutive samples that then holds — splits the video, each half needs its own calibration) and **creep** (many small changes accumulating — no clean split point). Exits 1 on a bump so it can gate a run. **Run it on any new footage before calibrating or labeling it.**
- **Validated against a known answer before being trusted**: on IMG_7743 it independently recovered the ADR-049 bump, bracketing it between t=2820s and t=2880s (hand-diagnosed at t≈2859s) — the thing that cost a session to find by hand. On brickwall it reads 0.2 px over 25 minutes, so a locked camera reads as locked.
- **Archived the two broadcast videos** (`ppa_atlanta_2023_...`, `austin_open_...`) to `videos/raw/archive/`. They're edited multi-camera productions — 19 and 25 hard scene cuts per 3 minutes, versus 0 for a fixed camera. Calibration is invalid *within* a single rally, so no tuning makes them work. Details and measurements in that directory's README.
- **Corrected a wrong all-clear in `videos/raw/archive/README.md`**: IMG_7655 was recorded as "no known defect found," but it takes a ~25 px vertical bump at t≈470s and creeps ~16 px horizontally. It is **not** the cheap fourth camera its 36 existing labels make it look like — those labels straddle the bump.
- **`brickwall_pro_series_finals.mp4` is the strongest remaining candidate**: 25 min, fixed camera, 0.2 px total travel — measurably the most stable footage in the project, better than IMG_7743 which needed split calibration to be usable at all. Not yet calibrated, labeled, or scored.

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
