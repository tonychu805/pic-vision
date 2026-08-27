"""RunPod pod lifecycle: create, wait for SSH, run commands, transfer files,
terminate. Uses the RunPod REST API + plain `ssh`/`scp` (no paramiko
dependency) -- the same mechanism validated manually in DECISIONS.md's
ADR-043 update (2026-08-26).

Deliberately uses RunPod's own maintained `runpod/pytorch` image family,
which bundles the PUBLIC_KEY-to-sshd startup script -- a plain Docker Hub
image (e.g. `ubuntu:22.04`) has no SSH daemon running by default.

Credentials: RUNPOD_API_KEY from the environment (.env, gitignored).
"""
import os
import queue
import subprocess
import threading
import time

import requests

API_BASE = "https://rest.runpod.io/v1"
DEFAULT_IMAGE = "runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04"
# Matches the local workstation's GPU on purpose (operator's call, 2026-08-26):
# every prior optimization in this project (ADR-064, ADR-065) was verified
# "byte-identical output" on the SAME GPU -- that guarantee doesn't
# automatically extend across different GPU architectures (different cuDNN
# kernel/algorithm selection, floating-point non-associativity), and that
# question has never been checked. Pinning to the identical card sidesteps
# it entirely instead of needing to verify it. No fallback list -- a
# fallback would silently trade this guarantee away exactly when it's least
# visible (a busy capacity night), so this fails loudly instead if
# unavailable. GPU type ID confirmed valid + available 2026-08-26
# ($0.24/hr) via a real (immediately terminated) pod creation.
DEFAULT_GPU_TYPES = [
    "NVIDIA RTX 2000 Ada Generation",
]

# Follow-up decision, same day (2026-08-26): the operator hit exactly the
# "busy capacity night" scenario the no-fallback comment above anticipated
# (a real 500 "no instances currently available" on the dashboard's first
# live cloud job) and asked for a fallback rather than a hard failure.
# Chosen to stay within the Ada Lovelace architecture -- not the pre-pin
# list's mix of Ampere/Ada cards (RTX 4090/3090/A4000/3080) -- on the
# reasoning that same-architecture cards are more likely to share cuDNN
# kernel selection than a cross-architecture jump, though this is NOT
# verified byte-identical the way the same-GPU guarantee was (ADR-064/065);
# accepted as an explicit availability-over-certainty trade, not a re-proof
# of consistency. IDs confirmed real via a live (read-only, no cost) RunPod
# GraphQL gpuTypes query, 2026-08-26.
#
# Widened same day, second time: the first (Ada-professional-only) list
# still failed outright on a real job (all 5 types "no instances currently
# available" simultaneously -- confirmed via that job's own log, not
# assumed). Operator asked whether the fallback had to stay Ada, or could
# use any similarly-priced NVIDIA card. Checked RunPod's real GPU pricing
# live (GraphQL lowestPrice) before answering rather than guess: the
# GeForce RTX 40-series cards (4090/4080 SUPER/4070 Ti) are consumer
# branding of the SAME Ada Lovelace architecture as the professional "RTX
# X000 Ada Generation" line -- not a compromise, and (checked at the time)
# more often available on RunPod's own Secure Cloud than the cheaper
# Ampere-generation cards, which run predominantly on Community Cloud
# (peer-hosted machines -- this pipeline's R2 credentials get sent to
# whatever pod is created, so Community Cloud is a real, separate
# credential-exposure tradeoff, not just an architecture one). Operator
# explicitly chose to add the consumer Ada cards but NOT go further into
# Ampere/Community-Cloud territory -- ordered here roughly professional-tier
# first, consumer-tier after.
FALLBACK_GPU_TYPES = [
    "NVIDIA RTX 2000 Ada Generation",
    "NVIDIA RTX 4000 Ada Generation",
    "NVIDIA RTX 4000 SFF Ada Generation",
    "NVIDIA RTX 5000 Ada Generation",
    "NVIDIA RTX 6000 Ada Generation",
    "NVIDIA GeForce RTX 4090",
    "NVIDIA GeForce RTX 4080 SUPER",
    "NVIDIA GeForce RTX 4070 Ti",
]


def _headers():
    return {"Authorization": f"Bearer {os.environ['RUNPOD_API_KEY']}"}


def create_pod(name, ssh_pubkey, gpu_type_ids=None, image=DEFAULT_IMAGE,
                container_disk_gb=20):
    """Create a pod. Tries each GPU type in gpu_type_ids (default:
    DEFAULT_GPU_TYPES, currently just the RTX 2000 Ada match to local) in
    order until one succeeds -- retrying across *multiple* types was useful
    when the default list had several interchangeable options (confirmed
    2026-08-26: a specific type can 500 with "no instances available" while
    another succeeds immediately). Pass FALLBACK_GPU_TYPES (or any explicit
    gpu_type_ids list) for a call site willing to trade the same-as-local
    guarantee for availability.

    Returns (pod_id, gpu_type) -- the caller may want to know which type
    actually got used (e.g. to flag a non-pinned GPU honestly in a status
    message), not just assume the first entry succeeded."""
    body = {
        "name": name,
        "imageName": image,
        "gpuCount": 1,
        "containerDiskInGb": container_disk_gb,
        "env": {"PUBLIC_KEY": ssh_pubkey},
        "ports": ["22/tcp"],
    }
    last_error = None
    for gpu_type in (gpu_type_ids or DEFAULT_GPU_TYPES):
        body["gpuTypeIds"] = [gpu_type]
        r = requests.post(f"{API_BASE}/pods", headers=_headers(), json=body, timeout=30)
        if r.status_code == 201:
            return r.json()["id"], gpu_type
        last_error = r.text
    raise RuntimeError(f"could not create pod on any GPU type: {last_error}")


def wait_for_ssh(pod_id, timeout_sec=180, poll_sec=5):
    """Poll until the pod has a public IP and SSH port mapping. Returns
    (ip, port)."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        r = requests.get(f"{API_BASE}/pods/{pod_id}", headers=_headers(), timeout=15)
        d = r.json()
        ip = d.get("publicIp")
        ports = d.get("portMappings") or {}
        if ip and "22" in ports:
            return ip, ports["22"]
        time.sleep(poll_sec)
    raise TimeoutError(f"pod {pod_id} never got a public IP/SSH port within {timeout_sec}s")


def ssh_run(ip, port, keyfile, remote_cmd, timeout_sec=1800, on_line=None):
    """Run a command on the pod over SSH. Raises on non-zero exit.

    With on_line=None (default, every existing call site's behavior,
    unchanged): blocks via subprocess.run, output goes wherever the parent
    process's stdout goes, nothing captured.

    With on_line=<callable>: streams stdout+stderr line-by-line via Popen,
    calling on_line(line) for each -- added so a long-running remote command
    (pod_infer.py's own inference loop, which already prints periodic
    "count/total fps ETA" progress lines) can feed a live progress display
    instead of the caller only finding out at the very end. Still enforces
    timeout_sec and still raises on non-zero exit, same contract as the
    non-streaming path."""
    cmd = [
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=20", "-i", keyfile, "-p", str(port),
        f"root@{ip}", remote_cmd,
    ]
    if on_line is None:
        subprocess.run(cmd, check=True, timeout=timeout_sec)
        return

    # A plain `for line in proc.stdout` blocks on the read syscall itself
    # with no timeout -- a remote command that hangs *without* printing
    # anything would never trip a deadline check placed between lines. A
    # reader thread + queue (same pattern as today's pod_infer.py
    # producer/consumer fix) lets the main loop poll with a real timeout
    # even when zero output is arriving.
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1)
    line_q = queue.Queue()

    def _read_lines():
        try:
            for line in proc.stdout:
                line_q.put(line.rstrip("\n"))
        finally:
            line_q.put(None)

    reader = threading.Thread(target=_read_lines, daemon=True)
    reader.start()

    deadline = time.time() + timeout_sec
    try:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(cmd, timeout_sec)
            try:
                line = line_q.get(timeout=min(remaining, 5.0))
            except queue.Empty:
                continue
            if line is None:
                break
            on_line(line)
        returncode = proc.wait(timeout=max(0.0, deadline - time.time()))
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    finally:
        if proc.stdout:
            proc.stdout.close()
        reader.join(timeout=5.0)
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, cmd)


def scp_to(ip, port, keyfile, local_path, remote_path):
    cmd = ["scp", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
           "-i", keyfile, "-P", str(port), local_path, f"root@{ip}:{remote_path}"]
    subprocess.run(cmd, check=True)


def scp_from(ip, port, keyfile, remote_path, local_path):
    cmd = ["scp", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
           "-i", keyfile, "-P", str(port), f"root@{ip}:{remote_path}", local_path]
    subprocess.run(cmd, check=True)


def terminate_pod(pod_id):
    requests.delete(f"{API_BASE}/pods/{pod_id}", headers=_headers(), timeout=30)


def generate_ephemeral_keypair(path_prefix):
    """Generates a throwaway ed25519 keypair for one job's pod. Returns
    (private_key_path, public_key_str)."""
    priv = f"{path_prefix}_id_ed25519"
    if os.path.exists(priv):
        os.remove(priv)
    subprocess.run(["ssh-keygen", "-t", "ed25519", "-f", priv, "-N", "",
                    "-C", "cloud-pipeline-ephemeral"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(priv + ".pub") as f:
        pub = f.read().strip()
    os.chmod(priv, 0o600)
    return priv, pub
