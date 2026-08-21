# pic-vision — project conventions

Pickleball Rally Cutter: turns a two-hour fixed-camera pickleball session into a highlight reel from one command. This is a **prototype** (see `PRD.md` §1) — one operator, one camera, one court, CLI only.

## Docs map — which file is authoritative for what

| Question | Read this |
|---|---|
| **Start here — plain-language status, what to pick up next** | `PROGRESS.md` (a pointer — the actual entries are `progress/MM.DD progress overview.md`, one file per day, newest last) |
| What and why (requirements) | `PRD.md` |
| How it's built (architecture, repo layout) | `TECH_SPEC.md` |
| Why a past decision was made | `DECISIONS.md` (ADR log, append-only) |
| What a specific run measured | `EXPERIMENTS.md` (append-only) |
| What's built vs. not, original Phase 0–1 gate status | `CHECKLIST.md` — for anything after Phase 1 (current detection-quality and direction work), Linear's `pic-vision` team / `Rally Detection Accuracy` project is authoritative instead; `CHECKLIST.md` was never extended past the original phase gates |
| Rally-labeling rules | `LABELING.md` |
| Post-prototype direction (exploratory, not committed) | `STRATEGY.md` |
| How to run the tools | `README.md` |

Record every scored run in `EXPERIMENTS.md`, even — especially — bad numbers; the point is to stop re-learning the same thing twice. A durable conclusion from an experiment gets an ADR in `DECISIONS.md` that links back to it, and — if it changes what to do next — an entry in that day's `progress/MM.DD progress overview.md` (create the day's file if it doesn't exist yet; add a new dated file for a new day rather than editing an old one). All three exist because they serve different readers (raw record / durable rationale / plain-language status); when correcting something, update the one that's actually wrong first, then check whether the other two need a matching update rather than assuming they don't.

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

## Where new files go

- **Root**: tools an operator runs directly as a primary workflow step (`calibrate*.py`, `label*.py`) plus the docs/config listed in `TECH_SPEC.md` §12.
- **`scripts/`**: one-off analysis, diagnostics, and parameter sweeps — not part of the core run-a-session flow.
- **`archive/`**: retired code, kept for reference, not imported by anything active (see `archive/README.md` for why each entry was retired).

`TECH_SPEC.md` §12 is the authoritative repo-layout tree (per the docs map above) — it had drifted badly out of date (still describing the pre-`ADR-046` design) until a 2026-08-21 repo-hygiene pass fixed it. **Update that tree in the same change that adds or moves a top-level file or directory**, not later — that lag is exactly how the drift happened.

## Subagent worktrees

If you spawn a subagent with `isolation: "worktree"`, its work-in-progress lives only in that worktree until you land it. Don't leave a finished worktree orphaned under `.claude/worktrees/`: either land its useful output onto `main` (commit or copy, per the rule above) and remove the worktree (`git worktree remove`, then delete the branch), or discard it outright if the work wasn't kept. An orphaned worktree with uncommitted scratch files was exactly what a 2026-08-21 repo-hygiene review found and had to reconstruct from scratch.
