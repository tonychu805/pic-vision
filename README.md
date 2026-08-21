# Pickleball Rally Cutter (pic-vision)

Turns a two-hour fixed-camera pickleball session into a watchable highlight reel from one command. This is a **prototype** — see [`PRD.md`](./PRD.md) §1 for scope.

## Documents

- [`PROGRESS.md`](./PROGRESS.md) — start here: plain-language status, what to pick up next
- [`PRD.md`](./PRD.md) — what and why
- [`TECH_SPEC.md`](./TECH_SPEC.md) — how it's built (§12 = repo layout, §13 = build order)
- [`DECISIONS.md`](./DECISIONS.md) — decision log (ADRs)
- [`STRATEGY.md`](./STRATEGY.md) — post-prototype direction (exploratory, uncommitted)
- [`LABELING.md`](./LABELING.md) — rally-labeling protocol
- [`EXPERIMENTS.md`](./EXPERIMENTS.md) — append-only run log
- Linear (`pic-vision` team, `Rally Detection Accuracy` project) — current priorities and open work past the original build phases in `TECH_SPEC.md` §13

## Setup

    pip install -r requirements.txt

## Tools available now

Court calibration — click the 12 court points + 2 net-tape points once per camera mount
(`calibrate_web.py` is the same tool over a browser, for SSH/no-display sessions):

    python calibrate.py session.mp4 --at 300 --out court_calibration.json

Rally labeling — mark rally start/end intervals (`label_web.py` is the browser version,
and adds a GRADE mode for the highlight-worthy quality pass, `LABELING.md`):

    python label.py session.mp4 --out eval/labels/session-001.jsonl --from 600 --to 1800

`scripts/` holds one-off analysis and diagnostic tooling (camera-drift detection,
false-positive anatomy, parameter sweeps) — not part of this core run-a-session flow.
See `TECH_SPEC.md` §12 for the full repo layout.

## Pipeline

The detection pipeline (`src/cut.py` + `src/`) runs via `make process` (see `Makefile`) —
RunPod TrackNet inference (`scripts/pod_infer.py`) produces `predictions.csv`, then
`src/cut.py` gates it through calibration and cuts clips. Built phase by phase per
[`PRD.md`](./PRD.md) §7 and [`TECH_SPEC.md`](./TECH_SPEC.md) §13; current pipeline state
(active detector, shipped defaults) is summarized in `CLAUDE.md`.
