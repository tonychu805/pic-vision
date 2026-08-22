# Progress Log

This file is a pointer, not the log itself — see [`AGENTS.md`](./AGENTS.md) for the same pattern applied to agent instructions. The actual history lives in [`progress/`](./progress/), one file per day, named `MM.DD progress overview.md`; sorted by filename, oldest first, so the last file in a directory listing is always the most recent. Restructured 2026-08-21 (documentation-maintenance review) — the old single growing file had accumulated multiple nested "superseded by the above" layers, which is exactly the reading-habit cost per-day files are meant to fix. Git history has the code-level detail; `progress/` is the narrative map. Metric-producing runs go in [`EXPERIMENTS.md`](./EXPERIMENTS.md); durable decisions in [`DECISIONS.md`](./DECISIONS.md). Doc-authority map (which file governs what) lives in [`CLAUDE.md`](./CLAUDE.md).

## ▶ NEXT SESSION — start here

**[`progress/08.22 progress overview.md`](./progress/08.22%20progress%20overview.md)** is the most recent entry as of this writing. Check the `progress/` folder for anything newer before trusting that.

## Phase gate tracker → [`CHECKLIST.md`](./CHECKLIST.md)

Covers Phase 0–1 only; Linear (`pic-vision` team, `Rally Detection Accuracy` project) is authoritative for current priorities.

## Status at a glance

- **Active detection path: TrackNet** (`src/tracknet.py`, local GPU or RunPod via `scripts/pod_infer.py`). The YOLO path (`src/pipeline.py`, `archive/yolo_pipeline.py`) is retired — ADR-046. TrackNetV3 (a different, newer pretrained architecture) is under evaluation as a possible replacement — see Linear PIC-47 and `progress/08.21 progress overview.md`.
- **Pipeline:** `predictions.csv` → court gate (`src/calib.py`'s `court_wedge`, perspective-aware trapezoid — prefer over the flatter `court_x_range`) → `track_ball` (teleport/re-acquisition confirmation, `src/track.py`) → `crossing_times` → `cluster_crossings` (`src/ball.py`). Shipped default `gap_sec=3.0`, `min_crossings=6` (ADR-048).
- **Built + tested (116 tests):** eval harness (IoU matching at 0.5, detection + selection tables) · calibration (order-independent, browser + CLI, marks the net) · TrackNet prediction parsing (including per-detection blob size/confidence) + court-wedge gating + tracker confirmation · scoring against hand labels on 4 independent camera angles · adaptive per-video `gap_sec` (PIC-33, opt-in) · a dev-only trained segment classifier (PIC-46, threshold not yet calibrated — not shipped).
- **Not built:** a signal that tells a real rally apart from a quick failed exchange (PIC-31 — the project's highest-priority open issue); selection/ranking (competitive vs. casual — Phase 1, still gated on precision); paddle-contact detection (PIC-42, prototyping only).
- **Camera-drift detection built** (`src/drift.py`, `scripts/check_drift.py`, PIC-29 closed) — run `check_drift.py` on any new footage *before* calibrating or labelling it.
- **Tried and rejected:** blob size/confidence as a clutter filter (PIC-2) — doesn't separate real balls from junk on this footage; a self-calibrated duration/rate threshold (PIC-31 candidate #1) — doesn't cleanly separate real rallies from dead-time crossings either.
- **Decided recently:** ADR-046 (TrackNet is the active detection path), ADR-048 (`min_crossings=6` is the one canonical default), ADR-049 (a camera bump invalidates calibration going forward — detect it, don't tune around it), ADR-052 (eval-set roles locked — IMG_7743 is `eval`, may never again be used to pick a parameter), ADR-053 (the label-artefact replacement precision numbers, 0.44/0.54/0.59/0.64, are blocked by adversarial review — only the original ceiling *retraction* survives).
- `main` pushed to `origin`, no open branches as of the last `progress/` entry.

## Three failure modes — distinguish these, don't lump them together as "precision"

1. **Fragmentation.** A too-tight `gap_sec` splits long rallies and charges the detector twice (a miss plus a false positive). The adaptive `gap_sec` (PIC-33) substantially reduces this on doubles/tournament-length rallies.
2. **Label incompleteness.** Real play that was never marked scores as a false positive — the mechanism behind the entire label-artefact thread (ADR-050/051/053). Root cause is the old "curate to competitive rallies" habit, which `LABELING.md` warns against.
3. **Genuine junk**, of two distinct kinds — *phantom crossings* (a tossed ball whose image-y crosses `net_y` without the ball crossing the net) and *courtesy returns* (ball really crosses, but it's dead time — PIC-31's territory, the project's current highest-priority open problem).

**Rally length is the hidden variable behind most of this**, and it's driven by format, not camera: brickwall is doubles tournament play (21.8s mean rally, ~50% of the video live); pb_draft_cup is a **singles** match (9.3s, 27%); IMG_7743/7744 are casual doubles (~10s, 4–9%). Raw precision is **not comparable across videos with different densities** — a spurious segment lands on real play far more easily when half the video is live. Use the chance-adjusted lift in `EXPERIMENTS.md` when comparing.

## Runnable now (all local — the RTX 2000 Ada does ~28 fps with court masking)

1. Inference env: `/mnt/fast_scratch/tf215_env/venv` (TF 2.15), weights at `/mnt/fast_scratch/tracknet_weights/weights_k14_epoch19`. Export `LD_LIBRARY_PATH` to the venv's `nvidia/*/lib` dirs first.
2. `python3 scripts/pod_infer.py --video game.mp4 --calib calib/<name>_calib.json --output cache/<name>_predictions_k14.csv` — pass `--calib`, it masks outside the court *before* inference.
3. Score: `rally_segments_from_predictions(..., in_court=court_wedge(calib), gap_sec=3.0, min_crossings=6)` → `match_intervals(..., threshold=0.5)`. **Note `match_intervals` returns a dict** (`matches`/`missed`/`false_pos`) — unpacking it as a tuple silently yields string lengths as metrics, which looks plausible and is entirely wrong.
4. **Tests run as `.venv/bin/python -m pytest -q tests/`** — system `python3` has neither pytest nor cv2, and `archive/tests/` fails collection.

## Traps that have cost real time, all now guarded or documented

- **Source `.MOV` files can be corrupt** — IMG_7743/7744 silently decoded 930 of 121k frames, exit 0. Both inference paths now abort below 98%.
- **A calibration without `net_image_points` gives a net line ~130px too low.**
- **A mid-session camera bump invalidates calibration from that instant on** (ADR-049) — now detectable with `scripts/check_drift.py`.
- **IoU≥0.3 vs IoU≥0.5** — numbers logged before 2026-08-17 may use the looser threshold. `TECH_SPEC.md` §11 specifies 0.5.
- **Judge rally-vs-dead-time from playback, never stills or aggregate statistics** — both have produced confidently wrong answers on this project.
- **A Python multiprocessing DataLoader with `num_workers>0` and a large in-memory dataset object can silently hang, not error, if the platform's default start method is `forkserver`/`spawn` rather than `fork`** — each worker gets its own separately-pickled full copy instead of sharing memory. Cost a session on TrackNetV3 (2026-08-21) before being diagnosed; check `multiprocessing.get_start_method()` if a GPU job looks alive but idle.
- **TrackNetV3's `--large_video` streaming loader (`/mnt/fast_scratch/TrackNetV3/dataset.py`) crashes with an `IndexError` if a video's frame count lands exactly on a sliding-window boundary** — the frame buffer empties via the sliding-window slice right at the end, then the padding step indexes `frame_list[-1]` on an empty list. Hit on `pb_draft_cup_30fps.mp4` (624.5s), did not reproduce on `brickwall_30fps.mp4` (1513s) — length-dependent, not universal. Fixed locally (commit `d77102d` in that clone, **not pushed upstream** — it's a third-party repo at `github.com/qaz812345/TrackNetV3`, not part of this git repo or backed up anywhere else). If that scratch clone is ever re-cloned or wiped, this fix needs reapplying: break out of `__iter__`'s outer loop when `frame_list` is empty instead of padding from it.
