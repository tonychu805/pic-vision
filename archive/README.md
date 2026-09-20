# Archive — retired code and process

Retired code and process kept for reference, not maintained. Four groups so
far: the YOLO ball-detection pipeline, one superseded calibration tool, one
abandoned workflow template, and one rejected performance experiment.

## YOLO ball-detection pipeline

Retired 2026-08-12. The YOLO-based ball detection path produced only 5 crossings
in the benchmark rally window where TrackNet finds 25 (EXPERIMENTS.md 2026-08-12).
TrackNet inference on RunPod GPU is now the default detection route (ADR-046).

**Kept for reference, not active:**
- `yolo_detect.py` — `detect_ball` / `detect_candidates` from `src/ball.py`
- `yolo_pipeline.py` — `detect_rallies` / `rally_segments_from_candidates` from `src/pipeline.py`
- `tests/test_yolo_pipeline.py` — unit tests for the above
- `scan_crossings.py` — moved here 2026-08-20 (`EXPERIMENTS.md`, found by `/committee-review`).
  Imported `detect_candidates` from `src/ball.py`, which had already moved to
  `yolo_detect.py` above when the YOLO path was retired — the import was broken
  (`ImportError` on any invocation) and had been for some time before anyone noticed.
- `debug_detections.py` — moved here 2026-08-20, same finding. Rendered annotated
  frames using a YOLO model's ball detections + net_y overlay. Ran fine (unlike
  `scan_crossings.py`), but visualized the retired detector, not TrackNet — anyone
  using it to debug the active pipeline would have silently gotten the wrong
  detector's output. If TrackNet-based visual debugging is wanted, it should be
  rebuilt against `src/tracknet.py`'s predictions, not resurrected from here.

The backend-agnostic signal-processing functions (`crossing_times`, `cluster_crossings`,
`count_crossings`, `net_line_y`, `ball_box_ok`) remain in `src/ball.py` — both
pipelines use them unchanged.

## Superseded calibration tool

- `calibrate_headless.py` — moved here 2026-08-21 (repo-hygiene review). A
  no-display calibration path: save a still frame, type each point's pixel
  coordinates back in by hand after reading them off in an external image
  viewer. `calibrate_web.py` solves the identical no-display problem with a
  browser-click UI instead of hand-typed coordinates and has had real bugs
  found and fixed against it since; this file was untouched and unreferenced
  from the commit that added it onward. If `calibrate_web.py` is ever
  unavailable (no HTTP access to the machine), this is the fallback to revive.

## Abandoned workflow template

- `TALLY.md` — moved here 2026-08-21 (documentation-maintenance review). A
  per-session watch-through template; its own instructions said to copy it to
  `tallies/session-NNN.md` before labeling new footage. Never once done —
  `tallies/` held nothing but a `.gitkeep` after 3+ weeks of near-daily
  footage work, so the directory is gone too. Revive if this project starts
  onboarding new camera setups or operators who'd benefit from a structured
  first-look pass; for this project's own footage, direct playback review has
  been the actual method used throughout (see `CLAUDE.md`'s "Verifying a
  root-cause claim" section).

## Rejected performance experiment

- `pod_infer_batched.py` — moved here 2026-08-25 (`DECISIONS.md` ADR-065).
  Investigating a real inference-throughput regression (23fps vs. a
  documented 58fps benchmark on the same GPU), a live probe suggested the
  GPU was idle waiting on CPU-bound per-frame preprocessing. This script
  tested the fix that theory implied — batch multiple frame-trios into one
  `model.predict()` call — and made things *slower*, not faster, which
  correctly disproved the theory rather than confirming it. The real cause
  (Keras's `.predict()` API itself carries fixed per-call overhead
  independent of batch size) was found afterward and fixed directly in
  `scripts/pod_infer.py` (a `tf.function`-wrapped direct model call). Kept
  as a documented negative result — re-batching this call has already been
  tried and shown not to help, twice (once with `.predict()`, once with
  `tf.function` — see `EXPERIMENTS.md` 2026-08-25).

## Retired experiment: LLM-judged rally verification

- `verify.py` (+ `tests/test_verify.py`) — moved here 2026-09-06
  (`DECISIONS.md` ADR-085). Built 2026-08-16 to have Gemini Flash watch a
  clip and judge "rally or dead time", with the aim of cutting the hand-
  labelling cost. Never adopted, for two independent reasons:
  1. **The verdicts moved with the video encoding, not the play.** The same
     footage re-encoded differently got different answers — so the signal
     being measured wasn't rally-vs-dead-time.
  2. **It was never scored.** PIC-10 (score it against hand labels) was
     blocked on a Google AI Studio spend cap and never unblocked, so there
     is no precision/recall number for it at all.
  Nothing in the pipeline ever imported it — only its own test did. Retired
  along with its `GOOGLE_API_KEY` (removed from `.env`/`.env.example`) and
  the `google-genai` dependency, since it was the sole user of both.
  Before rebuilding this: reproduce finding 1 first. An automatic judge
  whose answer depends on the encoding will quietly corrupt labels, which
  is worse than labelling by hand — see `project_labeling_noise_floor`'s
  wider point that labelling disagreement is already this project's
  biggest measurement error.

## Retired cloud path: the SSH-driven pipeline

Moved here 2026-09-20 (`PIC-139`, `DECISIONS.md` ADR-110). The original
RunPod route: this workstation did the drift check and CFR convert, uploaded
to R2, created a pod, then SSH'd in to run inference and cut the reel.
Superseded by ADR-093's self-driving pod, where `job_runner.py` hands a pod
everything it needs up front and `pod_driver.py` runs the job on the pod
itself with no inbound SSH at all.

**Do not run `run_cloud_job.py`.** It is still importable and still runnable
from here — `REPO_ROOT` resolves identically from `archive/` — and it uploads
the operator's video to the **public** bucket, which since `PIC-153` is the
one `cdn.picvisionai.com` fronts. Running it publishes venue footage. That
gap was found on 2026-09-18, recorded in the file's own `BUCKET` comment, and
deliberately never fixed because the path was already dead.

**Kept for reference, not active:**
- `run_cloud_job.py` — the orchestrator. Its last change (the day it was
  retired) moved the R2 credentials out of the SSH command string, where they
  had been sitting in the process table of *both* the pod and this
  workstation for every transfer — 4 to 15 per job. Fixed, tested, never run
  against a real pod.
- `pod_r2_helper.py` — the pod-side R2 transfer script it scp'd over.
  `pod_driver.py` uses `boto3` directly instead.
- `pod_cut.py` — the pod-side reel cutter it scp'd over. `pod_driver.py`
  absorbed this; its own docstring describes itself as "everything
  `run_cloud_job.py` used to do by SSH'ing into a pod".
- `run_desktop_job.py` — `PIC-68`'s CLI wrapper, spawned by
  `desktop/electron/pipeline.js` to run a cloud job from the desktop app.
  Already dead for the desktop path since ADR-084 made the venue agent thin:
  `pipeline.js` no longer spawns any Python at all, and only a comment about
  it remains there. It was the last caller of `webapp/pipeline.py`'s
  `run_cloud_job()`, which went at the same time.
- `cloud_upload.html` — the Flask dashboard's cloud upload page, served by
  the `/cloud` route removed from `webapp/app.py`.
- `tests/test_run_cloud_job_secrets.py` — the seven paired tests written for
  the credential fix above (three that no secret reaches the command, four
  that the credentials still arrive, quoted). Not collected: `pytest.ini`
  restricts `testpaths` to `tests/`.

**Deliberately NOT archived:** `cloud_pipeline/venues/*/calib.json` and the
`/cloud/new-venue` calibration flow in `webapp/app.py` that writes them.
Three venues' worth of hand-clicked calibration is data this project treats
as expensive to lose (`CLAUDE.md`), and that flow touches neither R2 nor a
pod. `cloud_pipeline/runpod_pod.py` also stays — `job_runner.py` uses it to
create pods on the live path.

**What this does not affect.** The live pipeline ships source to the pod as a
tarball, so a file need not be imported to be load-bearing — checked
explicitly. `job_runner.py`'s `POD_DEPS_FILES` contains `pod_driver.py`,
ten `src/` modules and five `scripts/` modules, and none of the files above.
