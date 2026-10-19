"""Create the CVAT project 'hit-chunk3c-pgc' (2026-10-18, PIC-226): mark every paddle hit in the first two minutes of
bounce chunk 3c (eda301d9 2026-09-26 05:38 session-000, source 2:00-4:00), where every bounce is already marked. Gives
the first exhaustive hit count; minute 1 (task frames 0-1799) to develop on, minute 2 (1800-3599) held back.
Clip cut from clips/bounce_chunk3/eda301d9_0926T0538_s000_120-360.mp4 (CFR 30), first 3600 frames, so task frame i =
chunk-3c frame i = source frame 3600 + i. Jobs of 900 frames (30 s). Labels (points): 'hit' = click the ball at the
frame the paddle meets it (the paddle if the ball is hidden); 'hit_unsure' = probably a hit, not certain.
--minute3 (2026-10-19): adds a task to the same project for chunk-3c minute 3 (source 4:00-5:00), the held-out test
set for the swing + ball hit rule. Clip cut from the 120-360 clip, frames 3600-5399 (frame match verified), so task
frame i = chunk-3c frame 3600 + i = source frame 7200 + i. Jobs of 900 frames.
--glare (2026-10-19): a separate project 'hit-chunk2-glare-pgc' for the glare court (camera c199a97c 2026-09-26
05:38 session-002), minutes 0-1 (session frames 0-3599, the two busiest), where every bounce is already marked
(CVAT project 7). Clip from frame 0 of session-002, so task frame i = session frame i (no offset); same labels/jobs.
This is the second-court generalization test for the swing + ball hit rule (ADR-157).
Run: PYTHONPATH=scripts .venv/bin/python scripts/cvat_make_hit_chunk.py [--minute3 | --glare]
"""
import sys, time
import requests
from cvat_make_scale_review import BASE, token, drop_token

PROJECT, TASK = "hit-chunk3c-pgc", "eda301d9 0926T0538 s000 120-240s hits"
VIDEO = "clips/bounce_chunk3/eda301d9_0926T0538_s000_120-240.mp4"
PROJECT_ID = 13
GLARE_PROJECT = "hit-chunk2-glare-pgc"
TASKG, VIDEOG = "c199a97c 0926T0538 s002 0-120s hits (glare court)", "clips/bounce_chunk3/c199a97c_0926T0538_s002_0-120.mp4"
TASK3, VIDEO3 = "eda301d9 0926T0538 s000 240-300s hits (minute 3)", "clips/bounce_chunk3/eda301d9_0926T0538_s000_240-300.mp4"


def main():
    h = {"Authorization": f"Token {token()}"}
    try:
        m3, glare = "--minute3" in sys.argv, "--glare" in sys.argv
        if glare:
            p = requests.post(f"{BASE}/api/projects", headers=h, json={"name": GLARE_PROJECT, "labels": [
                {"name": "hit", "type": "points", "attributes": []}, {"name": "hit_unsure", "type": "points", "attributes": []}]})
            p.raise_for_status(); pid, name, video = p.json()["id"], TASKG, VIDEOG
        elif m3:
            pid, name, video = PROJECT_ID, TASK3, VIDEO3
        else:
            p = requests.post(f"{BASE}/api/projects", headers=h, json={"name": PROJECT, "labels": [
                {"name": "hit", "type": "points", "attributes": []}, {"name": "hit_unsure", "type": "points", "attributes": []}]})
            p.raise_for_status(); pid, name, video = p.json()["id"], TASK, VIDEO
        t = requests.post(f"{BASE}/api/tasks", headers=h, json={"name": name, "project_id": pid, "segment_size": 900})
        t.raise_for_status(); tid = t.json()["id"]
        with open(video, "rb") as fh:
            requests.post(f"{BASE}/api/tasks/{tid}/data", headers=h, data={"image_quality": 90},
                          files={"client_files[0]": fh}).raise_for_status()
        for _ in range(600):
            s = requests.get(f"{BASE}/api/tasks/{tid}", headers=h).json()
            if s.get("size", 0) > 0: break
            time.sleep(1)
        jobs = requests.get(f"{BASE}/api/jobs", headers=h, params={"task_id": tid, "page_size": 100}).json()["results"]
        print("project", pid, "task", tid, "frames", s.get("size"), "jobs", [j["id"] for j in jobs])
    finally:
        drop_token(); print("token removed")


if __name__ == "__main__":
    main()
