"""Coarse court-map test: does a found bounce land in the right zone? (2026-10-18, PIC-226)
Pre-registered: this file (zones, data, matching, bar) was committed before any found bounce was put in a zone.
Already known before writing it (earlier entries): how many bounces each chunk's finder finds; the court error
of found candidates on chunk 3c (median 0.39 ft near, 2.05 ft far). Not known: any zone result.

Operator's question: can a 2D court map show where bounces land? Ball flight is not mapped (a ball in the air
cannot be placed on the floor from one camera); only floor contacts. Coarse version first, at the operator's
choice: per side, kitchen or deep.
ZONES (court feet, y from the near baseline, net at y = 22, kitchen lines 7 ft from the net):
  near_deep y < 15 | near_kitchen 15 <= y < 22 | far_kitchen 22 <= y < 29 | far_deep y >= 29
  (out-of-bounds bounces fall in the deep zone of their side; x is ignored).
DATA: every CVAT bounce chunk labelled exhaustively by the operator, none from camera de3d1953 (ADR-155):
  chunk 1  eda301d9 2026-09-25 08:21 s000   33 bounces  calib 365c798c
  chunk 2  c199a97c 2026-09-26 05:38 s002   36 bounces  calib 34fab44c (glare court)
  chunk 3c eda301d9 2026-09-26 05:38 s000   98 bounces  calib 7358ef3f (minutes 2-6)
  Detections: the tiled k14 pass already used for these chunks (cache/bounce_pilot/*.tile.csv), not production.
MATCHING: unchanged (src/bounce_eval.recover): found = a finder candidate within +-3 frames and 15 px of the mark.
  Truth zone = the operator's mark through the homography; system zone = the matched candidate through the same
  homography. Calibration error is therefore shared and not measured here (0.2-0.4 ft, earlier entries).
BAR, per side (side = the truth zone's side), over found bounces, all chunks pooled:
  usable on that side  =  right zone >= 80%.   Fewer than 10 found bounces on a side = underpowered.
REPORTED: per chunk and side: marked, found, right zone; the confusion of zones; share of marks within 1 ft of a
  kitchen line or the net; candidate precision (candidates within +-3 frames of any mark).
Small sample, one venue, two cameras: a pass is a lead for a demo map, not a product claim.
Run: .venv/bin/python scripts/eval_bounce_zones.py
"""
import collections, json, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from src.bounce_eval import project, recover

CHUNKS = [
    ("chunk 1", "eval/labels/bounces/cvat_eda301d9_0925T0821_s000.json", "cache/bounce_pilot/chunk_eda301d9_0821.tile.csv",
     "cache/pgc_fieldtest/365c798c-6554-42b1-b0e6-b2825e73d264.calib.json"),
    ("chunk 2", "eval/labels/bounces/cvat_c199a97c_0926T0538_s002.json", "cache/bounce_pilot/chunk2_c199a97c_0538_s002.tile.csv",
     "cache/pgc_fieldtest/34fab44c-a9a4-4719-bea3-d5a611d54576.calib.json"),
    ("chunk 3c", "eval/labels/bounces/cvat_eda301d9_0926T0538_s000_120-360.json", "cache/bounce_pilot/chunk3c_eda301d9_0538_s000.tile.csv",
     "cache/pgc_fieldtest/7358ef3f-6a41-4abe-b431-807eba7bc9f1.calib.json"),
]
NET, KITCHEN = 22.0, 7.0
BAR, MIN_N = 0.80, 10


def zone(y):
    if y < NET - KITCHEN: return "near_deep"
    if y < NET: return "near_kitchen"
    if y < NET + KITCHEN: return "far_kitchen"
    return "far_deep"


def near_line(y, ft=1.0):
    return any(abs(y - l) <= ft for l in (NET - KITCHEN, NET, NET + KITCHEN))


def main():
    import eval_bounce_recovery as E
    pooled = collections.defaultdict(lambda: [0, 0, 0])  # side -> marked, found, right
    confusion = collections.Counter(); close = 0; total = 0
    for name, lab, csv_, calib in CHUNKS:
        L = json.load(open(lab))
        H, raw, tracked, cands = E.clip_points({"calib": calib, "csv": csv_})
        per = collections.defaultdict(lambda: [0, 0, 0])
        for b in L["bounces"]:
            ty = project(H, b["x"], b["y"])[1]; tz = zone(ty); side = tz.split("_")[0]
            total += 1; close += near_line(ty)
            r = recover({"frame": b["frame"], "x": b["x"], "y": b["y"], "visible": True}, raw, tracked, cands, H)
            per[side][0] += 1
            if not r["found"]: continue
            c = min((f for f in cands if abs(f - b["frame"]) <= 3 and
                     ((cands[f][0] - b["x"]) ** 2 + (cands[f][1] - b["y"]) ** 2) ** 0.5 <= 15), key=lambda f: abs(f - b["frame"]))
            sz = zone(project(H, *cands[c])[1])
            per[side][1] += 1; per[side][2] += sz == tz; confusion[(tz, sz)] += 1
        prec = sum(any(abs(c - b["frame"]) <= 3 for b in L["bounces"]) for c in cands)
        for side in ("near", "far"):
            m, f, ok = per[side]
            print(f"{name:9s} {side:4s} marked {m:3d}  found {f:3d}  right zone {ok:3d}" + (f"  ({ok / f:.0%})" if f else ""))
            for i in range(3): pooled[side][i] += per[side][i]
        print(f"{name:9s} candidate precision {prec} of {len(cands)}")
    print("\nzone confusion (truth -> system):", dict(confusion))
    print(f"marks within 1 ft of a kitchen line or the net: {close} of {total} ({close / total:.0%})")
    verdict = {}
    for side in ("near", "far"):
        m, f, ok = pooled[side]
        verdict[side] = "UNDERPOWERED" if f < MIN_N else ("usable" if ok / f >= BAR else "not usable")
        print(f"POOLED {side:4s} marked {m:3d}  found {f:3d}  right zone {ok:3d}" + (f" ({ok / f:.0%})" if f else "") + f"  -> {verdict[side]}")


if __name__ == "__main__":
    main()
