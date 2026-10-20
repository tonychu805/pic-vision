# Phase-1 latency test (serve gate + Marathon/Firefight) — isolated from production

Answers "can the new pose stage make reels in time?" **without touching production.** New RunPod endpoint only;
reads a real session read-only; writes to `phase1_out/`; no reel row, no delivery, no DB write.

Files:
- `pose_handler.py` — pose inference, runs **on the RunPod worker** (serverless `handler()`; standalone, no `src/` imports).
- `Dockerfile` — builds the endpoint image (ultralytics 8.4.120, weights baked in).
- `bench_pose_endpoint.py` — **run here**; cold-start + warm-throughput of the endpoint.
- `replay_phase1.py` — **run here**; full chain end-to-end → `phase1_out/<sid>.json`.

## Step 1 — build & push the image (your machine with Docker, or RunPod's GitHub build)
```
docker build -t <registry>/pic-pose:phase1 scripts/phase1_test
docker push  <registry>/pic-pose:phase1
```

## Step 2 — create a NEW serverless endpoint (RunPod console)
- Image: `<registry>/pic-pose:phase1`
- GPU: same class / $0.50 cap as the TrackNet endpoint (so throughput reflects production)
- This is a **separate endpoint** — do not touch the TrackNet one. Note its endpoint id.

## Step 3 — a presigned R2 URL for one real session's video
Any session already uploaded. The handler downloads it once per call. (Or bake a video into the image and use
`--video-path` instead of `--video-url`.) Use a session that also exists under `cache/pgc_fieldtest/` so the
windows line up — e.g. `a96cbae3`.

## Step 4 — benchmark the GPU hop (the real unknown), from the repo root
```
export RUNPOD_API_KEY=...
.venv/bin/python scripts/phase1_test/bench_pose_endpoint.py \
  --endpoint <endpoint-id> --session a96cbae3 --video-url "<presigned-r2-url>"
```
Reports **COLD wall** (reel-ready from a cold endpoint) and **WARM wall** (per-session gate, hot).

## Step 5 — end-to-end replay through the endpoint
```
.venv/bin/python scripts/phase1_test/replay_phase1.py \
  --session a96cbae3 --endpoint <endpoint-id> --video-url "<presigned-r2-url>"
```
Writes `phase1_out/a96cbae3.json`: segments, warmup dropped, badges, per-stage timing. Delivers nothing.

## Go / no-go
Compare COLD + WARM wall to the reel turnaround target. Local baseline (unthrottled GPU) was ~1 min of serve
gate for ~15 candidates; RunPod under the cap is the number that matters. `phase1_out/` is scratch — don't commit it.

## Sanity check without RunPod
`replay_phase1.py --session a96cbae3` (no `--endpoint`) runs the whole chain on local GPU — validates logic/output,
not the RunPod latency.
