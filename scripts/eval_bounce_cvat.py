"""Score the bounce finder against hand labels exported from CVAT (one long video).
Same definitions as eval_bounce_recovery.py (+-3 frames, 15 px; seen / tracked / found,
court error in ft), but takes a CVAT-export json + a detections csv + a calib directly.
Run: .venv/bin/python scripts/eval_bounce_cvat.py LABELS.json DETECTIONS.csv CALIB.json"""
import json, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from src.bounce_eval import near_half, percentile, recover
import eval_bounce_recovery as E


def main(labels, csv, calib):
    L = json.load(open(labels))
    H, raw, tracked, cands = E.clip_points({"calib": calib, "csv": csv})
    res = []
    for b in L["bounces"]:
        r = recover({"frame": b["frame"], "x": b["x"], "y": b["y"], "visible": True}, raw, tracked, cands, H)
        res.append((near_half(H, b["x"], b["y"]), r))
    n = len(res)
    print(f"labelled bounces: {n};  finder candidates in video: {len(cands)}")
    for name, sel in (("all", lambda h: True), ("near", lambda h: h), ("far", lambda h: not h)):
        g = [r for h, r in res if sel(h)]
        if not g: continue
        m = len(g); f = lambda k: sum(1 for r in g if r[k]) / m
        errs = [r["cand_err_ft"] for r in g if r["found"]]
        med = percentile(errs, 0.5)
        print(f"{name:5s} n={m:3d} seen {f('seen'):4.0%} tracked {f('tracked'):4.0%} found {f('found'):4.0%} "
              f"median err {('%.2f ft' % med) if med is not None else '-'}")
    # precision proxy: candidates within +-3 frames of any label
    lf = [b["frame"] for b in L["bounces"]]
    hit = sum(1 for c in cands if any(abs(c - f) <= 3 for f in lf))
    print(f"candidates matching a label (+-3 frames): {hit} of {len(cands)}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
