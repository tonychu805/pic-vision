"""Add field-test clips (PGC, 2026-09-25/26) to the blind pace-share check.

Same design as scripts/make_blind_check.py, and the same measurement
(pace_share, scripts/ball_tempo_features.py), but on real venue footage from
the actual target cameras (1920x1080, 30 fps) so the check isn't built only
from the pilot dev videos. These sessions have NO hand grades, which a
playback check doesn't need.

  * Ranked WITHIN each session (z-score vs that session's own typical pace),
    because cameras/courts differ.
  * One length band (5-25 s) for every candidate, as before.
  * At most one clip per session, spread over as many courts as possible.
  * Same fixed fast-ball cut-off as the dev videos (1.80 court widths/s), so
    numbers are comparable; nothing is tuned on this footage.
  * Silent clips, letters continue K.., key appended to cache/ (not printed).

Internal review only: this is third-party venue footage with nothing signed
(see the PGC consent note). The clips stay in clips/ (gitignored); don't share.

Run: .venv/bin/python scripts/make_blind_check_field.py
"""
import csv
import glob
import json
import os
import random
import statistics
import subprocess
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import ball_tempo_features as btf  # noqa: E402
import validate_absolute_ranking as base  # noqa: E402
from src.ball import net_line_y  # noqa: E402
from src.select import score_segments  # noqa: E402

SEED = 20261012
BAND = (5.0, 25.0)
PAD = 1.0
CUTOFF_CW = 1.80
N_PER_GROUP = 4
DIR = "cache/pgc_fieldtest"
OUT_DIR = "clips/blind_check"
KEY = "cache/blind_check_key.csv"


def session_candidates(sid):
    calib = json.load(open(f"{DIR}/{sid}.calib.json"))
    csv_path = f"{DIR}/{sid}.csv"
    segments, crossed, speeds = base.detect(csv_path, calib)
    net_px = base.net_width_px(calib)
    raw = btf.raw_points(csv_path, calib)
    speeds_cw = [(t, v / net_px) for t, v in speeds]
    scored = score_segments(segments, crossed, speeds, net_px)
    score_by = {(r["start"], r["end"]): r["score"] for r in scored}
    out = []
    for s in segments:
        f = btf.features_for(s, crossed, speeds_cw, raw, net_line_y(calib), net_px, CUTOFF_CW,
                             score_by[(s["start"], s["end"])])
        f["sid"] = sid
        out.append(f)
    return out


def main():
    cands, courts, n_rallies = [], {}, {}
    for path in sorted(glob.glob(f"{DIR}/*.csv")):
        sid = os.path.basename(path)[:-4]
        try:
            rows = session_candidates(sid)
        except Exception as exc:  # a session that doesn't fit the pipeline is skipped, loudly
            print(f"skip {sid[:8]}: {type(exc).__name__}: {exc}")
            continue
        courts[sid] = open(f"{DIR}/{sid}.label").read().strip()
        n_rallies[sid] = len(rows)
        rows = [r for r in rows if r["pace_share"] is not None and BAND[0] <= r["duration"] <= BAND[1]]
        vals = [r["pace_share"] for r in rows]
        mu = statistics.mean(vals) if vals else 0.0
        sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        for r in rows:  # distance from this session's own typical pace
            r["z"] = (r["pace_share"] - mu) / sd if sd else 0.0
        cands += rows

    print(f"{len(n_rallies)} sessions, {sum(n_rallies.values())} detected rallies, "
          f"{len(cands)} in the {BAND[0]:.0f}-{BAND[1]:.0f} s band")
    print("courts: " + ", ".join(sorted(set(courts.values()))))
    usable = [r for r in cands if True]
    # Need enough rallies in a session for a percentile to mean something.
    per_session = {}
    for r in usable:
        per_session.setdefault(r["sid"], []).append(r)
    ok = {sid for sid, g in per_session.items() if len(g) >= 6}
    usable = [r for r in usable if r["sid"] in ok]
    print(f"{len(ok)} sessions with >= 6 candidates: used for the check")

    def pick(group_high, exclude_sids):
        pool = sorted(usable, key=lambda r: (r["z"], r["sid"], r["start"]), reverse=group_high)
        chosen, used_sid, used_court = [], set(exclude_sids), {}
        for r in pool:  # most extreme first, but spread: one per session, <= 2 per court
            court = courts[r["sid"]]
            if r["sid"] in used_sid:
                continue
            if used_court.get(court, 0) >= 2:
                continue
            chosen.append(r)
            used_sid.add(r["sid"])
            used_court[court] = used_court.get(court, 0) + 1
            if len(chosen) == N_PER_GROUP:
                break
        return chosen

    highs = pick(True, set())
    lows = pick(False, {r["sid"] for r in highs})  # different sessions from the highs
    if len(highs) < N_PER_GROUP or len(lows) < N_PER_GROUP:
        raise SystemExit(f"could not fill both groups: high {len(highs)}, low {len(lows)}")
    picks = [("high", r) for r in highs] + [("low", r) for r in lows]
    random.Random(SEED + 1).shuffle(picks)

    existing = [r for r in csv.DictReader(open(KEY))] if os.path.exists(KEY) else []
    start_idx = len(existing)
    letters = [chr(ord("A") + start_idx + i) for i in range(len(picks))]
    with open(KEY, "a", newline="") as fh:
        w = csv.writer(fh)
        for letter, (group, r) in zip(letters, picks):
            ss = max(0.0, r["start"] - PAD)
            out = f"{OUT_DIR}/{letter}.mp4"
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", f"{ss:.3f}", "-i", f"{DIR}/{r['sid']}.mp4",
                 "-t", f"{r['end'] - ss + PAD:.3f}", "-an", "-c:v", "libx264", "-crf", "20",
                 "-preset", "veryfast", "-pix_fmt", "yuv420p", out], check=True)
            w.writerow([letter, f"PGC:{courts[r['sid']]}:{r['sid'][:8]}", group, f"{r['start']:.2f}",
                        f"{r['end']:.2f}", f"{r['duration']:.2f}", f"{r['pace_share']}", ""])

    for g in ("high", "low"):
        d = [r["duration"] for grp, r in picks if grp == g]
        print(f"{g:4s}: n={len(d)}  clip length mean {statistics.mean(d):.1f}s (range {min(d):.1f}-{max(d):.1f}s)")
    print("courts used: " + ", ".join(sorted({courts[r['sid']] for _, r in picks})))
    print(f"cut {len(picks)} clips -> {OUT_DIR}/{letters[0]}..{letters[-1]}  (key appended to {KEY}, not shown)")


if __name__ == "__main__":
    main()
