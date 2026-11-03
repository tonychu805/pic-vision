"""Test E2: per-point still-site removal (tracklets_first.drop_still_v2) before track_ball (2026-10-16, PIC-226).
Pre-registered: committed before any chunk-3 label existed (labelling had just started) and before any v2 score.

v2 fixes the flaw found in Test E (glare chained into "moving" tracklets and exempted): a glare-site point is
kept only if it lies on a straight moving path between a detection just before and just after it. Constants
unchanged from v1. Chunk 2 was used to diagnose v1, so it is reported, not gated. Chunk 3 (de3d1953, the
third camera, minutes 2-6 of 0925 08:24 session-001, chosen by rule without looking at detections) is the
held-out bounce test; its calibration is borrowed (52f4de24, image-match 0.034).
AMENDED before any label or score (same day): that stretch was casual multi-ball hitting, so chunk 3 is now
chunk 3b = de3d1953 0925 08:24 session-004 minutes 2:00-6:00 (calib 499ed4b8, image-match 0.034), the first of
the next four recordings in calibration-match order that the operator judged a real game from an 8x preview.
Bars unchanged.
AMENDED again before any label or score: de3d1953 is the Tapo C200 and drops frames (3b's recording failed the
decode guard; CFR re-encode duplicates frames, which distorts speed). Chunk 3 is now chunk 3c = eda301d9
2026-09-26 05:38 session-000 minutes 2:00-6:00 (calib 7358ef3f, image-match 0.020): a different day from chunk 1
and a camera not used to design v1/v2, chosen as the first 9/26 recording in time order the operator judged a real
game from an 8x preview. Bars unchanged.

GATED (all must hold):
  chunk 3 (tile)  v2 found >= production found - 1        (no harm on unseen footage)
  chunk 1 (tile)  v2 found >= 13 of 33                     (production 14)
  rallies         real field clips lost <= 3 of 60 AND graded dev lost <= 5 of 83 (D-series units, as Test E)
REPORTED: chunk 3 and chunk 2 found for production / v2 / fixed static mask; share of static-cell detections
v2 removes on each chunk; scenery fakes and not-real removed; rallies before -> after.
Stated in advance: if chunk 3 has little glare (static cells < 20% of its detections), chunk 3 is only a
no-harm check, and the case for v2 rests on chunk 2 (contaminated) plus the rally numbers.
Run: .venv/bin/python scripts/eval_tracklets_first_v2.py   (after chunk-3 labels are exported)
"""
import collections, json, subprocess, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from src.bounce_eval import recover
from src.calib import court_wedge
from src.tracknet import load_predictions
import eval_tracklets_first as E1
import check_static_removed_bounces as M
from tracklets_first import drop_still_v2

E1.drop_still = drop_still_v2
C3_LABELS = "eval/labels/bounces/cvat_eda301d9_0926T0538_s000_120-360.json"
C3 = ("chunk 3", C3_LABELS, "cache/pgc_fieldtest/7358ef3f-6a41-4abe-b431-807eba7bc9f1.calib.json",
      "cache/bounce_pilot/chunk3c_eda301d9_0538_s000.tile.csv")
VIDEO3 = "clips/bounce_chunk3/eda301d9_0926T0538_s000_120-360.mp4"


def export_c3():
    q = """select l.job_id, l.frame, l.points from engine_labeledshape l join engine_job j on j.id=l.job_id
           join engine_segment s on s.id=j.segment_id join engine_task t on t.id=s.task_id
           join engine_project p on p.id=t.project_id where p.name='bounce-chunk3c-pgc' and l.type='points' order by l.frame"""
    out = subprocess.run(["docker", "--context", "desktop-linux", "exec", "cvat_db", "psql", "-U", "root", "-d", "cvat",
                          "-tA", "-F", "|", "-c", q], capture_output=True, text=True, check=True).stdout
    b, last = [], None
    for line in out.splitlines():
        j, f, pts = line.split("|"); x, y = (float(v) for v in pts.split(",")[:2]); f = int(f)
        # jobs overlap by 5 frames: the same bounce labelled in two adjacent jobs is kept once (added after
        # labelling, before scoring; it hit one pair, frames 6268/6269)
        if last and last[0] != j and f - last[1] <= 3 and abs(x - last[2]) + abs(y - last[3]) <= 15:
            continue
        last = (j, f, x, y)
        b.append({"frame": f, "t": round(f / 30.0, 3), "x": round(x, 1), "y": round(y, 1)})
    json.dump({"source": "cvat project bounce-chunk3c-pgc", "video": VIDEO3, "source_frame_offset": 3600, "fps": 30.0,
               "n_frames_cvat": 7200, "complete": None, "bounces": b}, open(C3_LABELS, "w"), indent=1)


def static_share(csv_, calib):
    tr = load_predictions(csv_, 30.0); w = court_wedge(calib, margin_px=400.0)
    fr = [[(x, y, 1.0)] if (x is not None and w(x, y)) else [] for _, x, y, *_r in tr]
    cell = lambda x, y: (int(x // 20), int(y // 20))
    cnt = collections.Counter(cell(*c[0][:2]) for c in fr if c); static = {k for k, v in cnt.items() if v >= 100}
    before = sum(1 for c in fr if c and cell(*c[0][:2]) in static)
    after = sum(1 for c in drop_still_v2(fr) if c and cell(*c[0][:2]) in static)
    return before, after, sum(1 for c in fr if c)


def chunk_row(name, labp, calp, csv_):
    labs = json.load(open(labp))["bounces"]; calib = json.load(open(calp))
    f = lambda pts: sum(recover({"frame": b["frame"], "x": b["x"], "y": b["y"], "visible": True}, *pts[1:3], pts[3], pts[0])["found"]
                        for b in labs)
    prod = f(E1.bounce_points(csv_, calib, False)); v2 = f(E1.bounce_points(csv_, calib, True))
    H, raw, tracked, cands, _s, _c = M.points(csv_, calib, True); mask = f((H, raw, tracked, cands))
    sb, sa, tot = static_share(csv_, calib)
    print(f"{name}: found production {prod} / v2 {v2} / fixed mask {mask}  of {len(labs)};  static-cell detections "
          f"{sb} ({sb / max(tot, 1):.0%} of all), v2 removes {sb - sa} ({(sb - sa) / max(sb, 1):.0%})")
    return prod, v2


def main():
    export_c3()
    p3, v3 = chunk_row(*C3)
    chunk_row(*E1.CHUNKS[1][:4])
    p1, v1 = chunk_row(*E1.CHUNKS[0][:4])
    rallies = E1.part2()
    g3, g1 = v3 >= p3 - 1, v1 >= 13
    print(f"\nchunk 3 no-harm {'PASS' if g3 else 'FAIL'}   chunk 1 {'PASS' if g1 else 'FAIL'}   rallies {'PASS' if rallies else 'FAIL'}"
          f"   ->  {'PASS' if g3 and g1 and rallies else 'FAIL'}")


if __name__ == "__main__":
    main()
