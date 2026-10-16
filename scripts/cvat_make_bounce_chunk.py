"""Create the CVAT project 'bounce-chunk2-pgc' (2026-10-16): the second unselected bounce chunk, one whole
short session (c199a97c 2026-09-26 05:38 session-002, 4.1 min, different camera and day from the first
chunk eda301d9 2026-09-25 08:21 session-000). One task, split into jobs of 900 frames (30 s) so it can be
labelled in sittings; task frame i = source frame i. Label: 'bounce' (points), one Shape per bounce, as in
the first chunk. Uses a short-lived API token for the local CVAT superuser (see cvat_make_scale_review.py).
Run: PYTHONPATH=scripts .venv/bin/python scripts/cvat_make_bounce_chunk.py [2|3]
"""
import sys, time
import requests
from cvat_make_scale_review import BASE, token, drop_token

CHUNKS = {   # name -> (project, task, video)
    "2": ("bounce-chunk2-pgc", "c199a97c 0926T0538 s002",
          "pgc-fieldtest-sept2026/c199a97c-c51f-4620-8523-b2837f48c1a7/2026-09-26T05-38-15-376Z/session-002.mkv"),
    # chunk 3 (2026-10-16): camera de3d1953, its best calibration match (52f4de24), minutes 2:00-6:00, chosen by
    # rule without looking at detections; cut at CFR 30 so clip frame i = source frame 3600 + i
    "3": ("bounce-chunk3-pgc", "de3d1953 0925T0824 s001 120-360s",
          "clips/bounce_chunk3/de3d1953_0925T0824_s001_120-360.mp4"),
    # chunk 3b: chunk 3 turned out to be casual hitting with several balls (operator, after 1 job). Replaced by the
    # first of the next four de3d1953 recordings (in calibration-match order) that the operator judged a real game
    # from an 8x preview, judged on game vs practice only: 0925 08:24 session-004 (calib 499ed4b8), minutes 2:00-6:00
    "3b": ("bounce-chunk3b-pgc", "de3d1953 0925T0824 s004 120-360s",
           "clips/bounce_chunk3/de3d1953_0925T0824_s004_120-360.mp4"),
}
JOB_FRAMES = 900


def main(chunk):
    project, task, video = CHUNKS[chunk]
    h = {"Authorization": f"Token {token()}"}
    try:
        p = requests.post(f"{BASE}/api/projects", headers=h, json={
            "name": project, "labels": [{"name": "bounce", "type": "points", "attributes": []}]})
        p.raise_for_status(); pid = p.json()["id"]
        t = requests.post(f"{BASE}/api/tasks", headers=h, json={
            "name": task, "project_id": pid, "segment_size": JOB_FRAMES})
        t.raise_for_status(); tid = t.json()["id"]
        with open(video, "rb") as fh:
            d = requests.post(f"{BASE}/api/tasks/{tid}/data", headers=h, data={"image_quality": 90},
                              files={"client_files[0]": fh})
            d.raise_for_status()
        for _ in range(600):
            s = requests.get(f"{BASE}/api/tasks/{tid}", headers=h).json()
            if s.get("size", 0) > 0: break
            time.sleep(1)
        jobs = requests.get(f"{BASE}/api/jobs", headers=h, params={"task_id": tid, "page_size": 100}).json()["results"]
        print("project", pid, "task", tid, "frames", s.get("size"), "jobs", len(jobs))
    finally:
        drop_token()
        print("token removed")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2")
