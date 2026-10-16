"""Create the CVAT project 'bounce-chunk2-pgc' (2026-10-16): the second unselected bounce chunk, one whole
short session (c199a97c 2026-09-26 05:38 session-002, 4.1 min, different camera and day from the first
chunk eda301d9 2026-09-25 08:21 session-000). One task, split into jobs of 900 frames (30 s) so it can be
labelled in sittings; task frame i = source frame i. Label: 'bounce' (points), one Shape per bounce, as in
the first chunk. Uses a short-lived API token for the local CVAT superuser (see cvat_make_scale_review.py).
Run: .venv/bin/python scripts/cvat_make_bounce_chunk.py
"""
import time
import requests
from cvat_make_scale_review import BASE, token, drop_token

VIDEO = "pgc-fieldtest-sept2026/c199a97c-c51f-4620-8523-b2837f48c1a7/2026-09-26T05-38-15-376Z/session-002.mkv"
JOB_FRAMES = 900


def main():
    h = {"Authorization": f"Token {token()}"}
    try:
        p = requests.post(f"{BASE}/api/projects", headers=h, json={
            "name": "bounce-chunk2-pgc", "labels": [{"name": "bounce", "type": "points", "attributes": []}]})
        p.raise_for_status(); pid = p.json()["id"]
        t = requests.post(f"{BASE}/api/tasks", headers=h, json={
            "name": "c199a97c 0926T0538 s002", "project_id": pid, "segment_size": JOB_FRAMES})
        t.raise_for_status(); tid = t.json()["id"]
        with open(VIDEO, "rb") as fh:
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
    main()
