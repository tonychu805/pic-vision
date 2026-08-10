# Progress Log

Plain-language record of what's been built and decided, newest first. Git history has the detail; this is the map. Metric-producing runs go in [`EXPERIMENTS.md`](./EXPERIMENTS.md); decisions in [`DECISIONS.md`](./DECISIONS.md).

## ▶ NEXT SESSION — start here

**First real footage (2026-08-08) came in but was compromised by camera zoom/pan** — not a fixed view, so the single calibration broke and players left frame. The read was confounded — *not* a fair test. Full detail in EXPERIMENTS.md (2026-08-08). Two things gate progress:

1. **Capture CLEAN fixed footage** — rigid mount, **NO zoom, NO pan**, whole court in frame, **well-lit (daylight / bright court)** so the ball is trackable. Indoor works (ball detectable 5/6 frames) but brighter is better. **This is the blocker.** *(No hardware upgrade yet — prove the net-crossing count in software + lighting first; camera-over-compute only if ever needed — ADR-038.)*
2. **Re-label to competitive rallies only** (`LABELING.md` v2) — today's labels were "any play" (warm-up/casual included), a target mismatch.

Then the **priority build — the pivot**: a **ball-net-crossing rally counter** (detect ball → filter false positives → track → count crossings of the net line). On real casual play, player *activity* is inverted (dead time is more active than low-energy casual rallies), so **the ball — "is a point being contested across the net" (ADR-028) — is the real rally signal**, not player motion. Also add **ByteTrack** to stabilize player positions (revisits ADR-008). Then a fair Phase 0.6.

**Why the pivot:** activity/position markers failed on real casual footage (motion + kitchen both inverted, even on clean frames). Tracking + ball both look needed *earlier* than the prototype planned (ADR-008 / ADR-022). The ball being detectable indoors makes the net-crossing path viable.

## Status at a glance

- **Built + tested (26 tests):** eval harness · calibration (order-independent) · detection pipeline front-end (`src/players.py`, `src/events.py` — detection → court coords → court filter → motion + kitchen markers) · scoring against labels.
- **Not built (Phase 1, after the gate):** segmenter, selection, render, `cut.py` orchestrator — the session→reel back half.
- **Decided:** ADR-035 (order-independent calibration), ADR-036 (court coords; calibration absorbs pose not occlusion), ADR-037 (two-sided live/stopped markers), LABELING.md v2, prior art assessed (beat, don't adopt — EXPERIMENTS.md).
- **Capture:** wifi/RTSP (tested, ~90–96% delivery, bursty drops; PTS handles drops). microSD skipped.
- `main` is ahead of `origin` (local, unpushed).

---

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
