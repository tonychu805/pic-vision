# Progress Log

Plain-language record of what's been built and decided, newest first. Git history has the detail; this is the map. Metric-producing runs go in [`EXPERIMENTS.md`](./EXPERIMENTS.md); decisions in [`DECISIONS.md`](./DECISIONS.md).

## Phase gate tracker → [`CHECKLIST.md`](./CHECKLIST.md)

## ▶ NEXT SESSION — start here

**The v1 ball-net-crossing rally detector is built and diagnosed. The mechanism is sound; its two inputs broke on the zoom-compromised clips. Fixes are shipped. The blocker is one clean, fixed clip to validate on.** Full diagnosis: EXPERIMENTS.md 2026-08-10.

**What we proved (on IMG_7652/7655, both compromised):** the crossing logic is fine (tested), but (1) the **derived net line landed below the real net** (calibration on a zoomed frame), and (2) **nano tagged heads as "ball."** So the crossing counts were noise and the "9/9 recall" was hollow (watched clips weren't real rallies). yolov8x finds the real ball (0.91 mid-court) but only 0.2–0.3 at the net (small/far) — the crossing moment is the hardest detection from a behind-baseline camera.

**The single gate — capture ONE clean clip:**
1. Rigid mount, **NO zoom, NO pan**, whole court in frame, well-lit. Mount **higher / side-on** if possible so the net isn't the farthest, smallest point.
2. Calibrate with the **new flow: 12 court points + 2 net-tape clicks** (net marking now in `calibrate.py`).
3. Re-label to **competitive rallies only** (`LABELING.md` v2).

**Then run the shipped recipe and get the first real number:** `detect_ball` (yolov8x default) with `max_ball_px` set to the **measured** ball pixel size, marked net via `net_line_y`, → `crossing_times` → `cluster_crossings` (min_crossings ≈ 5) → segments → harness vs labels. **Measure the ball's pixel size first**.

**The ball tracker is now BUILT, WIRED, and validated on real footage (2026-08-11, EXPERIMENTS).** Background: 2026-08-10 reprocessing showed that with a correct net line real rallies read clean, but dead time still produced phantom crossings — in a multi-court gym the detector locks onto **out-of-play balls** (adjacent courts, idle/warm-up) and "best ball anywhere per frame" hops between them, flipping sides. `src/pipeline.py` now chains `detect_candidates → track_ball → crossing_times → cluster_crossings`; the single-ball tracker rejects teleports. On IMG_7652: dead-time 659–666s dropped **22 → 0** tracked crossings while the 58–77.5s rally kept **16** — clean separation. Still on compromised footage: this validates the *mechanism*, not a benchmark number. Recipe note: use `gap_sec≈3s` (crossings are up to ~2s apart; 1.0s dissolves real rallies).

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
