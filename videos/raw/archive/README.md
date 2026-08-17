# Archive — footage paused, not actively used

- **IMG_7652.MOV** — the near baseline is cut off by the camera frame at typical calibration timestamps, so the near-left/near-right corners can't be clicked. Existing calibration (`calib/IMG_7652_calib.json`) predates net-point marking and has no `net_image_points`. Existing 9 hand-marked labels (`eval/labels/IMG_7652.jsonl`) are untouched and still usable if this footage is revisited.
- **IMG_7655.MOV** — no known defect found; paused alongside IMG_7652 (2026-08-17) to focus on IMG_7744 instead. Existing 36 hand-marked labels (`eval/labels/IMG_7655.jsonl`) are untouched.

Neither has been deleted or altered — just moved out of the active `videos/raw/` set. Move back up a directory to resume.
