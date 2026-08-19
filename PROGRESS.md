# Progress Log

Plain-language record of what's been built and decided, newest first. Git history has the detail; this is the map. Metric-producing runs go in [`EXPERIMENTS.md`](./EXPERIMENTS.md); decisions in [`DECISIONS.md`](./DECISIONS.md). Doc-authority map (which file governs what) lives in [`CLAUDE.md`](./CLAUDE.md).

## Phase gate tracker → [`CHECKLIST.md`](./CHECKLIST.md)

## ▶ NEXT SESSION — start here

**Status (2026-08-20): the precision-ceiling artefact is confirmed and closed out on all four cameras; process integrity (eval-set locking, labelling noise) is now measured too. Read every number below against the noise floor in the last bullet before trusting a fine-grained comparison.**

- **Precision-ceiling artefact (ADR-050/051): closed.** The 2026-08-17 "precision pinned at 0.25–0.29" reading does not survive playback review on any of the four cameras — pb_draft_cup 0.27→0.59, brickwall 0.59→0.64, IMG_7743 0.29→0.44, IMG_7744 0.25→0.54. Full detail in the 2026-08-19 entries below.
- **FP anatomy (PIC-37): done.** Remaining false positives on IMG_7743/7744 are 26% fragment, 48% real dead-time crossing, 21% noise, 5% ambiguous — the dominant mechanism is real crossings during dead time (PIC-31's territory), not phantom crossings, reversing the working assumption from brickwall's framing. Two flagged long segments playback-confirmed as warm-up, not missed rallies.
- **PIC-31 candidate #1 (duration/rate threshold): tested, rejected.** Real rallies and real dead-time crossings overlap too much to separate this way, on any video, two methods. Candidate #3 (a non-ball signal) is what's left — brainstormed, unscoped, in PIC-42.
- **Eval-set roles locked (PIC-17/ADR-052).** `sessions.jsonl` now exists: `eval`=IMG_7743 (locked, never used to pick a parameter again), `dev`=brickwall/pb_draft_cup/IMG_7744. Was overdue three days before being caught.
- **`min_crossings=6` re-derived dev-only (PIC-43, partial).** Of 16 combinations swept, `min_crossings=6` + adaptive `gap_sec` is the only one with zero regressions on any `dev` video, and holds flat on the untouched `eval` check. `court_wedge`'s cap/spread constants are the one piece still unchecked.
- **Labelling self-consistency measured for the first time (PIC-6), and this is the one to actually internalize:** blind-relabelling the same 5 minutes found only **~1/3 agreement on whether a stretch is a rally at all** (boundary placement, by contrast, was fine — ~0.6s median). That noise floor is bigger than several of the fine precision/recall differences chased this week (e.g. `min_crossings=6` vs `7`). Nothing above is wrong because of this, but treat any comparison finer than roughly this margin as unproven until corroborated another way.

**Open, unblocked work:** PIC-36 (fp anatomy on `pb_draft_cup`, tool exists), PIC-38 (chance-adjusted lift recompute for `pb_draft_cup`), PIC-39 (adversarial review of the label-artefact conclusion — now higher-stakes given the labelling-noise finding above, do this before trusting anything further), PIC-40 (wire `court_wedge` into `src/cut.py`'s CLI), PIC-43's remaining `court_wedge` piece. PIC-31 needs a steer on which PIC-42 candidate to pursue before more work can happen there.

**Open decision, not yet made:** this is now the strongest evidence so far for promoting `adaptive_gap` from opt-in to the shipped default — a genuine dev-search/eval-check result, not just "tested on the 4 videos that happen to exist." Left as a call for whoever picks this up next.

**Linear triage done 2026-08-19:** PIC-31 bumped to Urgent (48% of IMG_7743's remaining FPs are its exact failure mode — real dead-time crossings, not phantom crossings); PIC-34 dropped to Medium (0 of 46 examined FPs showed its signature); PIC-33/36/38/39/40 moved Backlog→Todo (all unblocked). PIC-33 is now done (see below); next up by priority is PIC-31 or PIC-6 (once a day has passed).

**Tool built this session, useful for any future gap-review pass:** `label_web.py`'s GRADE mode can now re-mark a candidate's boundary in place (`s`/`e` while grading) instead of only keep/drop — the original detector timestamp is preserved as `detector_start`/`detector_end` alongside the corrected one, never silently lost. Needed because a detector segment spans only first-to-last net crossing, so real rallies are routinely truncated at both ends, not just missing entirely.

**Also flagged, not yet fixed:** `src/cut.py`'s CLI still derives the older flat `court_x_range` from `--calib`, not the preferred `court_wedge` — a real `python3 -m src.cut` run today would score worse than the numbers above unless `in_court=court_wedge(calib)` is wired in by hand (the 2026-08-19 rescore did this via a scratch script, not through `cut.py` itself).

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
- **Built + tested (98 tests):** eval harness (IoU matching at 0.5, detection + selection tables) · calibration (order-independent, browser + CLI, marks the net) · TrackNet prediction parsing (including per-detection blob size/confidence) + court-wedge gating + tracker confirmation · scoring against hand labels on 4 independent camera angles · adaptive per-video `gap_sec` (PIC-33, opt-in).
- **Not built:** a signal that tells a real rally apart from a quick failed exchange (PIC-31 — IMG_7744's open problem); selection/ranking (competitive vs. casual — Phase 1, still gated on precision).
- **Camera-drift detection built** (`src/drift.py`, `scripts/check_drift.py`, PIC-29 closed) — run `check_drift.py` on any new footage *before* calibrating or labelling it.
- **Tried and rejected:** blob size/confidence as a clutter filter (PIC-2, 2026-08-17) — doesn't separate real balls from junk on this footage.
- **Decided recently:** ADR-046 (TrackNet is the active detection path), ADR-048 (`min_crossings=6` is the one canonical default, reconciled across code+docs), ADR-049 (a camera bump invalidates calibration going forward — detect it, don't tune around it), ADR-050 (a precision number is not admissible until its false positives have been reviewed at playback speed — now confirmed on all 4 scored cameras as of 2026-08-19, not just the 2 it was based on), ADR-051 (the pre-2026-08-18 precision ceiling is fully retracted, confirmed on all 4 cameras), ADR-052 (eval-set roles locked — IMG_7743 is `eval`, may never again be used to pick a parameter; PIC-43 open to re-derive the shipped constants honestly).
- `main` pushed to `origin`, no open branches.

---

## 2026-08-20 — PIC-6: labelling self-consistency measured for the first time — presence, not boundaries, is the real noise floor

- Blind-relabelled the prepped 5-minute clip (`videos/IMG_7743_consistency_0-300s.mp4`), a day after prep as planned. 5 rallies originally, 7 on the blind repeat, only **3 of 9 distinct rally-windows agreed on by both** (2 missed on repeat, 4 found that weren't marked the first time).
- Boundary spread on the 3 agreed rallies is small (~0.6s median) — close to the project's own ±0.5s target, not the concern.
- **The bigger, previously-unmeasured source of noise is whether a stretch counts as a rally at all** — roughly a third agreement, bigger than several of the fine precision/recall differences chased this week (e.g. PIC-43's `min_crossings=6` vs `7`, ~0.05 precision). Doesn't invalidate this week's conclusions, but any comparison finer than roughly this margin should be read with real skepticism.
- One data point (one labeller, one 5-minute stretch) — not a precise constant. Feeds directly into PIC-39 (adversarial review, still open).
- Recorded in `EXPERIMENTS.md`, `LABELING.md`. PIC-6 closed.

---

## 2026-08-19 (truly final) — PIC-43: min_crossings re-derived dev-only, confirms the shipped default

- Swept `min_crossings` ∈ {3..10} × {fixed `gap_sec=3.0`, adaptive} = 16 combinations, scored against `dev` only (brickwall, pb_draft_cup, IMG_7744) — `eval` (IMG_7743) untouched throughout.
- **`min_crossings=6` + adaptive `gap_sec` is the only combination that improves or holds on every `dev` video with zero regressions.** `min_crossings=7`/adaptive scores higher on average (0.771 vs 0.727 F1) but costs real recall on `pb_draft_cup` and `IMG_7744` — a genuine tradeoff, documented as an alternative, not selected.
- Checked against `eval` (IMG_7743): 0.44/0.75 (fixed) vs 0.44/0.74 (adaptive) — flat. The number picked on one video out of necessity, three days before `dev`/`eval` existed, survives being re-derived blind on three different ones.
- `court_wedge`'s cap/spread constants remain the one unchecked piece of PIC-43's original scope.
- Recorded in `EXPERIMENTS.md`, `CHECKLIST.md`. Linear PIC-43 updated with the full table.

---

## 2026-08-19 (final) — Eval-set roles locked (PIC-17/ADR-052); PIC-31's duration/rate idea tested and rejected

- **PIC-31 candidate #1 rejected.** A self-calibrated minimum-duration/crossing-rate threshold (no fixed constant — the same trap `gap_sec` fell into) was checked against all 4 videos, two unsupervised methods, labels used only to score afterward. No clean separation anywhere; the faint real signal (slower pace leans toward "real") would misclassify 24–50% of real rallies as junk if used as a filter. Candidate #3 (a non-ball signal) is what's left — brainstormed and filed as PIC-42 (backlog): serve-shaped ball arc, double-bounce at rally end, reviving the frozen player-position signal, audio score-calling, audio hit rhythm.
- **PIC-17 closed, ADR-052.** Caught mid-session: today's own `gap_sec`/duration-threshold sweeps (~100+ parameter combinations total) were tuning and evaluating against the same videos, exactly the problem this issue named on 2026-08-16 and flagged as still-open when checking Linear outside the `Rally Detection Accuracy` project specifically (a full-team check that hadn't been done this session until asked). `sessions.jsonl` now exists and is populated: `eval`=IMG_7743 (locked), `dev`=brickwall/pb_draft_cup/IMG_7744. The currently shipped `min_crossings`, `gap_sec` base, and `court_wedge` constants were tuned on IMG_7743 before this lock existed and can't be retroactively cleaned — PIC-43 tracks re-deriving them dev-only, which is the actual outstanding risk, not just the paperwork of writing roles down.

---

## 2026-08-19 (later still) — Adaptive gap_sec (PIC-33): self-calibrating design beats the fixed constant on all 4 videos

- **First idea (per-crossing local adaptivity — scale the allowed gap by the median interval already seen within the current cluster) tested and rejected**: every one of 60 parameter combinations scored worse than the fixed `gap_sec=3.0` baseline on all three videos checked. Root cause: most in-rally gaps are short, so a multiple of the local median ends up *tighter* than 3.0s most of the time — the opposite of what's needed.
- **Second design, validated**: `src.ball.adaptive_gap_sec` — two passes. Pass 1 clusters at the existing constant to get a coarse (still partly fragmented) estimate of the video's own typical rally span; pass 2 nudges the gap toward that estimate, scaled by `k=0.10` relative to a `ref_duration=10.0` reference, clamped to `[2.0, 5.0]`, and re-clusters.
- **All four scored videos improve or hold** — the property the earlier, rejected `gap_sec=4.0` proposal never had: brickwall 0.64/0.80→**0.76/0.91**, pb_draft_cup 0.59/0.72→**0.65/0.72**, IMG_7744 0.54/0.65→**0.64/0.70**, IMG_7743 (sanity check, not a formal criterion) ~unchanged. Brickwall's fragment-type false positives more than halve, 12→5 — the actual mechanism moved, not just the aggregate number.
- **Shipped as opt-in** (`rally_segments_from_predictions(..., adaptive_gap=True)`, `python3 -m src.cut --adaptive-gap`, both default off) rather than the new shipped default — `k`/`ref_duration`/etc. were fit against the same four videos being validated against, and a fifth, held-out video would make the promotion decision solid rather than a repeat of the `gap_sec=4.0` overfit risk. 4 new tests, suite 94→98 green.
- Linear: PIC-33 closed with these results.

---

## 2026-08-19 (later) — FP anatomy on IMG_7743/7744 (PIC-37): real dead-time crossings, not phantom crossings, are the dominant junk mechanism

- **Built `scripts/fp_anatomy.py`**: mechanically flags "fragment" false positives (overlap/adjacent to a real label — a clustering artefact, not a detector error), then plots every remaining candidate's image-y/image-x trajectory against `net_y` so the rest can be read by shape rather than guessed from aggregate stats (which the 2026-08-18 brickwall entry already showed can be misleading).
- **Result across all 62 remaining false positives** (IMG_7743 pre-bump 38, post-bump 13, IMG_7744 11): 26% fragment, 48% real dead-time crossing (smooth, physically coherent net crossings — courtesy returns / between-point practice), 21% noise/hallucinated, 5% ambiguous. Post-bump in particular is 12/12 real dead-time crossings — nothing there is a detector flaw.
- **This flips the working assumption from the 2026-08-18 brickwall framing**: phantom crossings looked like the leading junk mechanism going in; on this video the leading mechanism is real crossings during dead time, which is PIC-31's territory (needs a game-state signal), not PIC-34's (a geometry fix). No candidate in this batch showed a clean phantom-crossing signature.
- **This is a plot read, not a playback verdict** — flagged two long pre-bump segments (24.4s/28 crossings, 17.9s/18 crossings) that look like real rallies in the plot and deserve an actual watch before trusting the table further; if either is a missed rally rather than dead-time practice, that's a recall finding on top of everything else.
- Closes PIC-37 in Linear (caveats noted in the completion comment — the two flagged segments still need a playback check before this is final).

---

## 2026-08-19 — IMG_7743/7744 re-reviewed; precision-ceiling artefact confirmed on all 4 cameras

- **Reviewed all 78 outstanding gap candidates** (IMG_7743 pre-bump 49, post-bump 12, IMG_7744 17) at playback speed via `label_web.py`, per ADR-050's top follow-up. Kept 21 + 0 + 10; merged into labels via `review_gaps.py merge`: IMG_7743 pre-bump 22→42, post-bump unchanged at 11 (every candidate there was junk), IMG_7744 10→20.
- **Built boundary-correction into `label_web.py`'s GRADE mode** (`s`/`e` re-marks the current candidate's true start/end in place; original detector timestamp preserved as `detector_start`/`detector_end`, never discarded or duplicated into a second entry) — needed because a detector segment only spans first-to-last net crossing, so real rallies are often truncated at both ends, not just missing outright.
- **Rescored** both (shipped config, `court_wedge` gate, called directly via `src.tracknet.rally_segments_from_predictions` against the cached `predictions_k14.csv` — no re-inference): IMG_7743 combined precision 0.29→**0.44** (recall 0.79→0.75, a boundary-widening side effect, not a regression), IMG_7744 precision 0.25→**0.54** (recall 0.60→0.65). Full numbers and mechanism notes in `EXPERIMENTS.md`.
- **Closes ADR-050 follow-up #1** — the label-completeness artefact first found on pb_draft_cup/brickwall (2026-08-18) is now confirmed on all four scored cameras, none is an exception.
- **Still open:** the fragment/boundary/junk false-positive anatomy (done for brickwall) hasn't been run on IMG_7743/7744/pb_draft_cup; the label-artefact conclusion still hasn't been through adversarial review; `src/cut.py`'s CLI still doesn't wire up `court_wedge` (only the older flat `court_x_range`), so a plain `python3 -m src.cut` run would underperform these numbers today.

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
