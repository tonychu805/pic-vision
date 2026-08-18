# Archive — footage paused, not actively used

## Fixed-camera footage, paused

- **IMG_7652.MOV** — the near baseline is cut off by the camera frame at typical calibration timestamps, so the near-left/near-right corners can't be clicked. Existing calibration (`calib/IMG_7652_calib.json`) predates net-point marking and has no `net_image_points`. Existing 9 hand-marked labels (`eval/labels/IMG_7652.jsonl`) are untouched and still usable if this footage is revisited.
- **IMG_7655.MOV** — **the camera moves.** Measured 2026-08-18 with `scripts/check_drift.py --step-sec 20`: a ~25 px vertical bump between t=460s and t=480s that holds for the rest of the file, plus ~16 px of horizontal creep across the 9.4 minutes, plus two small settling shifts in the first 40s. Same failure mode as IMG_7743 (ADR-049), so it needs split calibration around t≈470s, and its 36 existing labels (`eval/labels/IMG_7655.jsonl`) straddle that boundary. This corrects an earlier note here that said "no known defect found" — `PROGRESS.md`'s original 2026-08-08 read (both this and IMG_7652 compromised by camera movement) was right, and the all-clear that replaced it was wrong. It is **not** a cheap fourth camera despite already having labels.

## Broadcast footage — structurally unusable for rally detection

Both archived 2026-08-18. These are edited multi-camera broadcast productions, not fixed-camera recordings. Camera cuts every 7–9 seconds mean the calibration is invalid *within* a single rally and the net line never holds still, so no amount of tuning makes the pipeline work on them. Measured hard scene cuts in a 3-minute sample (t=120–300s), `ffmpeg` scene threshold 0.3 — a fixed camera scores 0 over the same window:

| file | length | cuts in 3 min |
|---|---|---|
| `ppa_atlanta_2023_johnswaters_vs_newmantodd.mp4` | 5.0 min, 720p | 19 |
| `austin_open_johns_vs_ashlonnavratil.mp4` | 44.6 min, 1080p | 25 |

- **ppa_atlanta_2023_johnswaters_vs_newmantodd.mp4** — the 2023 PPA highlights clip. Edited, with dead time already removed, so it can't measure false positives even if the cuts were solved. Was used as a calibration test bed only (`PROGRESS.md`, 2026-08-06).
- **austin_open_johns_vs_ashlonnavratil.mp4** — the 2023 Austin PPA match broadcast. Only ever usable by hand-carving single-camera rally windows out of it: `videos/austin_rally1/2/3.mp4` came from here and stay in the active set as dev scaffolding, along with `calib/austin_rally2_calib.json` and `eval/labels/austin_rally2.jsonl`.

---

Nothing here has been deleted or altered — just moved out of the active `videos/raw/` set. Move back up a directory to resume. The fixed-camera files above are genuinely resumable; the broadcast files are archived for provenance, not as candidates.
