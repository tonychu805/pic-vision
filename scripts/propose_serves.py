"""Serve-candidate PROPOSER over the PGC field-test sessions.

Builds a TRACEABLE, bounded set of serve candidates a human can confirm/reject
-- the trustworthy harness the orphaned cache/pose_serve set can't be. Each
candidate maps straight to a watchable clip in cache/pgc_fieldtest/<uuid>.mp4.

Key idea: a serve is the shot that STARTS a rally. So we anchor to each
detected rally start (shipped detection, gap_sec=3/min_crossings=6) and look in
its lead-in window for the EARLIEST deep-player arm swing -- that's the serve
that initiated the point. ~1 candidate per rally (tens, not the ~1400 that
proposing every deep swing gives), and directly serve-relevant.

- "deep" / swing-strength are self-normalized PER SESSION, PER SIDE, so far-side
  serves survive the far-baseline depth compression we found.
- EARLIEST deep swing in the window = the server (the returner swings after).
- A rally with no clear deep swing in-window is recorded too (note=no_serve_found)
  -- those are exactly the far-compression / missed-serve cases to inspect.

Read-only. Writes cache/serve_candidates.csv (one row per detected rally).
"""
import sys, json, math, pathlib, csv, bisect
import numpy as np

ROOT = pathlib.Path("/home/tonychu/repository/pic-vision")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
import tune_web as tw
import footage_rules as fr

PGC = ROOT / "cache/pgc_fieldtest"
POSE = ROOT / "cache/arm_swing"
NET_Y, FPS = 22.0, 30.0
PRE, POST = 4.0, 1.0      # serve window around a rally start: [start-PRE, start+POST]
DEEP_FRAC = 0.40          # back 40% toward a side's own extreme = "deep"
# Far-serve depth floor, derived from the COURT'S OWN calibrated geometry rather
# than a hand-tuned constant or the observed-player spread. court_y is calibrated
# feet, with the net at NET_Y and the far baseline at 2*NET_Y; the non-volley
# ("kitchen") line sits KITCHEN_DEPTH ft past the net by rule. A serve is struck
# deep in the backcourt (behind the far kitchen line, toward the baseline), so the
# floor is the back fraction of that backcourt zone. This fixes the real failure:
# the self-normalized far_cut collapses in compressed-court sessions (nobody
# reaches the baseline) and lets mid-court players count as "far" -- 20 of 27
# false far proposals in the project-16 ground truth. Deriving the floor from the
# calibrated court lines (not from where players happened to stand) can't collapse,
# and it moves with the calibration instead of being pinned to these cameras.
# NOTE: far-end depth is the least reliable region from a behind-baseline camera,
# so this floor is still only a necessary (not sufficient) cue -- see EXPERIMENTS
# 2026-10-23. For standard calibration it lands ~34 ft (keeps all 7 known serves).
KITCHEN_DEPTH = 7.0            # non-volley-zone depth from the net (court rule)
BACKCOURT_SERVE_FRAC = 0.33    # a serve sits in the back third of the backcourt


def sessions():
    for csvp in sorted(PGC.glob("*.csv")):
        uuid = csvp.stem; pre = uuid[:8]
        calib = PGC / f"{uuid}.calib.json"; pose = POSE / f"poses_pgc_{pre}.json"
        name = (PGC / f"{uuid}.label").read_text().strip() if (PGC / f"{uuid}.label").exists() else ""
        # Skip excluded footage (frame-dropping Tapo court-1 camera, coaching/drill
        # sessions) so it never becomes a serve candidate -- see scripts/footage_rules.py
        # (ADR-155/158). This is the gate whose absence let the Tapo + drill sessions
        # leak into the first near-serve review pass.
        if calib.exists() and pose.exists() and fr.usable(uuid):
            yield uuid, pre, name, str(csvp), str(calib), str(pose)


def wrists(persons):
    out = []
    for pp in persons:
        if not pp.get("court"):
            continue
        kp = pp.get("kp") or []
        ws = [(kp[j][0], kp[j][1]) for j in (9, 10) if len(kp) > j and kp[j][2] > 0.3]
        if ws:
            out.append((pp["court"][1], ws))
    return out


def deep_swings(pose_path):
    """Per-frame fastest wrist motion of a DEEP player -> [(t, side, cy, speed)]."""
    poses = json.load(open(pose_path)); fnums = sorted(poses, key=int)
    allys = [y for fn in fnums for y, _ in wrists(poses[fn])]
    if not allys:
        return [], (None, None)
    near_ext, far_ext = np.percentile(allys, 2), np.percentile(allys, 98)
    near_cut = near_ext + DEEP_FRAC * (NET_Y - near_ext)
    far_baseline = 2 * NET_Y                       # court length; net is the midline
    far_kitchen = NET_Y + KITCHEN_DEPTH            # far non-volley line
    geom_floor = far_kitchen + BACKCOURT_SERVE_FRAC * (far_baseline - far_kitchen)
    far_cut = max(far_ext - DEEP_FRAC * (far_ext - NET_Y), geom_floor)
    events, prev_t, prev_pts = [], None, []
    for fn in fnums:
        t = int(fn) / FPS; people = wrists(poses[fn])
        if prev_t is not None and t > prev_t and prev_pts:
            dt = t - prev_t
            for cy, ws in people:
                side = "near" if cy <= near_cut else ("far" if cy >= far_cut else None)
                if side:
                    sp = max(min(math.hypot(wx - px, wy - py) for px, py in prev_pts) for wx, wy in ws) / dt
                    events.append((t, side, cy, sp))
        prev_t, prev_pts = t, [w for _, wl in people for w in wl]
    return events, (round(near_cut, 1), round(far_cut, 1))


def rally_starts(csvp, calib, pose):
    p = dict(tw.DEFAULTS)
    p.update({"csv": csvp, "calib": calib, "pose": pose, "fps": FPS, "n": 99999, "serve_gate": 0})
    return sorted(r["start"] for r in tw.compute(p)["rows"])


def main():
    out = ROOT / "cache/serve_candidates.csv"; rows = []
    print(f"{'session':9} {'name':14} {'rallies':>7} {'serves':>6} {'near':>4} {'far':>4} {'noSrv':>5}")
    print("-" * 64)
    for uuid, pre, name, csvp, calib, pose in sessions():
        events, _ = deep_swings(pose)
        thr = np.percentile([e[3] for e in events], 60) if events else 0  # a modest swing floor
        starts = rally_starts(csvp, calib, pose)
        near = far = nosrv = 0
        for S in starts:
            win = sorted([e for e in events if S - PRE <= e[0] <= S + POST and e[3] >= thr])
            if win:
                t, side, cy, sp = win[0]          # earliest deep swing = gates side/depth
                # Serve TIME is anchored to the rally's first net crossing, not the
                # pose swing: the serve is struck ~0.5s before the ball first crosses.
                # Measured on the project-16 ground truth, this cut median timing error
                # from 3.7s (swing) to 0.2s (crossing). The deep swing is still used to
                # decide far/near side and the depth gate; only the moment changes.
                serve_t = round(S - 0.5, 1)
                rows.append({"session": uuid, "name": name, "rally_start": round(S, 1),
                             "serve_t": serve_t, "side": side, "court_y": round(cy, 1),
                             "swing_px_s": round(sp), "note": ""})
                near += side == "near"; far += side == "far"
            else:
                rows.append({"session": uuid, "name": name, "rally_start": round(S, 1),
                             "serve_t": "", "side": "", "court_y": "", "swing_px_s": "",
                             "note": "no_serve_found"})
                nosrv += 1
        print(f"{pre:9} {name[:14]:14} {len(starts):7d} {near+far:6d} {near:4d} {far:4d} {nosrv:5d}")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["session", "name", "rally_start", "serve_t",
                                          "side", "court_y", "swing_px_s", "note"])
        w.writeheader(); w.writerows(rows)
    tot = len(rows); nf = sum(1 for r in rows if r["side"] == "far")
    ns = sum(1 for r in rows if r["note"] == "no_serve_found")
    print("-" * 64)
    print(f"TOTAL rallies: {tot}  serve proposed: {tot-ns} (near {tot-ns-nf}, far {nf})  no_serve_found: {ns}")
    print(f"written: {out}")


if __name__ == "__main__":
    main()
