# Labeling Protocol

**Fill in the bracketed decisions after watching your first session (step 3), then don't change them.** Consistency matters more than which choice you make — an inconsistent labeler puts a ceiling on every metric the project will ever produce.

Version: 3 · Last changed: 2026-08-20

---

## What a rally is

A rally runs from **serve contact** to **the moment the ball next touches the ground or goes out of play** — the ball becoming *dead*, not merely the last paddle contact.

**Decided (v2):** ball-dead. This is deliberately *later* than the original "last ball contact"; PRD §5 has been updated to match, so the two agree.

The difference is up to a second on any point that ends with the ball sailing long, which is a large fraction of your 1.0 s boundary target.

## What makes a rally highlight-worthy (quality grade)

**First draft, decided 2026-08-20 (PIC-45) — not yet consistency-checked.** Everything else in this file has been through at least one round of "does this hold up," this hasn't; read it as a starting point to test, not a settled rule the way "what is a rally" above is.

During the GRADE pass (`label_web.py`), a real rally gets `quality`: **1 = highlight-worthy, 2 = ordinary** (a rally that isn't a rally at all — dead time, courtesy return, etc. — is dropped per the rules above, not graded).

Grade **1** if the rally clearly shows **at least one** of:

| Factor | What to look for |
|---|---|
| **Length/intensity** | Unusually long for its format — more exchanges than a typical rally on this court, this session |
| **Momentum swing** | A side is scrambling or out of position and still wins the point, or the rally clearly turns mid-point |
| **Skill display** | A dive, a sprint recovery, an around-the-post shot, a well-executed drop/reset under pressure |
| **Sustained tension** | An extended dinking/kitchen-line battle before the point breaks open |
| **Clean finish** | A decisive, well-earned put-away — not an unforced error ending the point |

Grade **2** otherwise — a real rally, nothing above stood out.

This is a **checklist, not a formula**: one clear factor is enough, and "clearly shows" is the same kind of judgment call "ball dead" is for the boundary above — consistent application matters more than precision on any single borderline case.

**Consistency check — do this once (PIC-45), same method as the rally-presence check below.** Grade a set of already-labelled rallies against this checklist, wait at least a day, re-grade blind, compare agreement. Record the result in `EXPERIMENTS.md` regardless of outcome — if agreement is as loose as the ~1/3 rally-presence figure below, "highlight-worthy" isn't a stable target yet either, and that's a real finding, not a failure.

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

**Run once, 2026-08-20 (PIC-6), `EXPERIMENTS.md` for the full breakdown.** Boundary spread on agreed-upon rallies is small (~0.6s median, close to the ±0.5s target above) — not the concern. **Whether a stretch counts as a rally at all is the real noise source**: only 3 of 9 distinct rally-windows identified across two blind passes over the same 5 minutes were agreed on by both (2 missed on repeat, 4 found that weren't marked the first time). Read any precision/recall comparison finer than roughly this margin with real skepticism — it may be labelling noise, not signal. One data point (one labeller, one 5-minute stretch) — not yet a precise constant.

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

**Locked 2026-08-19 (PIC-17).** This table existed but `sessions.jsonl` was never actually populated — every parameter sweep on this project (`min_crossings`, `gap_sec`, `court_wedge`'s cap/spread, and PIC-33's adaptive-gap search) has tuned and evaluated on the same labelled footage. See `sessions.jsonl` for the actual assignment. `eval` = **IMG_7743**: the most-labelled video (53 labels after PIC-32), and the one PIC-33's adaptive-gap search and PIC-31's threshold check already happened to leave untouched, so it's the closest thing this project has to a real held-out check today. `dev` = **brickwall, pb_draft_cup, IMG_7744**: each is the only labelled example of its rally-length/format regime (tournament doubles, singles, casual doubles-with-adjacent-court-noise respectively) — locking any of them out of tuning would remove a whole regime's coverage, so `eval` had to be the one video whose regime (casual doubles) already has a second representative (IMG_7744) in `dev`.

**Known, unfixable-in-place limitation:** the *currently shipped* `min_crossings=6`, `gap_sec=3.0` base, and `court_wedge`'s cap/spread constants were all originally tuned using IMG_7743 itself (`EXPERIMENTS.md`, 2026-08-16), before this lock existed. That history can't be undone. Going forward, no future sweep may touch IMG_7743's labels to pick a parameter — only to report a final number, per the `eval` role above. Re-deriving those specific constants against `dev` only, now that this discipline exists, is open as PIC-43.
