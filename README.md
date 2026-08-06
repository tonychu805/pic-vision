# Pickleball Rally Cutter (pic-vision)

Turns a two-hour fixed-camera pickleball session into a watchable highlight reel from one command. This is a **prototype** — see [`PRD.md`](./PRD.md) §1 for scope.

## Documents

- [`PRD.md`](./PRD.md) — what and why
- [`TECH_SPEC.md`](./TECH_SPEC.md) — how it's built (§12 = repo layout, §13 = build order)
- [`DECISIONS.md`](./DECISIONS.md) — decision log (ADRs)
- [`STRATEGY.md`](./STRATEGY.md) — post-prototype direction (exploratory, uncommitted)
- [`LABELING.md`](./LABELING.md) — rally-labeling protocol
- [`TALLY.md`](./TALLY.md) — per-session watch-through template
- [`EXPERIMENTS.md`](./EXPERIMENTS.md) — append-only run log

## Setup

    pip install -r requirements.txt

## Tools available now

Court calibration — click the 12 court points once per camera mount:

    python calibrate.py session.mp4 --at 300 --out court_calibration.json

Rally labeling — mark rally start/end intervals:

    python label.py session.mp4 --out eval/labels/session-001.jsonl --from 600 --to 1800

## Pipeline

The detection pipeline (`cut.py` + `src/`) is built phase by phase per [`PRD.md`](./PRD.md) §7 and [`TECH_SPEC.md`](./TECH_SPEC.md) §13. Module files appear as each phase lands — they are not stubbed ahead of time. The directory skeleton (`src/`, `eval/labels/`, `tallies/`) and config surface (`config.yaml`) exist from the start.
