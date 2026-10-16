"""Create the CVAT project 'scale-dropped-review' with one task per clip in clips/scale_review/ (2026-10-15).
Labels: not_a_rally, real_rally, unsure (tag one per clip). Uses a short-lived API token for the local
CVAT superuser, read from the cvat_server container at run time and deleted at the end; never printed.
Run: .venv/bin/python scripts/cvat_make_scale_review.py
"""
import csv, subprocess, sys, time
import requests

BASE = "http://localhost:8080"
DC = ["docker", "--context", "desktop-linux", "exec", "cvat_server", "python3", "manage.py", "shell", "-c"]


def token():
    code = ("from rest_framework.authtoken.models import Token\nfrom django.contrib.auth import get_user_model\n"
            "u=get_user_model().objects.get(username='tonychu')\nt,_=Token.objects.get_or_create(user=u)\nprint('KEY='+t.key)")
    out = subprocess.run(DC + [code], capture_output=True, text=True, check=True).stdout
    return [l for l in out.splitlines() if l.startswith("KEY=")][0][4:]


def drop_token():
    code = ("from rest_framework.authtoken.models import Token\nToken.objects.filter(user__username='tonychu').delete()\nprint('deleted')")
    subprocess.run(DC + [code], capture_output=True, text=True)


def main():
    h = {"Authorization": f"Token {token()}"}
    try:
        p = requests.post(f"{BASE}/api/projects", headers=h, json={
            "name": "scale-dropped-review",
            "labels": [{"name": n, "type": "any", "attributes": []} for n in ("not_a_rally", "real_rally", "unsure")]})
        p.raise_for_status(); pid = p.json()["id"]
        print("project", pid)
        for r in csv.DictReader(open("clips/scale_review/KEY.csv")):
            name = f"d-{int(r['clip']):02d} {r['session'][:8]} {float(r['start']):.0f}-{float(r['end']):.0f}s"
            t = requests.post(f"{BASE}/api/tasks", headers=h, json={"name": name, "project_id": pid}); t.raise_for_status()
            tid = t.json()["id"]
            with open(r["file"], "rb") as fh:
                d = requests.post(f"{BASE}/api/tasks/{tid}/data", headers=h, data={"image_quality": 80},
                                  files={"client_files[0]": fh}); d.raise_for_status()
            for _ in range(120):
                s = requests.get(f"{BASE}/api/tasks/{tid}", headers=h).json()
                if s.get("size", 0) > 0: break
                time.sleep(1)
            print("task", tid, name, "frames", s.get("size"))
    finally:
        drop_token()
        print("token removed")


if __name__ == "__main__":
    main()
