"""Spike: is RunPod Serverless (not raw Pods) the right compute unit for
ADR-093's "move everything off the operator's workstation" plan?

Context (DECISIONS.md ADR-093, 2026-09-10 addendum): the 2026-08-26 baked-
image test measured raw Pods -- 113.4s cold (worse than the 79.6s
no-image-bake baseline), then ~52.7s average once a host's Docker layer
cache was warm, but all 6 measurements happened within ~15 minutes of each
other, so whether that cache survives real gaps between jobs (hours, not
minutes) was never checked, and DEFAULT_IMAGE was never switched over.
Serverless was ruled out back on 2026-08-26/09-05, but for reasons that no
longer apply to today's architecture: the 10MB/20MB /run//runsync payload
cap only mattered when the plan was uploading video straight into the
request body -- today's pipeline already passes everything through R2
(r2_storage.py, confirmed working), so a real job's invocation payload is a
few hundred bytes of R2 keys, nowhere near that cap. And RunPod's own
FlashBoot is a purpose-built cache for this exact "my image is huge, cold
start is slow" problem -- never tried, because Serverless looked wrong for
an unrelated reason (09-05 ruled it out for hosting the lightweight CPU-only
*orchestrator*, which is a different role than running the actual GPU job).

This script answers the timing question for real rather than assuming
either outcome. It does NOT touch run_cloud_job.py or job_runner.py --
nothing production depends on this yet.

    python3 -m cloud_pipeline.serverless_spike setup      # one-time: template + endpoint
    python3 -m cloud_pipeline.serverless_spike invoke     # fire one job, time it, print the result
    python3 -m cloud_pipeline.serverless_spike teardown   # delete the endpoint + template

`invoke` is meant to be re-run standalone, spaced out over real hours (not
in one sitting) -- that gap is exactly what the 08-26 test never covered.
State lives in serverless_spike_state.json (gitignored, has real account
ids) so `invoke` doesn't need `setup` re-run each time.
"""
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(REPO_ROOT, ".env"))

from cloud_pipeline.runpod_pod import DEFAULT_GPU_TYPES, FALLBACK_GPU_TYPES  # noqa: E402

MANAGEMENT_API = "https://rest.runpod.io/v1"
RUN_API = "https://api.runpod.ai/v2"
IMAGE = "tonychu805/pic-vision-tracknet:serverless-spike"
STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "serverless_spike_state.json")

# Serverless workers report unhealthy and get recycled if idle too briefly
# for a spike fired by hand every so often; 15s (vs. the platform default
# of 5s) just avoids tearing a worker down between typing the command and
# it actually running. Not a production value -- a real endpoint would tune
# this against real request cadence.
IDLE_TIMEOUT_SEC = 15
WORKERS_MAX = 1


def _headers():
    return {"Authorization": f"Bearer {os.environ['RUNPOD_API_KEY']}", "Content-Type": "application/json"}


def _load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {}


def _save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def create_template(name, image, container_disk_gb=25):
    body = {
        "name": name,
        "imageName": image,
        "isServerless": True,
        "containerDiskInGb": container_disk_gb,
    }
    r = requests.post(f"{MANAGEMENT_API}/templates", headers=_headers(), json=body, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def create_endpoint(name, template_id, gpu_type_ids=None):
    """Same GPU-type-fallback list runpod_pod.py already validated for
    Pods -- confirmed against RunPod's own OpenAPI spec (2026-09-10) that
    Serverless endpoints accept the identical gpuTypeIds strings."""
    body = {
        "name": name,
        "templateId": template_id,
        "gpuTypeIds": gpu_type_ids or FALLBACK_GPU_TYPES,
        "workersMin": 0,
        "workersMax": WORKERS_MAX,
        "idleTimeout": IDLE_TIMEOUT_SEC,
        "flashboot": True,
    }
    r = requests.post(f"{MANAGEMENT_API}/endpoints", headers=_headers(), json=body, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def delete_endpoint(endpoint_id):
    requests.delete(f"{MANAGEMENT_API}/endpoints/{endpoint_id}", headers=_headers(), timeout=30)


def delete_template(template_id):
    requests.delete(f"{MANAGEMENT_API}/templates/{template_id}", headers=_headers(), timeout=30)


def run_job(endpoint_id, payload=None):
    r = requests.post(f"{RUN_API}/{endpoint_id}/run", headers=_headers(),
                       json={"input": payload or {}}, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def poll_status(endpoint_id, job_id, timeout_sec=180, poll_sec=2):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        r = requests.get(f"{RUN_API}/{endpoint_id}/status/{job_id}", headers=_headers(), timeout=15)
        r.raise_for_status()
        d = r.json()
        if d["status"] in ("COMPLETED", "FAILED"):
            return d
        time.sleep(poll_sec)
    raise TimeoutError(f"job {job_id} still {d.get('status')} after {timeout_sec}s")


def cmd_setup():
    state = _load_state()
    if state.get("endpoint_id"):
        print(f"already set up: endpoint {state['endpoint_id']} -- delete "
              f"{STATE_PATH} first if you want a clean one")
        return
    print(f"creating template ({IMAGE})...")
    template_id = create_template("pic-vision-serverless-spike", IMAGE)
    print(f"  template_id={template_id}")
    print("creating endpoint...")
    endpoint_id = create_endpoint("pic-vision-serverless-spike", template_id)
    print(f"  endpoint_id={endpoint_id}")
    _save_state({"template_id": template_id, "endpoint_id": endpoint_id})
    print(f"saved to {STATE_PATH} -- run `invoke` now for a cold number, "
          f"then again after a real gap (hours) to check FlashBoot persistence")


def cmd_invoke():
    state = _load_state()
    endpoint_id = state.get("endpoint_id")
    if not endpoint_id:
        sys.exit("no endpoint yet -- run `setup` first")
    print(f"[{time.strftime('%H:%M:%S')}] submitting job to endpoint {endpoint_id}...")
    submitted_at = time.time()
    job_id = run_job(endpoint_id)
    result = poll_status(endpoint_id, job_id)
    elapsed = time.time() - submitted_at
    print(f"[{time.strftime('%H:%M:%S')}] status={result['status']} "
          f"wall_clock={elapsed:.1f}s")
    print(json.dumps(result.get("output"), indent=2))
    if result["status"] != "COMPLETED":
        print(json.dumps(result, indent=2))


def cmd_teardown():
    state = _load_state()
    if state.get("endpoint_id"):
        print(f"deleting endpoint {state['endpoint_id']}...")
        delete_endpoint(state["endpoint_id"])
    if state.get("template_id"):
        print(f"deleting template {state['template_id']}...")
        delete_template(state["template_id"])
    if os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)
    print("torn down")


if __name__ == "__main__":
    if not os.environ.get("RUNPOD_API_KEY"):
        sys.exit("RUNPOD_API_KEY not set (.env)")
    cmd = sys.argv[1] if len(sys.argv) > 1 else None
    {"setup": cmd_setup, "invoke": cmd_invoke, "teardown": cmd_teardown}.get(
        cmd, lambda: sys.exit(__doc__))()
