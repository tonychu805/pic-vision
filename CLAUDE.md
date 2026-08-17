# pic-vision — project conventions

Pickleball Rally Cutter: turns a two-hour fixed-camera pickleball session into a highlight reel from one command. This is a **prototype** (see `PRD.md` §1) — one operator, one camera, one court, CLI only.

## Docs map — which file is authoritative for what

| Question | Read this |
|---|---|
| What and why (requirements) | `PRD.md` |
| How it's built (architecture, repo layout) | `TECH_SPEC.md` |
| Why a past decision was made | `DECISIONS.md` (ADR log, append-only) |
| What a specific run measured | `EXPERIMENTS.md` (append-only) |
| What's built vs. not, gate status | `CHECKLIST.md` |
| Rally-labeling rules | `LABELING.md` |
| Post-prototype direction (exploratory, not committed) | `STRATEGY.md` |

Record every scored run in `EXPERIMENTS.md`, even — especially — bad numbers; the point is to stop re-learning the same thing twice. A durable conclusion from an experiment gets an ADR in `DECISIONS.md` that links back to it.

## Pipeline state

TrackNet (RunPod GPU inference, `src/tracknet.py`) is the active ball detector. The YOLO path is retired to `archive/` and not maintained.

Detection flow: `predictions.csv` → court gate (`src/calib.py`'s `court_wedge`, perspective-aware — prefer this over the older flat `court_x_range`) → `track_ball` (teleport/re-acquisition confirmation) → `crossing_times` → `cluster_crossings`. Shipped default: `gap_sec=3.0`, `min_crossings=6` (tuned on IMG_7743 — see `DECISIONS.md` ADR-048).

## Scoring rallies

Match predictions to labels at **IoU ≥ 0.5** (`TECH_SPEC.md` §11) — that's the spec'd threshold. Looser thresholds (0.3) have shown up informally in past `EXPERIMENTS.md` entries; treat any precision/recall number in there as IoU≥0.3 unless the entry says otherwise, and use 0.5 for anything new.

## What's committed vs. regenerated

See `.gitignore` for the full list. In short: commit `eval/labels/*.jsonl` (hand labels — ground truth) and `calib/*.json` (per-camera calibration — expensive manual re-click if lost). Never commit video (`*.mp4`/`*.MOV`/`*.mkv`), `cache/`, or `clips/` — all regenerable from footage + `scripts/pod_infer.py`.

## Testing

`python3 -m pytest -q` or `make test`. Tests live in `tests/`.

## Verifying a root-cause or precision/recall claim

Judge rally-vs-dead-time calls from actual video playback, not still frames — a stills-based verdict has already been wrong once on this project (see `EXPERIMENTS.md`, the IMG_7744 false-positive review). A lead from a still frame is not a verdict until someone has watched the clip.
