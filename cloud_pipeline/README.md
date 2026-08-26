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
  transfer files, terminate) via the REST API + plain `ssh`/`scp`. Retries
  across a few GPU types on creation, since community-cloud capacity
  fluctuates (confirmed 2026-08-26 — a CPU-only pod spec failed repeatedly
  on availability while a GPU pod succeeded immediately).
- `run_cloud_job.py` — the orchestrator. Mirrors `webapp/pipeline.py`'s
  `run_job` structure: local drift check → local CFR conversion → **upload to
  R2 → RunPod pod runs `pod_infer.py` → results back via R2** → local
  `build_reel()`.
- `pod_r2_helper.py` — copied onto the pod alongside `pod_infer.py`; a small
  standalone script (not an inline `python3 -c` one-liner over SSH, which
  gets fragile fast with nested shell/Python quoting) for the pod's R2
  download/upload calls.

## Calibration

Closed 2026-08-26, tested live (not just imported): `run_cloud_job.py` now calls
`ensure_calibration()` first. If `--calib`'s path already has a file, it's reused
as-is. If not, it launches `calibrate_web.py` — the existing standalone
browser-click tool, already independent of `webapp/`, so reusing it doesn't
reintroduce the coupling the isolation design avoided — and polls for the file
to appear rather than waiting for the process to exit (`calibrate_web.py`
blocks forever on `serve_forever()`; there's no clean exit signal to wait on
otherwise). Once the operator clicks the 12 court points + 2 net points and
hits Save in the browser, the file appears, the subprocess is terminated, and
the job continues automatically.

`--calib` is no longer required — it defaults to `<out-dir>/calib.json`.
`--calib-at` (default 60s) picks which frame to calibrate from; `--calib-port`
(default 8765) which port the browser server listens on.

Verified directly: launched `ensure_calibration()` against a real video,
confirmed the server actually came up (`GET /` → 200), POSTed the same
save payload a real browser click would send, confirmed a real `calib.json`
was written (RMSE 0.345ft, a real value, not a stub), confirmed the polling
loop detected it and terminated the subprocess (port stopped responding
afterward), and confirmed the already-calibrated path returns immediately
without launching anything.

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

**Built, not yet run end-to-end with real GPU inference.** What's confirmed
working, on real infrastructure, as of today:
- R2 upload/download from both a local machine and a real RunPod pod
  (`DECISIONS.md` ADR-043 update).
- RunPod pod creation, SSH access, command execution (same session).

**Not yet tested:** installing TF2.15 fresh on a pod and running real
TrackNet inference through `pod_infer.py` there — this is the one step that
combines everything above and hasn't been exercised live. Expect the first
real run to spend several extra minutes on the TF2.15 install (no way around
it without a custom pre-built image, which doesn't exist yet).

## Usage

```
python3 -m cloud_pipeline.run_cloud_job \
  --video path/to/session.mp4 \
  --target-sec 300 \
  --session-id my-session \
  --out-dir cloud_pipeline/jobs/my-session
```

If `cloud_pipeline/jobs/my-session/calib.json` doesn't exist yet, this will
print a URL, wait for you to calibrate in a browser, then continue on its own.
Pass `--calib path/to/existing.json` to reuse one instead.
