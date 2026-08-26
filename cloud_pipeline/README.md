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

**Setup path measured end-to-end for real; the actual inference call itself
still isn't.** Confirmed working, on real infrastructure:
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

**Not yet tested: the actual `pod_infer.py` inference call on a pod** — the
one piece that combines a real video with the now-confirmed environment.
Everything upstream of it (get a working TF2.15+GPU environment ready on a
fresh pod, in under 90 seconds) is now measured, not assumed.

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
