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
