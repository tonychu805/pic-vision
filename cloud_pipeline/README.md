# cloud_pipeline/ — the R2 + RunPod path, isolated from the local-GPU pipeline

Added 2026-08-26 at the operator's request: a parallel path to `webapp/`'s
upload → calibrate → detect → rank → reel flow, with inference dispatched to
a RunPod GPU pod via Cloudflare R2 instead of this workstation's local GPU
(the TF2.15 environment `webapp/pipeline.py` currently subprocesses into).

## What's isolated, and why

`webapp/pipeline.py`'s `_run_inference` is the only part of the existing
pipeline that touches local GPU — it shells into
`/mnt/fast_scratch/tf215_env/venv` on this machine. Everything else (drift
check, CFR conversion, and `build_reel`'s detection/ranking/cutting) is pure
CPU logic with no GPU dependency at all.

So "isolated from the local pipeline" means, specifically:

- This directory never imports `webapp/`, never invokes the local TF2.15
  environment, and never runs inference on this workstation's GPU. Nothing
  here can affect or be affected by the existing, working local pipeline.
- **It does reuse** the detector-agnostic downstream logic (`src/drift.py`,
  `src/calib.py`, `src/track.py`, `src/ball.py`, `src/select.py`,
  `src/render.py`, via `scripts/rank_and_reel.py`'s `build_reel`) — this is
  the validated rally-detection algorithm (ADR-060, ADR-063), not "the local
  GPU pipeline." Re-implementing it here to be "more isolated" would just
  reintroduce bugs this project already found and fixed, for no benefit.
- **It runs `scripts/pod_infer.py` unmodified** — copied onto a RunPod pod
  and executed there, instead of subprocessed locally. Same already-correct
  inference code (including the ADR-064 coordinate fix and ADR-065
  throughput fix), different machine.

## Files

- `r2_storage.py` — thin `boto3` wrapper for Cloudflare R2 (upload/download/
  exists). Reached directly, same mechanism validated in `DECISIONS.md`
  ADR-043's update — no RunPod-R2 platform integration exists or is needed.
- `runpod_pod.py` — RunPod pod lifecycle (create, wait for SSH, run commands,
  transfer files, terminate) via the REST API + plain `ssh`/`scp`. GPU type
  is **pinned to `NVIDIA RTX 2000 Ada Generation`** — the same card as the
  local route's workstation (operator's call, 2026-08-26), deliberately with
  no fallback to other types: every prior inference optimization in this
  project was verified "byte-identical output" on the *same* GPU, and
  whether that holds across different GPU architectures (different cuDNN
  kernel selection, floating-point non-associativity) has never been
  checked. Pinning sidesteps that open question rather than needing to
  verify it. The earlier design retried across a few consumer GPU types for
  availability (confirmed 2026-08-26 — a CPU-only pod spec failed repeatedly
  while a GPU pod succeeded immediately); that fallback still exists in
  `create_pod()` for a caller that passes its own `gpu_type_ids` list, just
  not as the default anymore.
- `run_cloud_job.py` — the orchestrator. Mirrors `webapp/pipeline.py`'s
  `run_job` structure: local drift check → local CFR conversion → **upload to
  R2 → RunPod pod runs `pod_infer.py` → results back via R2** → local
  `build_reel()`.
- `pod_r2_helper.py` — copied onto the pod alongside `pod_infer.py`; a small
  standalone script (not an inline `python3 -c` one-liner over SSH, which
  gets fragile fast with nested shell/Python quoting) for the pod's R2
  download/upload calls.
- `setup_venue_calibration.py` — the *only* place calibration logic lives now
  (see below). Not imported by `run_cloud_job.py` at all.

## Calibration

**Corrected 2026-08-26 (twice, same day).** First pass added
`ensure_calibration()` to `run_cloud_job.py`, auto-launching
`calibrate_web.py` on every job missing a `calib.json`. That was an
architectural mistake, caught by the operator: calibration is a **one-time,
per-venue** event — it only needs to change if the camera physically moves
(`DECISIONS.md` ADR-049) — not something tied to the per-*session* job
lifecycle. Auto-triggering it inside `run_cloud_job()` conflated the two.

**Fixed by removing it from `run_cloud_job.py` entirely** and moving it to
its own standalone script, `setup_venue_calibration.py`. Run it once, when a
venue's camera is first mounted:

```
python3 -m cloud_pipeline.setup_venue_calibration \
  --video first-session-from-this-venue.mp4 \
  --out venues/my-venue/calib.json
```

It launches `calibrate_web.py` (the existing standalone browser-click tool,
still independent of `webapp/`) and waits for the save — same mechanism as
before, just relocated — then refuses to run again if the target path
already has a file (`SystemExit`, not a silent skip), since re-running this
per session would be exactly the mistake being corrected.

`run_cloud_job.py` now has **zero calibration logic**. `--calib` is required
again and must point at an already-existing file; if it doesn't exist,
`run_cloud_job()` raises `SystemExit` with the exact command to fix it,
rather than trying to handle it inline. Both failure modes verified live
(missing file → the exact expected error message; already-exists guard on
the setup script → the exact expected error message).

**Not addressed here, out of scope for this fix:** `webapp/app.py`'s local
route still collects calibration fresh, in-browser, *per job* — unchanged,
and arguably has the same "should this really run every session" question,
just not one raised or touched today.

## Prerequisites

`.env` (gitignored, repo root) needs:
```
RUNPOD_API_KEY=...
CLOUDFLARE_R2_ACCESS_KEY_ID=...
CLOUDFLARE_R2_SECRET_ACCESS_KEY=...
CLOUDFLARE_R2_ACCOUNT_ID=...
```

An R2 bucket must already exist (Cloudflare doesn't provision the
account's S3 endpoint until one does — see `DECISIONS.md` ADR-043). Default
bucket name is `test-ingest-runpod` (the one created during today's
connectivity testing); override with `CLOUD_PIPELINE_BUCKET`.

## Status (2026-08-26)

**Fully run end-to-end on real infrastructure, real footage, real live calibration.** Confirmed working:
- R2 upload/download from both a local machine and a real RunPod pod
  (`DECISIONS.md` ADR-043 update).
- RunPod pod creation, SSH access, command execution.
- Calibration setup (`setup_venue_calibration.py`), tested live end-to-end,
  now correctly scoped as a one-time per-venue step, not a per-job one.
- The full setup sequence, timed on a real pod: pod → SSH-ready **13.1s**,
  `pip install tensorflow[and-cuda]==2.15.1` + deps **66.5s**, weights
  download (130MB) **5.2s**, untar **1.4s** — **~86s total**, not the
  "several minutes" this doc originally guessed. Weights upload to R2
  (one-time, cached after) **29.5s**.

Two real bugs found and fixed doing this measurement, not hypothetically:
the weights tarball preserved this machine's uid/gid, and extracting it as
root on a fresh pod failed outright (`tar: ... Operation not permitted`) --
fixed with `--no-same-owner`. And `run_cloud_job.py` never loaded `.env`, so
a real invocation would crash with `KeyError` unless the caller manually
sourced it first -- fixed to match `src/verify.py`'s existing `load_dotenv()`
pattern.

**Run end-to-end for real, 2026-08-26 — no piece of this is untested anymore.**
A genuinely fresh test, deliberately avoiding any prior artifact: a random
5-minute clip cut from raw, previously-untouched footage
(`videos/raw/brickwall-SEMI.mp4`), a *live* calibration the operator clicked
through in a real browser session against `setup_venue_calibration.py`
(RMSE 0.166ft), then one real `run_cloud_job.py` invocation start to finish
— drift check, CFR convert, upload, pod creation, TF2.15 install, `pod_infer.py`
inference, results back via R2, `build_reel()`. **Exit code 0.** 13 candidate
rally segments detected, both reels (`highlight.mp4`, `highlight_by_rank.mp4`,
209.5s each) produced and playable, `manifest.json` written, ranking scores
look sane (0.011–0.850, same shape as every other scored video this project
has produced). Sent the top-ranked clip to the operator directly for a real
playback check (this project's own standing rule — a stills/numbers-only
verdict isn't good enough, `feedback_video_review_method`).

One real, measured number worth being honest about: **pod inference ran at
29.4fps (wall-clock ratio ~1.02×, essentially real-time)** — 9000 frames in
5.1 min for 5 min of source footage. That's slower than the local RTX 2000
Ada's measured 36.2fps for the same masked config (`ADR-065`) despite being
the same GPU model pinned specifically for consistency. Neither number clears
`PRD.md`'s ≤0.5× wall-clock target; this cloud path is currently *slower*
than the already-short-of-target local path, not faster.

**Root-caused same day** (`scripts/profile_pod_infer.py`, `DECISIONS.md`
ADR-043 final update): GPU inference time is essentially identical on pod vs.
local (confirms the GPU pin works as intended), and decode/disk I/O is a
small fraction of the loop on both — the earlier "likely network/disk I/O"
guess was wrong. **The entire gap is single-threaded CPU preprocessing**
(`prep3()`'s `cv2.resize` + numpy reshape) running ~43% slower per call on
the pod's shared/virtualized cores despite the pod having far more vCPUs (48
vs. local's 16) — vCPU count doesn't help a single-threaded stage.

**Fixed same day.** `scripts/pod_infer.py` now decodes+preprocesses the next
trio on a background thread while the main thread runs GPU inference on the
current one, so the two costs overlap instead of stacking serially — pure
scheduling change, verified byte-identical CSV output against the pre-change
version (both locally and on a real pod, including the non-multiple-of-3
tail-frame case). **Real measured result: 29.4fps → 74.8fps on a real pod**
(local also improved, 36.4→66.8fps). A 10-min/18,000-frame chunk now takes
~4 min of inference instead of ~10.2 min — comfortably inside the 600s
chunk budget even before the ~86s pod-setup tax is addressed.

**Still open: the ~86s per-job pod-setup tax** (13.1s boot + 66.5s
`pip install tensorflow[and-cuda]` + 5.2s weights download + 1.4s untar),
paid on every job since `run_cloud_job.py` creates and tears down a fresh
pod each time. Considered three shapes for the rolling-10-min-chunk
production architecture (`ADR-066`): pod-per-job (today — safest/most
isolated, but pays the tax every chunk), pod-per-session (amortizes the tax
across a session's back-to-back chunks, but needs session-lifecycle/watchdog
logic this project has never built or tested for multi-hour GPU-memory
stability), and pod-per-day (rejected — realistic booking gaps between
separate sessions mean paying for idle GPU-hours with no benefit over
per-session, plus a wider crash blast radius).

**Tried the pre-baked pod image — cold start lost, but caching won on repeat use.** Built
`cloud_pipeline/Dockerfile` (base image + `boto3`, `opencv-python-headless`,
`tensorflow[and-cuda]==2.15.1` pre-installed, matching `POD_SETUP_CMD`
exactly), pushed it to Docker Hub (`tonychu805/pic-vision-tracknet:tf215-cuda118`).
Turned out **17.7GB total, with a 4.76GB new layer** on top of the base
image (`tensorflow[and-cuda]`'s bundled NVIDIA CUDA runtime wheels are the
bulk of it) — much larger than expected.

First pod (cold): pod-create → ready-to-run **113.4s**, worse than the
~79.6s baseline (13.1s boot + 66.5s install). Read initially as a loss.
**Then tested 5 more pods, ~20s apart over ~10-15 minutes: 70.1s, 20.4s,
39.5s, 75.9s, 57.7s — average ~52.7s, a real ~34% win over baseline**, every
one faster than the cold run. The image caches somewhere in RunPod's pool
after the first pull and later pod creations benefit — not a one-off lucky
host match, it held across 5 separate creations.

**Still open, not yet switched:** whether that caching survives the longer
gaps a real production system would have between jobs (hours, not the ~15
minutes these tests spanned) is untested. `DEFAULT_IMAGE` stays on the
generic base until that's checked. Treat neither the 113.4s nor the ~53s
average as the final word on their own.

## Usage

Once per venue, the first time (see Calibration above):

```
python3 -m cloud_pipeline.setup_venue_calibration \
  --video first-session.mp4 --out venues/my-venue/calib.json
```

Then, per session, reusing that same calibration file every time:

```
python3 -m cloud_pipeline.run_cloud_job \
  --video path/to/session.mp4 \
  --calib venues/my-venue/calib.json \
  --target-sec 300 \
  --session-id my-session \
  --out-dir cloud_pipeline/jobs/my-session
```
