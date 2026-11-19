"""Run pilot-phase reel jobs on this workstation's GPU (operator, 2026-11-19).

The Cloudflare orchestrator (console repo, orchestrator-worker/src/workstation.ts)
asks this workstation before RunPod and Google while WORKSTATION_FIRST is on.
This agent never accepts connections: every 10 s it checks in at
POST <ORCHESTRATOR_URL>/workstation/poll, starts the jobs it is handed, kills
the ones it is told to, and reports which are still running.

Each job runs exactly what a rented pod runs -- the pod-code tarball and
pod_driver.py, with the environment the orchestrator built -- inside a
bubblewrap sandbox: its own /workspace and /usr/local/bin (pod_driver.py
hard-codes both), the GPU and network, and the rest of the machine read-only.

Config (environment, e.g. from ~/.config/pic-vision/workstation.env):
  ORCHESTRATOR_URL   the orchestrator's workers.dev URL (staging or production)
  WORKSTATION_TOKEN  that orchestrator's WORKSTATION_TOKEN secret
  WORKSTATION_SLOTS  jobs at once (default 2: two 10-minute parts take 9.5 min
                     on the RTX 2000 Ada, EXPERIMENTS.md 2026-11-18)
  WORKSTATION_PYTHON interpreter with the pod's dependencies
  WORKSTATION_JOBS_DIR  per-job folders (default on /mnt/fast_scratch)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable

ID_RE = re.compile(r"^ws-[0-9a-f]{12}$")
POLL_SEC = 10
KILL_GRACE_SEC = 20

# Read-only system folders the job needs (Python, CUDA libraries, certificates, DNS).
RO_DIRS = ["/usr", "/etc", "/opt", "/home", "/var", "/run", "/snap", "/srv", "/mnt"]


def sandbox_command(env: dict, job_dir: Path, python: str) -> tuple[list[str], dict]:
    """The bubblewrap command for one job, and the environment it runs with.

    The environment is the orchestrator's pod environment plus PATH -- never
    this agent's own (which holds WORKSTATION_TOKEN).
    """
    ws, bin_dir = job_dir / "workspace", job_dir / "bin"
    ws.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)
    # This workstation's IPv6 route hangs: Python tried the console's two
    # IPv6 addresses for ~90 s each before IPv4 (181 s per request, measured
    # 2026-11-19). Each job gets a resolver setting that puts IPv4 first.
    gai = job_dir / "gai.conf"
    gai.write_text("precedence ::ffff:0:0/96  100\n")
    argv = ["bwrap", "--tmpfs", "/"]
    for d in RO_DIRS:
        if os.path.exists(d):
            argv += ["--ro-bind", d, d]
    for d in ["/bin", "/lib", "/lib64", "/lib32", "/sbin"]:
        if os.path.islink(d):
            argv += ["--symlink", os.readlink(d), d]
        elif os.path.exists(d):
            argv += ["--ro-bind", d, d]
    argv += [
        "--dev-bind", "/dev", "/dev", "--proc", "/proc", "--ro-bind", "/sys", "/sys",
        "--tmpfs", "/tmp",
        "--ro-bind", str(gai), "/etc/gai.conf",
        "--bind", str(ws), "/workspace",
        "--bind", str(bin_dir), "/usr/local/bin",
        "--chdir", "/workspace",
        "--die-with-parent", "--unshare-pid", "--new-session",
        "bash", "-c",
        # BOOTSTRAP_CMD (orchestrator adapters.ts) minus its pip installs:
        # WORKSTATION_PYTHON already has them.
        'curl -sfL "$BOOTSTRAP_URL" -o /tmp/deps.tar && '
        "tar -xf /tmp/deps.tar -C /workspace --no-same-owner && "
        f"cd /workspace && exec {python} -u pod_driver.py",
    ]
    # pod_driver.py starts the ball model as plain `python3`: WORKSTATION_PYTHON's
    # folder comes right after /usr/local/bin (pod_driver's own ffmpeg) so it is that one.
    venv_bin = os.path.dirname(python)
    job_env = {**env, "PATH": f"/usr/local/bin:{venv_bin}:/usr/bin:/bin", "HOME": "/workspace", "PYTHONUNBUFFERED": "1"}
    return argv, job_env


def spawn_job(job_id: str, env: dict, job_dir: Path, python: str):
    argv, job_env = sandbox_command(env, job_dir, python)
    log = open(job_dir / "job.log", "ab")
    return subprocess.Popen(argv, env=job_env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def kill_job(proc) -> None:
    if proc.poll() is not None:
        return
    pgid = os.getpgid(proc.pid)
    os.killpg(pgid, signal.SIGTERM)
    try:
        proc.wait(timeout=KILL_GRACE_SEC)
    except subprocess.TimeoutExpired:
        os.killpg(pgid, signal.SIGKILL)
        proc.wait()


class Agent:
    def __init__(self, post: Callable[[dict], dict], spawn, kill, jobs_dir: Path, slots: int, label: str):
        self.post, self.spawn, self.kill = post, spawn, kill
        self.jobs_dir, self.slots, self.label = Path(jobs_dir), slots, label
        self.procs: dict = {}

    def report(self) -> dict:
        return {"slots": self.slots, "label": self.label,
                "procs": [{"id": i, "running": p.poll() is None} for i, p in self.procs.items()]}

    def tick(self) -> None:
        try:
            reply = self.post(self.report())
        except Exception as err:  # noqa: BLE001 -- offline is normal; the orchestrator falls back to the cloud
            print(f"[workstation] check-in failed: {err}", flush=True)
            return
        for job_id in reply.get("kill", []):
            proc = self.procs.pop(job_id, None)
            if proc is not None:
                self.kill(proc)
                # The video, weights and outputs go; the job's log stays.
                for d in ("workspace", "bin"):
                    shutil.rmtree(self.jobs_dir / job_id / d, ignore_errors=True)
                print(f"[workstation] {job_id} removed", flush=True)
        for job in reply.get("start", []):
            job_id = job.get("id", "")
            if not ID_RE.match(job_id) or job_id in self.procs:
                continue
            if sum(p.poll() is None for p in self.procs.values()) >= self.slots:
                break
            self.procs[job_id] = self.spawn(job_id, job.get("env", {}), self.jobs_dir / job_id)
            print(f"[workstation] {job_id} started", flush=True)


def http_post(url: str, token: str) -> Callable[[dict], dict]:
    def post(report: dict) -> dict:
        req = urllib.request.Request(url, data=json.dumps(report).encode(), method="POST",
                                     # Cloudflare refuses Python's default User-Agent (HTTP 403, 2026-11-19).
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                              "User-Agent": "pic-vision-workstation-agent/1"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    return post


def main() -> int:
    url = os.environ["ORCHESTRATOR_URL"].rstrip("/") + "/workstation/poll"
    token = os.environ["WORKSTATION_TOKEN"]
    python = os.environ.get("WORKSTATION_PYTHON", sys.executable)
    jobs_dir = Path(os.environ.get("WORKSTATION_JOBS_DIR", "/mnt/fast_scratch/pic-vision-scratch/workstation-jobs"))
    slots = int(os.environ.get("WORKSTATION_SLOTS", "2"))
    label = os.environ.get("WORKSTATION_LABEL", "NVIDIA RTX 2000 Ada (workstation)")
    if not shutil.which("bwrap"):
        print("[workstation] bwrap is not installed", flush=True)
        return 1
    jobs_dir.mkdir(parents=True, exist_ok=True)
    agent = Agent(http_post(url, token), lambda i, e, d: spawn_job(i, e, d, python), kill_job, jobs_dir, slots, label)
    print(f"[workstation] checking in at {url} every {POLL_SEC} s, {slots} slots", flush=True)
    while True:
        agent.tick()
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    sys.exit(main())
