# Labeling Protocol

**Fill in the bracketed decisions after watching your first session (step 3), then don't change them.** Consistency matters more than which choice you make — an inconsistent labeler puts a ceiling on every metric the project will ever produce.

Version: 2 · Last changed: 2026-08-06

---

## What a rally is

A rally runs from **serve contact** to **the moment the ball next touches the ground or goes out of play** — the ball becoming *dead*, not merely the last paddle contact.

**Decided (v2):** ball-dead. This is deliberately *later* than the original "last ball contact"; PRD §5 has been updated to match, so the two agree.

The difference is up to a second on any point that ends with the ball sailing long, which is a large fraction of your 1.0 s boundary target.

## Edge cases — decide once

| Case | Rule |
|---|---|
| **Serve fault** | **Not a rally** — a faulted serve is a dead ball, no play occurred. (Pickleball has no second-serve do-over.) *(default — override if your games differ)* |
| **Let serve** (if your games replay it) | **Label the replay only**; the let itself is not a rally. Note: current USAP rules keep a net-serve that lands in *live* — then it is a normal rally. *(default — override if your games differ)* |
| **Courtesy return** — ball tapped back to the server after the point | **Never a rally.** Non-negotiable — this is the exact false positive the detector must reject, so the labels must be unambiguous. |
| **Warm-up / dinking practice** | **Exclude entirely.** Note the timestamp where real play begins. |
| **Rally interrupted** by a stray ball from the next court | **Label up to the interruption** — the real play counts; the interruption is just an early end. |
| **A point nobody plays out** (obvious out, players stop) | Label to the last contact anyway |
| **Between-game breaks** | Not rallies. Obviously. |

## Boundary precision

Aim for **± 0.5 s**. Don't agonise beyond that — your own repeatability is the floor, and the measurement below tells you what it is.

Label the *observed* action, not what you think the detector will find. Labels describe reality; the detector's job is to match them, not the reverse.

## Consistency check — do this once

1. Label a 5-minute stretch.
2. Wait at least a day. Do not look at the first labels.
3. Label the same 5 minutes again into a separate file.
4. Compare: how many rallies appear in both? What's the median difference in start and end times?

Record the result in `EXPERIMENTS.md`. **That number is the noise floor for every metric in the project** — a 1.0 s boundary target is meaningless if your own labels disagree with themselves by 1.5 s.

## Which footage to label

- **Take a continuous block**, not the interesting bits. Cherry-picking biases everything downstream.
- Skip warm-up unless the rule above says to include it.
- 20 minutes of source is a starting point; more is better and it's cheap.
- **Never split one session across dev and eval.** Whole sessions go entirely to one or the other — two chunks of the same session share lighting, players, court and mount, so they aren't independent samples.

## Session roles

Assign in `sessions.jsonl`, don't copy video files.

| Role | Use |
|---|---|
| `dev` | All tuning, threshold fitting, weight sweeps. Look as often as you like. |
| `eval` | Acceptance only. Locked. Touch at most once per phase. |
| `eval-lowlight` | Graceful-degradation check |
| `unassigned` | Captured but not yet labelled |

First session → `dev`. Second session, different day → `eval`.
