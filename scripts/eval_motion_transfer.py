"""Does the speed-ratio rule found on one chunk hold on other cameras and times? (2026-10-15)

The rule: speed after / speed before the event (a line fit to the 8 tracked frames either
side; scripts/eval_motion_hit_vs_bounce.py) is < 0.95 for a bounce and >= 0.95 for a paddle
hit. Threshold 0.95 and all features are FIXED from the first chunk (eda301d9 2026-09-25 08:21:
23 bounces, 13 hits; AUC 0.88, leave-one-out 83%); nothing is refitted here.

New events: every tile-arm candidate in the 18 PGC pilot clips (3 cameras, 6 recordings), 28 of
them, which the operator tags in CVAT project 'pilot-candidate-review' (5): bounce, paddle_hit,
not_ball, unsure. Tracks are the tile arm's tracked points on the cut clip (cache/bounce_pilot/
<clip>.tile.csv); an event near a clip edge may lack 3 points on one side and is then skipped.

BAR, fixed BEFORE any tag exists.
  coverage      the rule is computable for >= 70% of the bounce/hit-tagged events
  accuracy      at 0.95: >= 75% of computable bounce/hit events classified correctly
  hits          if there are >= 6 hits: >= 60% of them have ratio >= 0.95
  direction     AUC(bounce > hit) <= 0.25 (same direction as before)
If there are fewer than 6 hits, 'hits' is not assessed and the run is reported as inconclusive
on hits; the bounce keep-rate (ratio < 0.95) is still reported.
Run: .venv/bin/python scripts/eval_motion_transfer.py
"""
import json, subprocess, sys
import numpy as np
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import eval_bounce_recovery as E
import eval_motion_hit_vs_bounce as M

PROJECT = 5
THR = 0.95


def tags():
    q = f"""select t.name, l.name from engine_task t join engine_segment s on s.task_id=t.id join engine_job j on j.segment_id=s.id
            join engine_labeledimage i on i.job_id=j.id join engine_label l on l.id=i.label_id where t.project_id={PROJECT}"""
    r = subprocess.run(["docker", "--context", "desktop-linux", "exec", "cvat_db", "psql", "-U", "root", "-d", "cvat",
                        "-tA", "-F", "|", "-c", q], capture_output=True, text=True, check=True).stdout
    return {int(l.split("|")[0].split(" ")[0][2:]): l.split("|")[1] for l in r.splitlines()}


def main():
    meta = {o["n"]: o for o in json.load(open("cache/bounce_pilot/pilot_candidate_review.json"))}
    tg = tags()
    print(f"candidates {len(meta)}, tagged {len(tg)}: " + ", ".join(f"{k} {list(tg.values()).count(k)}" for k in
          ("bounce", "paddle_hit", "not_ball", "unsure")))
    cache = {}
    rows = []
    for n, lab in sorted(tg.items()):
        if lab not in ("bounce", "paddle_hit"): continue
        o = meta[n]
        if o["clip"] not in cache:
            c = next(c for c in json.load(open("eval/labels/bounces/sample.json"))["clips"] if c["id"] == o["clip"])
            cache[o["clip"]] = E.clip_points({"calib": c["calib"], "csv": f"cache/bounce_pilot/{o['clip']}.tile.csv"})[2]
        ft = M.feats(cache[o["clip"]], o["clip_frame"])
        rows.append((n, o["clip"], lab, ft["speed_ratio"] if ft else None))
    ok = [r for r in rows if r[3] is not None]
    print(f"bounce/hit events {len(rows)}; rule computable for {len(ok)} ({len(ok) / max(len(rows), 1):.0%})")
    b = [r[3] for r in ok if r[2] == "bounce"]; h = [r[3] for r in ok if r[2] == "paddle_hit"]
    for r in sorted(ok, key=lambda r: r[3]): print(f"   p-{r[0]:02d} {r[1]}  {r[2]:10s} ratio {r[3]:.2f}")
    correct = sum(1 for x in b if x < THR) + sum(1 for x in h if x >= THR)
    acc = correct / max(len(ok), 1)
    print(f"bounces {len(b)}: kept (ratio<{THR}) {sum(1 for x in b if x < THR)};  hits {len(h)}: caught {sum(1 for x in h if x >= THR)}")
    print(f"accuracy {acc:.0%};  chance-level (always 'bounce') {len(b) / max(len(ok), 1):.0%}")
    a = M.auc(b, h) if b and h else None
    print("AUC(bounce > hit):", "n/a" if a is None else f"{a:.2f}")
    cov = len(ok) / max(len(rows), 1) >= 0.7
    print(f"coverage {'PASS' if cov else 'FAIL'}   accuracy {'PASS' if acc >= 0.75 else 'FAIL'}   "
          f"hits {'n/a (<6 hits)' if len(h) < 6 else ('PASS' if sum(1 for x in h if x >= THR) / len(h) >= 0.6 else 'FAIL')}   "
          f"direction {'n/a' if a is None else ('PASS' if a <= 0.25 else 'FAIL')}")


if __name__ == "__main__":
    main()
