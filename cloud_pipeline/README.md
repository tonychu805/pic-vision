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

## Calibration — not symmetric with the local route

`run_cloud_job.py` takes `--calib` as a **required, pre-existing file path** — unlike
`webapp/app.py`, it has no calibration UI of its own. Produce `calib.json` first via
`calibrate.py`/`calibrate_web.py` (the standalone CLI tools), or reuse one already
produced by a `webapp/` job. This is a real gap, not an oversight to route around
silently — a browser-based calibration step for this path doesn't exist yet.

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
  --calib path/to/calib.json \
  --target-sec 300 \
  --session-id my-session \
  --out-dir cloud_pipeline/jobs/my-session
```
