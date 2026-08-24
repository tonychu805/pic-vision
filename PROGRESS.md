# Progress Log

This file is a pointer, not the log itself — see [`AGENTS.md`](./AGENTS.md) for the same pattern applied to agent instructions. The actual history lives in [`progress/`](./progress/), one file per day, named `MM.DD progress overview.md`; sorted by filename, oldest first, so the last file in a directory listing is always the most recent. Restructured 2026-08-21 (documentation-maintenance review) — the old single growing file had accumulated multiple nested "superseded by the above" layers, which is exactly the reading-habit cost per-day files are meant to fix. Git history has the code-level detail; `progress/` is the narrative map. Metric-producing runs go in [`EXPERIMENTS.md`](./EXPERIMENTS.md); durable decisions in [`DECISIONS.md`](./DECISIONS.md). Doc-authority map (which file governs what) lives in [`CLAUDE.md`](./CLAUDE.md).

## ▶ NEXT SESSION — start here

**[`progress/08.24 progress overview.md`](./progress/08.24%20progress%20overview.md)** is the most recent entry as of this writing. Check the `progress/` folder for anything newer before trusting that.

**Immediate next step:** finish reviewing `Brick-Wall--Mid-Atlantic.mp4`'s **corrected** reel by full playback (not just frame samples) — `clips/brickwall_mid_atlantic_reel_5min_fixed/`, not the original `..._reel_5min/` (superseded, see below). This is a brand-new video, first true end-to-end pipeline run (raw file → reel) outside development, no hand labels exist for it. See `EXPERIMENTS.md`'s 2026-08-24 entries for full detail, including a real "is this broadcast footage" check that turned out fine but was worth doing carefully.

**A real coordinate bug was found and fixed the same day (`DECISIONS.md` ADR-064).** `scripts/pod_infer.py` scaled TrackNet predictions back to source pixels with one height-derived ratio applied to both x and y — wrong on any non-16:9 video, and `brickwall_mid_atlantic` (1280×640, 2:1) is the first non-16:9 video this project has processed, which is why it was never caught before. Found via a diagnostic overlay video built for an unrelated reason (visualizing signals), fixed, and the fix's impact *measured* rather than assumed: 51/56 detected candidates and 10/12 reel clips unchanged after re-running with the fix; the few that changed all trace to bug-only crossings near the court-wedge boundary being correctly excluded. Net-crossing detection itself (y-only) was never affected — no other video's results need re-checking. Uncommitted, asked about, confirmed — should be committed this session: the `pod_infer.py` fix, `calib/brickwall_mid_atlantic_calib.json`, and the earlier `rank_and_reel.py` bugfix (a generalization pass had silently dropped the chronological-reel output).

**Also still open from 2026-08-23:** `brickwall-SEMI` is fully labeled and scored (74.2% precision, 63.9% recall, both explainable gaps accepted rather than fixed — see `EXPERIMENTS.md`'s "held-out check, continued" entry). Rally 29 is a genuine unresolved 3-way conflict (original playback call vs. fresh label vs. frame evidence on the same ~10s window) that needs an actual rewatch. `src/select.py`'s ranking formula (ADR-063) is locked in but not yet validated against real `quality:1`/`quality:2` hand grades.

**Also new: post-detection reel ranking got its first real implementation.** `src/select.py`'s `rank_segments` (duration + peak crossing rate + velocity-spike count, live-tuned against `brickwall-SEMI` and locked in — `DECISIONS.md` ADR-063) replaces the ad hoc raw-crossing-count scoring every prior reel used. Not yet checked against `quality:1`/`quality:2` hand grades — that's the natural next step alongside rally 29.

## Phase gate tracker → [`CHECKLIST.md`](./CHECKLIST.md)

Covers Phase 0–1 only; Linear (`pic-vision` team, `Rally Detection Accuracy` project) is authoritative for current priorities.

## Status at a glance

- **Active detection path: TrackNet** (`src/tracknet.py`, local GPU or RunPod via `scripts/pod_infer.py`). The YOLO path (`src/pipeline.py`, `archive/yolo_pipeline.py`) is retired — ADR-046. TrackNetV3 (a different, newer pretrained architecture) is under evaluation as a possible replacement — see Linear PIC-47 and `progress/08.21 progress overview.md`.
- **Pipeline:** `predictions.csv` → court gate (`src/calib.py`'s `court_wedge`, perspective-aware trapezoid — prefer over the flatter `court_x_range`) → `track_ball` (teleport/re-acquisition confirmation, `src/track.py`) → `crossing_times` → `cluster_crossings` (`src/ball.py`). Shipped default `gap_sec=3.0`, `min_crossings=6` (ADR-048) — **confirmed adequate on all four scored videos with honest labels, 2026-08-23, ADR-060/061.**
- **Built + tested (124 tests):** eval harness (IoU matching at 0.5, detection + selection tables) · calibration (order-independent, browser + CLI, marks the net) · TrackNet prediction parsing (including per-detection blob size/confidence) + court-wedge gating + tracker confirmation · scoring against hand labels on 4 independent camera angles, **all four exhaustively relabeled and re-confirmed 2026-08-23** · adaptive per-video `gap_sec` (PIC-33, opt-in, not yet re-validated against the new labels — `PIC-54`) · a dev-only trained segment classifier (PIC-46, trained on the old incomplete labels — needs retraining, `PIC-54`) · **reel ranking** (`src/select.py`, ADR-063, duration + peak crossing rate + velocity-spike count — see the dedicated section below).
- **Not built:** player-movement quality signals (dives, sprint recoveries — the one selection-signal candidate not yet tested); a boundary-precision fix for `gap_sec` fragmentation and the intentional `start` lead-in offset (`PIC-33`/`PIC-55`); paddle-contact detection (PIC-42, prototyping only). **Selection/ranking is no longer blocked** — see the dedicated section below.
- **Camera-drift detection built** (`src/drift.py`, `scripts/check_drift.py`, PIC-29 closed) — run `check_drift.py` on any new footage *before* calibrating or labelling it.
- **Tried and rejected:** blob size/confidence as a clutter filter (PIC-2) — doesn't separate real balls from junk on this footage. ~~a self-calibrated duration/rate threshold~~ **un-rejected 2026-08-23, ADR-061** — the 2026-08-19 rejection was itself a label-contamination artifact; duration alone is a real signal on honest labels (see below), it's just redundant with the already-shipped `min_crossings=6`.
- **Decided recently:** ADR-046 (TrackNet is the active path), ADR-048 (`min_crossings=6`), ADR-049 (camera bump invalidates calibration), ADR-052 (`eval` role locked on IMG_7743), ADR-053 (label-artefact replacement numbers blocked by adversarial review), ADR-054 (raw crossing *count* isn't a valid shot-count proxy — rate is a separate question, see below), **ADR-057 (IMG_7743 postbump's "12/12 real dead-time crossings" fully retracted — they're missed real rallies), ADR-058/059 (the resulting "recall ceiling" was itself measuring the wrong target — corrected), ADR-060 (capstone: all four videos relabeled, `min_crossings=6` confirmed everywhere, `PIC-31`'s founding premise is nearly moot project-wide), ADR-061 (duration threshold un-rejected), ADR-062 (`LABELING.md` v4 — `start` is an intentional 0–3s viewer lead-in, not literal serve contact; `eval/harness.py` doesn't yet account for it, `PIC-55`).**
- `main` pushed to `origin`, no open branches as of the last `progress/` entry.

## Rally detection — where it stands (updated 2026-08-23)

**Precision is essentially solved.** All four scored videos (IMG_7743 post-bump, IMG_7744, brickwall, pb_draft_cup) were exhaustively relabeled 2026-08-23 after IMG_7743 post-bump's original labels turned out to have missed the large majority of real rallies. Once relabeled: of 30 total residual "false positives" across all four videos, 28 are confirmed real rallies with mismatched boundaries (not detector errors), 2 are unconfirmed either way (`PIC-52`), and **zero are confirmed genuine junk or dead time.** `min_crossings=6` is confirmed adequate on all four videos using the metric that actually matters (recall on `quality:1`/highlight-worthy rallies is flat regardless of the threshold value — lowering it recovers nothing real, only adds noise).

**`PIC-31`'s founding problem — distinguish a real rally from a dead-time/courtesy-tap crossing — is nearly moot on this project's current footage.** There isn't enough confirmed genuine dead time left anywhere in the labeled footage to even test a candidate signal against (`PIC-53`). Don't keep chasing this without new footage that actually contains dead time, correctly distinguished from missed short rallies from the start.

**What's actually left is boundary precision, not detection correctness.** The remaining false positives are timing mismatches, from two compounding, only-partly-disentangled causes: `gap_sec`-clustering fragmentation (`PIC-33`, long-standing) and the newly-codified intentional `start` lead-in (`LABELING.md` v4, `PIC-55`, new). A flat 3s correction for the second cause alone recovered ~1/3 of the mismatches in a quick check — real, but not a full fix.

## Rally start/end boundary signals (2026-08-23)

Distinct from "is this a real rally" above — this is about *when* one begins and ends, still open.

**Start**, candidates in order of how validated they are:
- **First net crossing** — what the pipeline uses today. Precise in principle (a discrete physical event), but the label it's compared against (`start`) is intentionally 0–3s earlier by design (`LABELING.md` v4), not a matching physical event — see `PIC-55`.
- **Pre-serve stillness dip** (near-team ankle-speed drop, `scripts/pose_stillness.py`) — validated 2026-08-23 as a reliable *leading indicator* (88% presence on a 17-rally spread sample across brickwall's full length), but its timing doesn't land on the boundary (median ~1s early, real spread) — useful as a trigger/gate ("watch for a confirming crossing burst next"), not as a timestamp source on its own.
- **Player court-depth-at-serve / post-serve transition timing** — exploratory, one small brickwall sample (2026-08-22), never re-tested at scale.

**End**, much less explored:
- **Last net crossing + `gap_sec` trailing silence** — what the pipeline uses today. Imprecise by construction, always lags the true end by up to `gap_sec`.
- **Post-rally motion spike** (a burst of movement right after the point ends — retrieval, resetting, celebration) — noted once (2026-08-22) as a byproduct observation, opposite polarity from the start-side dip, **never tested at scale** the way the start-side dip was. The clear next parallel piece of work if this direction continues.
- The `end` label itself, unlike `start`, is *not* intentionally offset — `LABELING.md` still defines it as the literal ball-dead moment.

`src/render.py`'s `cut_clips(..., pad_sec=3.0)` already pads real output clips 3s before cutting — this has existed the whole project but is never applied on the scoring path, which is most of why the mismatch above exists (`PIC-55`).

## Rally quality / selection signals (new thread, 2026-08-23)

Previously blocked on precision (now resolved above). First test against real quality grades (`quality:1`/`quality:2`) across all four relabeled videos, three signals validated, each independently consistent in direction on all four:

| signal | how measured | direction |
|---|---|---|
| Duration | rally length | `quality:1` 1.4–1.8x longer |
| Crossing rate | crossings ÷ duration (not raw count — see ADR-054) | consistently higher for `quality:1` |
| Ball velocity | mean of the top-5 fastest ball speeds (duration-normalized — raw peak/max is a duration-count artifact, don't use it) | 8–29% higher for `quality:1` |

Player-movement signals (dives, sprint recoveries — `LABELING.md`'s "skill display" factor) not yet tested — would need the pose-tracking pipeline. Small `quality:1` sample sizes per video (n=3–13) — real, consistent trends, not yet a validated ranking model. Full numbers: `EXPERIMENTS.md`, 2026-08-23 "selection signals" entries.

**A ranking formula combining detector-derived signals is now actually implemented** (`src/select.py`'s `rank_segments`, ADR-063, same day) — `duration` (direct, not a denominator) + `peak_crossing_rate` (max in a 3s sliding window, not the flat average — a flat-rate version was tried first and found to penalize long rallies) + `n_spikes` (raw top-decile ball-speed count). Tuned by live playback review on `brickwall-SEMI`, not yet checked against the `quality:1`/`quality:2` grades in the table above — that's the natural next step to actually validate it the way the three signals above were validated.

## Three failure modes — distinguish these, don't lump them together as "precision"

**Largely historical as of 2026-08-23 — see "Rally detection — where it stands" above for the current picture.** Kept for context on how the project's understanding evolved.

1. **Fragmentation.** A too-tight `gap_sec` splits long rallies and charges the detector twice (a miss plus a false positive). The adaptive `gap_sec` (PIC-33) substantially reduces this on doubles/tournament-length rallies. Still real — now understood as the dominant remaining false-positive mechanism, alongside the `start`-lead-in scoring gap.
2. **Label incompleteness.** Real play that was never marked scores as a false positive — the mechanism behind the entire label-artefact thread (ADR-050/051/053), and then confirmed far more severe than thought on all four videos (ADR-057/058/059/060). Root cause is the old "curate to competitive rallies" habit, which `LABELING.md` warns against. **Fixed 2026-08-23** — all four videos exhaustively relabeled.
3. **Genuine junk**, of two distinct kinds — *phantom crossings* (a tossed ball whose image-y crosses `net_y` without the ball crossing the net) and *courtesy returns* (ball really crosses, but it's dead time). **Turned out to be almost entirely mechanism 2 in disguise** — once labels were fixed, confirmed genuine junk across all four videos dropped to zero (ADR-060).

**Rally length is the hidden variable behind most of this**, and it's driven by format, not camera. Final numbers as of 2026-08-23 (all four videos now relabel-confirmed, not provisional): brickwall is doubles tournament play (21.8s mean rally, 58.1% of the video live); pb_draft_cup is a **singles** match (9.3s, 41.8%); IMG_7743 post-bump and IMG_7744 are casual doubles (37.5% and 24.2% respectively — both far higher than the original ~4–9% figure, which came from the same incomplete labels this whole thread is about). Raw precision is **not comparable across videos with different densities** — a spurious segment lands on real play far more easily when half the video is live. Use the chance-adjusted lift in `EXPERIMENTS.md` when comparing.

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
