"""Export bounce labels from the local CVAT project 'bounce-pilot-pgc' to the format
eval_bounce_recovery.py reads (eval/labels/bounces/labels.jsonl).

Reads CVAT's database directly (stored Shapes and Track keyframes alike) rather than CVAT's
export, which expands a Track to a point on every later frame. Clip frame i maps to source
frame ceil(start * fps) + i: the clips were cut with ffmpeg -ss start, re-encoded at 30 fps.
--complete-all treats every clip as fully marked (use only when the operator says so).
Run: .venv/bin/python scripts/cvat_to_bounce_labels.py [--complete-all]"""
import json, math, subprocess, sys
FPS = 30.0
Q = """select t.name, k.frame, ts.points from engine_trackedshape ts join engine_labeledtrack k on k.id=ts.track_id
 join engine_job j on j.id=k.job_id join engine_segment s on s.id=j.segment_id join engine_task t on t.id=s.task_id
 where t.project_id=2
 union all
 select t.name, l.frame, l.points from engine_labeledshape l join engine_job j on j.id=l.job_id
 join engine_segment s on s.id=j.segment_id join engine_task t on t.id=s.task_id where t.project_id=2 and l.type='points'"""


def main(complete_all):
    out = subprocess.run(["docker", "--context", "desktop-linux", "exec", "cvat_db", "psql", "-U", "root", "-d", "cvat",
                          "-tA", "-F", "|", "-c", Q], capture_output=True, text=True, check=True).stdout
    by = {}
    for line in out.splitlines():
        name, f, pts = line.split("|")
        x, y = (float(v) for v in pts.split(","))
        by.setdefault(name, []).append((int(f), x, y))
    clips = {c["id"]: c for c in json.load(open("eval/labels/bounces/sample.json"))["clips"]}
    with open("eval/labels/bounces/labels.jsonl", "w") as fh:
        for cid, c in clips.items():
            if c["set"] != "pgc" or cid not in by:
                continue
            first = math.ceil(c["start"] * FPS - 1e-6)
            bs = [{"frame": first + f, "t": round((first + f) / FPS, 3), "x": round(x, 1), "y": round(y, 1), "visible": True}
                  for f, x, y in sorted(by[cid])]
            fh.write(json.dumps({"clip": cid, "set": "pgc", "complete": complete_all, "source": "cvat", "bounces": bs}) + "\n")
            print(cid, len(bs))


if __name__ == "__main__":
    main("--complete-all" in sys.argv)
