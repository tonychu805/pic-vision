# Progress Log

Plain-language record of what's been built and decided, newest first. Git history has the detail; this is the map. Metric-producing runs go in [`EXPERIMENTS.md`](./EXPERIMENTS.md); decisions in [`DECISIONS.md`](./DECISIONS.md).

## ▶ NEXT SESSION — start here

**The project is blocked on one thing: field footage of a real session.** No code to build until it exists — building now would be guessing. When Tony brings footage:

1. `calibrate.py <session> --out <calib>.json` (order-independent; RMSE < 0.5 ft)
2. `label.py <session> --out eval/labels/<name>.jsonl` — rally start/end per **`LABELING.md` v2** (rally = serve → ball dead; warm-up excluded; interruption = label up to it)
3. Generate court tracks + score markers vs labels = **the real Phase 0.6** (do player markers separate rallies from dead time?)
4. Read → fork: markers hold → build segmenter/selection/render/`cut.py`; ball needed → build ball-presence pass first.

**If no footage yet:** the only action is capture — mount (behind baseline, ≥8 ft, centered, rigid) → 30 s **shakedown** → framing check (**far feet visible at the kitchen line**) → `calibrate.py` on it → full session over **wifi/RTSP** (microSD skipped), 10-min segments, clean stop. Capture command + fixes in TECH_SPEC §1.2 / ADR-030–032.

**Live hypothesis to settle:** the preliminary read (broadcast clip, dev-scaffold) showed single player-markers are weak on *still* moments (serves) → **the ball may be needed earlier than Phase 2**. Test on real footage; fusion (ADR-022) is the likely answer.

## Status at a glance

- **Built + tested (26 tests):** eval harness · calibration (order-independent) · detection pipeline front-end (`src/players.py`, `src/events.py` — detection → court coords → court filter → motion + kitchen markers) · scoring against labels.
- **Not built (Phase 1, after the gate):** segmenter, selection, render, `cut.py` orchestrator — the session→reel back half.
- **Decided:** ADR-035 (order-independent calibration), ADR-036 (court coords; calibration absorbs pose not occlusion), ADR-037 (two-sided live/stopped markers), LABELING.md v2, prior art assessed (beat, don't adopt — EXPERIMENTS.md).
- **Capture:** wifi/RTSP (tested, ~90–96% delivery, bursty drops; PTS handles drops). microSD skipped.
- `main` is ahead of `origin` (local, unpushed).

---

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
