"""Tonight's blurred copies for one venue: the console's `archive` job (operator 2026-11-24).

During the day each finished part leaves its proxy video, its poses (every 2nd
frame, from the hit finder) and its calibration in the ingest bucket
(pod_driver.stash_for_archive). From 00:00 venue time the console hands one
`archive` job per venue to a CPU-only machine, which runs this through
pod_driver.py (JOB_KIND=archive). It asks the console for one stashed part at a
time, makes the copy with src/session_archive.redact_video, uploads it through
the one-file link it was given, and reports. The console then deletes that
part's stash, so nothing unblurred outlives its copy, and whatever is still
stashed at 06:00 venue time is deleted without a copy.

Every part is tried once. A failure is reported as such and the console deletes
that stash: an unblurred part is never kept for a retry.
"""
import gzip
import json
import os
import shutil
import sys
import threading
import time

import requests

from src.session_archive import ArchiveRefused, redact_video

DOWNLOAD_TIMEOUT_SEC = 600
FINAL_REPORT_ATTEMPTS = 5
# The orchestrator counts the machine as started when the job's stage moves off
# 'queued', and the console treats a running job silent for 30 minutes as stale.
HEARTBEAT_SEC = 60


def _log(msg):
    print(f"[archive {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _download(url, path, http):
    with http.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT_SEC) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            shutil.copyfileobj(r.raw, f)


def copy_one(item, base, headers, deadline, workdir, now=time.time, http=requests, redact=redact_video, workers=None):
    """Make, upload and report one part's copy. None when a copy was kept, else why not. Never raises."""
    paths = {name: os.path.join(workdir, name) for name in ("proxy.mp4", "poses.json.gz", "calib.json", "copy.mp4")}
    report = {"input_id": item["input_id"]}
    try:
        _download(item["proxy_url"], paths["proxy.mp4"], http)
        _download(item["poses_url"], paths["poses.json.gz"], http)
        _download(item["calib_url"], paths["calib.json"], http)
        with gzip.open(paths["poses.json.gz"], "rt") as f:
            poses = json.load(f)
        with open(paths["calib.json"]) as f:
            calib = json.load(f)
        started = now()
        res = redact(paths["proxy.mp4"], paths["copy.mp4"], calib, poses, workers=workers,
                     should_stop=lambda: now() >= deadline)
        with open(paths["copy.mp4"], "rb") as f:
            http.put(item["upload_url"], data=f, headers={"Content-Type": "video/mp4"}, timeout=DOWNLOAD_TIMEOUT_SEC).raise_for_status()
        report.update(key=item["key"], bytes=res["bytes"], frames=res["frames"], seconds=res["seconds"], version=res["version"])
        http.post(f"{base}/report", json=report, headers=headers, timeout=30).raise_for_status()
        _log(f"copy kept: {res['frames']} frames in {now() - started:.0f}s, {res['bytes'] / 1e6:.1f} MB")
        return None
    except Exception as e:  # noqa: BLE001 -- one part's failure must not stop the night's other parts
        why = str(e) if isinstance(e, ArchiveRefused) else f"{type(e).__name__}: {e}"
        _log(f"no copy for this part: {why}")
        try:
            http.post(f"{base}/report", json={**report, "failed": why[:500]}, headers=headers, timeout=30)
        except Exception:  # noqa: BLE001 -- the 06:00 sweep deletes the stash anyway
            pass
        return why
    finally:
        for p in paths.values():
            if os.path.exists(p):
                os.remove(p)


def run(console_url, job_id, token, deadline, workdir, now=time.time, http=requests, redact=redact_video, workers=None):
    """Copy stashed parts until the console has none left or the deadline passes. Returns (kept, why each other part failed)."""
    base = f"{console_url}/api/runner/jobs/{job_id}/archive"
    headers = {"Authorization": f"Bearer {token}"}
    os.makedirs(workdir, exist_ok=True)
    kept, failures = 0, []
    while now() < deadline:
        r = http.get(f"{base}/next", headers=headers, timeout=30)
        r.raise_for_status()
        item = r.json()
        if item.get("done"):
            break
        why = copy_one(item, base, headers, deadline, workdir, now, http, redact, workers)
        if why is None:
            kept += 1
        else:
            failures.append(why[:300])
    return kept, failures


def _final_report(console_url, job_id, token, **fields):
    for attempt in range(FINAL_REPORT_ATTEMPTS):
        try:
            r = requests.patch(f"{console_url}/api/runner/jobs/{job_id}", json=fields,
                               headers={"Authorization": f"Bearer {token}"}, timeout=30)
            if r.status_code == 409 or r.ok:
                return
            r.raise_for_status()
        except requests.RequestException as e:
            _log(f"final report failed ({e})")
            time.sleep(5 * 2 ** attempt)


def _report_alive(console_url, job_id, token):
    try:
        requests.patch(f"{console_url}/api/runner/jobs/{job_id}", json={"stage": "archiving", "message": "making tonight's blurred copies"},
                       headers={"Authorization": f"Bearer {token}"}, timeout=30)
    except requests.RequestException as e:
        _log(f"heartbeat failed ({e})")


def _heartbeat(console_url, job_id, token, stop):
    """Tell the console this job is alive every HEARTBEAT_SEC until stopped."""
    while not stop.wait(HEARTBEAT_SEC):
        _report_alive(console_url, job_id, token)


def main():
    from src.cpus import usable_cpus
    console_url = os.environ.get("CONSOLE_URL", "https://console.picvisionai.com").rstrip("/")
    job_id, token = os.environ["JOB_ID"], os.environ["JOB_TOKEN"]
    deadline = float(os.environ["ARCHIVE_DEADLINE"])
    _report_alive(console_url, job_id, token)
    stop = threading.Event()
    threading.Thread(target=_heartbeat, args=(console_url, job_id, token, stop), daemon=True).start()
    try:
        kept, failures = run(console_url, job_id, token, deadline, "/workspace/job", workers=usable_cpus())
    except Exception as e:  # noqa: BLE001 -- report it; the 06:00 sweep deletes every stash left
        _log(f"FAILED: {e}")
        _final_report(console_url, job_id, token, error=str(e)[:2000])
        return 1
    finally:
        stop.set()
    _log(f"night done: {kept} copies kept, {len(failures)} parts without one")
    _final_report(console_url, job_id, token, done=True, stage="done", message="done",
                  progress=None, result={"archive_kept": kept, "archive_failed": len(failures), "archive_failures": failures})
    return 0


if __name__ == "__main__":
    sys.exit(main())
