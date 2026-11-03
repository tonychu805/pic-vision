"""A1 staging testbed: run the REAL detect -> score path on a session's
TrackNet predictions + calibration, and emit the ranked reel as JSON + SQL
ready to load into the isolated staging console DB.

Why this exists: to evaluate a new detection/ranking signal (swing, etc.)
end-to-end into the delivery data model *without touching production* and
*without re-deriving a crude baseline* — the failure the 2026-10-xx feedback
flagged. It reuses the shipped functions verbatim (`court_wedge`,
`track_ball`, `crossing_times`, `cluster_crossings`, `frame_speeds`,
`score_segments` = the ADR-133 fixed 0-100 score that real reels carry); the
only thing it does differently from `src/rallies.detect_candidates` is supply
an explicit fps instead of probing a video file (the pod CFR-converts to a
fixed 30fps anyway), so it runs on cached predictions with no video and no GPU.

It does NOT cut clips (that needs the raw video — see A2). It produces the
selection + 0-100 scores, which is what a ranking signal actually changes.

Usage:
    python3 scripts/rank_to_staging.py \
        --csv cache/IMG_7743_predictions_k14.csv \
        --calib calib/IMG_7743_calib.json \
        --label a1-img7743-baseline \
        [--fps 30] [--offset-sec 0] [--n 10] [--gap-sec 3.0] [--min-crossings 6]

Output: a JSON artifact + an idempotent SQL block (DELETE then INSERT by
session_id) for public.reels on the staging project. Load the SQL into staging
(dashboard SQL editor / MCP) to see the run in the staging console.
"""
import argparse
import gzip
import json
import pathlib
import sys
import uuid

sys.path.insert(0, ".")

from src.ball import cluster_crossings, crossing_times, net_line_y
from src.calib import court_wedge
from src.rallies import GAP_SEC, MIN_CROSSINGS
from src.select import frame_speeds, net_width_px, score_segments, spike_threshold
from src.track import max_jump_for_fps, reset_after_for_fps, track_ball
from src.tracknet import load_predictions

# Fixed identifiers for the staging seed brand/agent/camera (see the staging
# synthetic seed). Rows attach to these so they show up under "Staging Test Club".
STAGING_AGENT_ID = "cccccccc-0000-0000-0000-000000000001"
STAGING_CAMERA_ID = "staging-cam-1"
STAGING_CAMERA_LABEL = "Court 1 (staging)"
STAGING_BRAND_NAME = "Staging Test Club"
# Placeholder bucket/key: A1 writes no clip files (A2 does). r2_key_ranked is
# NOT NULL, so it carries a marker path that clearly isn't a real object.
NOCLIP_BUCKET = "a1-noclip"


def _open_csv(path):
    path = str(path)
    return gzip.open(path, "rt") if path.endswith(".gz") else open(path)


def rank(csv_path, calib_path, fps, gap_sec, min_crossings, offset_sec):
    """The real detect->score path, fps supplied instead of probed. Returns
    the ranked rows (best first) with absolute-time start/end."""
    with open(calib_path) as f:
        calib = json.load(f)
    in_court = court_wedge(calib)
    net_y = net_line_y(calib)
    net_px = net_width_px(calib)

    # load_predictions wants a path; handle optional .gz by staging a temp read.
    import csv as _csv
    import io
    with _open_csv(csv_path) as fh:
        text = fh.read()
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as tmp:
        tmp.write(text)
        tmp_path = tmp.name
    track = load_predictions(tmp_path, fps)

    times = [t for t, *_ in track]
    frames = [[(x, y, conf if conf is not None else 1.0)] if in_court(x, y) else []
              for _, x, y, w, h, conf in track]
    ys = track_ball(frames, max_jump=max_jump_for_fps(fps), reset_after=reset_after_for_fps(fps))
    tracked = list(zip(times, ys))
    times_crossed = crossing_times(tracked, net_y=net_y, band=0.0)
    segments = cluster_crossings(times_crossed, gap_sec=gap_sec, min_crossings=min_crossings)

    raw_points = sorted([(t, x, y) for t, x, y, w, h, c in track if in_court(x, y)],
                        key=lambda p: p[0])
    speeds = frame_speeds(raw_points)

    ranked = score_segments(segments, times_crossed, speeds, net_px)
    for r in ranked:
        r["start_abs"] = r["start"] + offset_sec
        r["end_abs"] = r["end"] + offset_sec
    return ranked, net_px


def _sql_rows(ranked, label, n):
    session_id = label
    share_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "picvision-staging-a1/" + label))
    chosen = ranked[:n]
    lines = [
        "-- A1 staging run: %s  (%d candidates, top %d)" % (label, len(ranked), len(chosen)),
        "delete from public.reels where session_id = %s;" % _q(session_id),
    ]
    # one 'full' row representing the session
    lines.append(
        "insert into public.reels (agent_id, camera_id, camera_label, session_id, "
        "r2_bucket, r2_key_ranked, duration_sec, rally_count, brand_name, kind, share_id) values ("
        + ", ".join([_q(STAGING_AGENT_ID), _q(STAGING_CAMERA_ID), _q(STAGING_CAMERA_LABEL),
                     _q(session_id), _q(NOCLIP_BUCKET), _q("a1/%s/full.mp4" % label),
                     _num(sum(r["end"] - r["start"] for r in chosen)), str(len(ranked)),
                     _q(STAGING_BRAND_NAME), _q("full"), _q(share_id)]) + ");")
    for rank_i, r in enumerate(chosen, 1):
        lines.append(
            "insert into public.reels (agent_id, camera_id, camera_label, session_id, "
            "r2_bucket, r2_key_ranked, duration_sec, rally_count, brand_name, kind, share_id, "
            "rally_rank, score, part_start_sec, part_end_sec) values ("
            + ", ".join([
                _q(STAGING_AGENT_ID), _q(STAGING_CAMERA_ID), _q(STAGING_CAMERA_LABEL),
                _q(session_id), _q(NOCLIP_BUCKET), _q("a1/%s/rank%d.mp4" % (label, rank_i)),
                _num(r["end"] - r["start"]), "1", _q(STAGING_BRAND_NAME), _q("rally"),
                _q(share_id), str(rank_i), _num(r["score"]),
                str(int(r["start_abs"])), str(int(r["end_abs"]))]) + ");")
    return session_id, share_id, "\n".join(lines)


def _q(s):
    return "'" + str(s).replace("'", "''") + "'"


def _num(x):
    return repr(round(float(x), 3))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True, help="TrackNet predictions CSV (.csv or .csv.gz)")
    ap.add_argument("--calib", required=True)
    ap.add_argument("--label", required=True,
                    help="run label; also the staging session_id (e.g. a1-img7743-baseline)")
    ap.add_argument("--fps", type=float, default=30.0, help="CFR fps (pod uses 30)")
    ap.add_argument("--offset-sec", type=float, default=0.0,
                    help="add to clip-relative times for absolute session time (e.g. 2900 for the postbump clip)")
    ap.add_argument("--n", type=int, default=10, help="top-N rallies to record")
    ap.add_argument("--gap-sec", type=float, default=GAP_SEC)
    ap.add_argument("--min-crossings", type=int, default=MIN_CROSSINGS)
    ap.add_argument("--out-json", default=None, help="write ranked rows JSON here")
    ap.add_argument("--out-sql", default=None, help="write staging SQL here")
    args = ap.parse_args()

    ranked, net_px = rank(args.csv, args.calib, args.fps, args.gap_sec,
                          args.min_crossings, args.offset_sec)
    print("net width px: %s  |  %d candidate rallies" % (
        ("%.1f" % net_px) if net_px else "n/a (length+pace only)", len(ranked)), file=sys.stderr)
    print("\nrank  start-end (abs s)       dur    pcr   hard   score", file=sys.stderr)
    for i, r in enumerate(ranked[:args.n], 1):
        print("%4d  %7.1f-%7.1f  %6.1f  %4.2f  %4d  %6.1f" % (
            i, r["start_abs"], r["end_abs"], r["end"] - r["start"],
            r["peak_crossing_rate"], r["n_hard"], r["score"]), file=sys.stderr)

    session_id, share_id, sql = _sql_rows(ranked, args.label, args.n)
    if args.out_json:
        pathlib.Path(args.out_json).write_text(json.dumps(
            {"label": args.label, "session_id": session_id, "share_id": share_id,
             "n_candidates": len(ranked),
             "rallies": [{k: r[k] for k in ("start_abs", "end_abs", "duration",
                          "peak_crossing_rate", "n_hard", "score")} for r in ranked[:args.n]]},
            indent=2))
    if args.out_sql:
        pathlib.Path(args.out_sql).write_text(sql + "\n")
    print("\nsession_id=%s  share_id=%s" % (session_id, share_id), file=sys.stderr)
    print(sql)


if __name__ == "__main__":
    main()
