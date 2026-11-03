"""Create a CVAT project 'serve-review-<side>' with one task per clip in
cache/serve_review/<side>/ (the serve candidates from propose_serves.py).

--side far (default) or near; the near set is the near-side precision pass.

Labels (per the house bounce/hit + scale-review pattern):
  serve_contact  (points) -- click the ball at the serve-contact frame.
                            Marking it = "yes, this is a far serve" (timed+located GT).
  not_serve      (tag)    -- the proposed moment is not a serve.
  wrong_side     (tag)    -- a real serve, but tagged the wrong side.

The proposed serve sits ~3s into each 8s clip (window was serve_t-3 .. serve_t+5).

Uses a short-lived API token for the local CVAT superuser, minted from the
cvat_server container at run time and deleted at the end; never printed.
Run: PYTHONPATH=. .venv/bin/python scripts/cvat_make_serve_review.py
"""
import argparse, csv, pathlib, subprocess, time
import requests

BASE = "http://localhost:8080"
DC = ["docker", "--context", "desktop-linux", "exec", "cvat_server", "python3", "manage.py", "shell", "-c"]
LABELS = [
    {"name": "serve_contact", "type": "points", "attributes": []},
    {"name": "not_serve", "type": "tag", "attributes": []},
    {"name": "wrong_side", "type": "tag", "attributes": []},
    {"name": "unsure", "type": "tag", "attributes": []},
]


def token():
    code = ("from rest_framework.authtoken.models import Token\nfrom django.contrib.auth import get_user_model\n"
            "u=get_user_model().objects.get(username='tonychu')\nt,_=Token.objects.get_or_create(user=u)\nprint('KEY='+t.key)")
    out = subprocess.run(DC + [code], capture_output=True, text=True, check=True).stdout
    return [l for l in out.splitlines() if l.startswith("KEY=")][0][4:]


def drop_token():
    code = ("from rest_framework.authtoken.models import Token\nToken.objects.filter(user__username='tonychu').delete()\nprint('deleted')")
    subprocess.run(DC + [code], capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", default="far", choices=["far", "near"])
    side = ap.parse_args().side
    clips = pathlib.Path(f"cache/serve_review/{side}")
    h = {"Authorization": f"Token {token()}"}
    try:
        p = requests.post(f"{BASE}/api/projects", headers=h, json={"name": f"serve-review-{side}", "labels": LABELS})
        p.raise_for_status(); pid = p.json()["id"]
        print("project", pid, f"serve-review-{side}")
        rows = list(csv.DictReader(open(clips / "review.csv")))
        for r in rows:
            f = clips / r["clip"]
            if not f.exists():
                print("  SKIP missing", r["clip"]); continue
            name = (f"{int(r['idx']):02d} {r['session'][:8]} t{float(r['serve_t']):.0f}s "
                    f"cy{float(r['court_y']):.0f} sw{r['swing_px_s']}")
            t = requests.post(f"{BASE}/api/tasks", headers=h, json={"name": name, "project_id": pid})
            t.raise_for_status(); tid = t.json()["id"]
            with open(f, "rb") as fh:
                d = requests.post(f"{BASE}/api/tasks/{tid}/data", headers=h,
                                  data={"image_quality": 80, "use_zip_chunks": True, "sorting_method": "lexicographical"},
                                  files={"client_files[0]": fh})
                d.raise_for_status()
            s = {}
            for _ in range(180):
                s = requests.get(f"{BASE}/api/tasks/{tid}", headers=h).json()
                if s.get("size", 0) > 0:
                    break
                time.sleep(1)
            print("  task", tid, name, "frames", s.get("size"))
        print(f"\n{len(rows)} tasks -> project {pid}. Open: {BASE}/projects/{pid}")
    finally:
        drop_token()
        print("token removed")


if __name__ == "__main__":
    main()
