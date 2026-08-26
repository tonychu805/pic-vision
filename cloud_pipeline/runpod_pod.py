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
import subprocess
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


def _headers():
    return {"Authorization": f"Bearer {os.environ['RUNPOD_API_KEY']}"}


def create_pod(name, ssh_pubkey, gpu_type_ids=None, image=DEFAULT_IMAGE,
                container_disk_gb=20):
    """Create a pod. Tries each GPU type in gpu_type_ids (default:
    DEFAULT_GPU_TYPES, currently just the RTX 2000 Ada match to local) in
    order until one succeeds -- retrying across *multiple* types was useful
    when the default list had several interchangeable options (confirmed
    2026-08-26: a specific type can 500 with "no instances available" while
    another succeeds immediately), but with a single pinned type there's
    nothing to fall back to; pass an explicit gpu_type_ids list to restore
    that behavior for a call site that doesn't need the same-as-local
    guarantee."""
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
            return r.json()["id"]
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


def ssh_run(ip, port, keyfile, remote_cmd, timeout_sec=1800):
    """Run a command on the pod over SSH. Raises on non-zero exit."""
    cmd = [
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=20", "-i", keyfile, "-p", str(port),
        f"root@{ip}", remote_cmd,
    ]
    subprocess.run(cmd, check=True, timeout=timeout_sec)


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
