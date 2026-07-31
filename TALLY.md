# Session Tally — watch-through notes

One of these per session, filled in during step 3 (watch at 2× with this open). It costs ~45 minutes and it is the cheapest way to falsify the design before writing code.

**Copy this file per session:** `tallies/session-001.md`

---

## Session

| | |
|---|---|
| Session ID | |
| Date / time of day | |
| Court | |
| Lighting | bright sun / overcast / dusk / indoor |
| Singles or doubles | |
| Camera height & position | e.g. 9 ft, fence, centered, 8 ft behind baseline |
| Source duration | |

## Framing — check before anything else

| Check | Y/N | Notes |
|---|---|---|
| All 4 court corners visible | | |
| Both NVZ lines visible | | |
| Net line visible across full width | | |
| Far-court players' **feet** visible when at the kitchen line | | ← everything geometric depends on this |
| Near players occlude far players (how often?) | | |
| Adjacent court visible in frame | | if yes, ROI masking matters more |
| Ball visible at the far baseline | | if no, ball presence is not worth building |

## Rally tally

Count rallies in a **10-minute representative block** (note which block):

| | Count |
|---|---|
| Rallies | |
| Courtesy returns after a point | |
| Warm-up duration (min) | |
| Rallies interrupted by adjacent-court balls | |

Rough durations — just note a handful: shortest ___ s, typical ___ s, longest ___ s
Gap between rallies — typical ___ s, longest ___ s

## How rallies END — the critical tally

**This validates or kills ADR-026.** The design assumes dead-time markers are frequent and clean. For each rally in the block, tick what happened within ~5 s of the point ending:

| Marker | Tally | of N |
|---|---|---|
| Someone **crossed the net line** | | |
| Someone **left the court** (retrieval, towel, drink) | | |
| Someone **picked up / held the ball** | | |
| **Everyone stood still** ≥ 1.5 s | | |
| **None of the above** — play resumed immediately | | |

> **If "none of the above" is common, the dead-time inversion doesn't work** and the detection design needs to change before any code is written. Report the numbers rather than working around them.

## Anything surprising

Free text. Things the docs didn't anticipate — odd lighting shifts, people walking through frame, the mount drifting, a serve routine that looks like dead time, whatever.

```




```

## Verdict

- [ ] Framing usable
- [ ] Dead-time markers frequent enough to build on
- [ ] This session is worth labeling
- Assign role: `dev` / `eval` / `eval-lowlight`
