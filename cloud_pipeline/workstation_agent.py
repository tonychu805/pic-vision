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
  WORKSTATION_CACHE_DIR model files and ffmpeg kept between jobs

Model files and ffmpeg are kept between jobs (setup took 60 s per job on
staging, 2026-11-19): see pod_assets().
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ID_RE = re.compile(r"^ws-[0-9a-f]{12}$")
POLL_SEC = 10
KILL_GRACE_SEC = 20

USER_AGENT = "pic-vision-workstation-agent/1"

# Files pod_driver.py downloads only when they are missing, by the names of
# its own constants: <NAME>_R2_KEY is where it fetches from, <NAME>_LOCAL
# where it puts it. Cached by the KEY, so a new version (a new key) is never
# served from an older copy that lands under the same local name. Every one of
# these downloads is atomic (boto3 writes a temp name then renames; the
# weights use .part), so a file at its final path is complete however the job
# ended.
CACHED_ASSETS = ("WEIGHTS", "POSE", "FFMPEG", "FFPROBE")
# Where each sandbox path lives in the job's folder (sandbox_command's binds).
SANDBOX_DIRS = {"/workspace/": "workspace", "/usr/local/bin/": "bin"}


@dataclass(frozen=True)
class Asset:
    key: str
    path: Path


def pod_assets(pod_driver_src: str, job_dir: Path) -> list[Asset]:
    consts = dict(re.findall(r'^([A-Z0-9_]+) = "([^"]+)"', pod_driver_src, re.M))
    out = []
    for name in CACHED_ASSETS:
        key, local = consts.get(f"{name}_R2_KEY"), consts.get(f"{name}_LOCAL")
        if not key or not local:
            continue
        for prefix, sub in SANDBOX_DIRS.items():
            if local.startswith(prefix) and "/" not in local[len(prefix):]:
                out.append(Asset(key, Path(job_dir) / sub / local[len(prefix):]))
    return out


def _cached(cache: Path, key: str) -> Path:
    return Path(cache) / hashlib.sha256(key.encode()).hexdigest()[:32] / os.path.basename(key)


def seed(assets: list[Asset], cache: Path) -> int:
    """Copy each cached file into the job (a copy: a job never changes the cache). Returns how many."""
    n = 0
    for a in assets:
        src = _cached(cache, a.key)
        if not src.is_file():
            continue
        a.path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, a.path)
        if a.path.parent.name == "bin":
            os.chmod(a.path, 0o755)
        n += 1
    return n


def harvest(assets: list[Asset], cache: Path) -> None:
    """Keep each of the job's files the cache does not have yet."""
    for a in assets:
        dst = _cached(cache, a.key)
        if dst.exists() or not a.path.is_file():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".tmp")
        shutil.copyfile(a.path, tmp)
        os.replace(tmp, dst)


def unpack_job_code(tar_bytes: bytes, ws: Path) -> str:
    """The pod-code tarball into the workspace (nothing outside it), and pod_driver.py's text."""
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as t:
        for m in t.getmembers():
            if m.name.startswith("/") or ".." in Path(m.name).parts:
                continue
            t.extract(m, ws, filter="data")
    return (ws / "pod_driver.py").read_text()


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
        # BOOTSTRAP_CMD (orchestrator adapters.ts) without its download and
        # pip installs: spawn_job unpacked the job code (to seed the cache),
        # and WORKSTATION_PYTHON already has the packages.
        "bash", "-c", f"{python} -u pod_driver.py",
    ]
    # pod_driver.py starts the ball model as plain `python3`: WORKSTATION_PYTHON's
    # folder comes right after /usr/local/bin (pod_driver's own ffmpeg) so it is that one.
    venv_bin = os.path.dirname(python)
    job_env = {**env, "PATH": f"/usr/local/bin:{venv_bin}:/usr/bin:/bin", "HOME": "/workspace", "PYTHONUNBUFFERED": "1"}
    return argv, job_env


def spawn_job(job_id: str, env: dict, job_dir: Path, python: str, cache: Path):
    argv, job_env = sandbox_command(env, job_dir, python)
    log = open(job_dir / "job.log", "ab")
    req = urllib.request.Request(env["BOOTSTRAP_URL"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        src = unpack_job_code(r.read(), job_dir / "workspace")
    log.write(f"[workstation] {seed(pod_assets(src, job_dir), cache)} model/tool files from the cache\n".encode())
    log.flush()
    return subprocess.Popen(argv, env=job_env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def finish_job(job_dir: Path, cache: Path) -> None:
    """After a job is removed: keep its model files for the next job, then delete everything but its log."""
    driver = job_dir / "workspace" / "pod_driver.py"
    try:
        if driver.is_file():
            harvest(pod_assets(driver.read_text(), job_dir), cache)
    except OSError as err:
        print(f"[workstation] cache not updated from {job_dir.name}: {err}", flush=True)
    for d in ("workspace", "bin"):
        shutil.rmtree(job_dir / d, ignore_errors=True)


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
    def __init__(self, post: Callable[[dict], dict], spawn, kill, jobs_dir: Path, slots: int, label: str,
                 finish: Callable[[Path], None] | None = None):
        self.post, self.spawn, self.kill = post, spawn, kill
        self.finish = finish or (lambda job_dir: [shutil.rmtree(job_dir / d, ignore_errors=True) for d in ("workspace", "bin")])
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
                # The video and outputs go (model files to the cache first); the job's log stays.
                self.finish(self.jobs_dir / job_id)
                print(f"[workstation] {job_id} removed", flush=True)
        for job in reply.get("start", []):
            job_id = job.get("id", "")
            if not ID_RE.match(job_id) or job_id in self.procs:
                continue
            if sum(p.poll() is None for p in self.procs.values()) >= self.slots:
                break
            try:
                self.procs[job_id] = self.spawn(job_id, job.get("env", {}), self.jobs_dir / job_id)
            except Exception as err:  # noqa: BLE001 -- not started: the orchestrator retries it in the cloud
                print(f"[workstation] {job_id} could not start: {err}", flush=True)
                continue
            print(f"[workstation] {job_id} started", flush=True)


def http_post(url: str, token: str) -> Callable[[dict], dict]:
    def post(report: dict) -> dict:
        req = urllib.request.Request(url, data=json.dumps(report).encode(), method="POST",
                                     # Cloudflare refuses Python's default User-Agent (HTTP 403, 2026-11-19).
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                              "User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    return post


def main() -> int:
    url = os.environ["ORCHESTRATOR_URL"].rstrip("/") + "/workstation/poll"
    token = os.environ["WORKSTATION_TOKEN"]
    python = os.environ.get("WORKSTATION_PYTHON", sys.executable)
    jobs_dir = Path(os.environ.get("WORKSTATION_JOBS_DIR", "/mnt/fast_scratch/pic-vision-scratch/workstation-jobs"))
    cache = Path(os.environ.get("WORKSTATION_CACHE_DIR", "/mnt/fast_scratch/pic-vision-scratch/workstation-cache"))
    slots = int(os.environ.get("WORKSTATION_SLOTS", "2"))
    label = os.environ.get("WORKSTATION_LABEL", "NVIDIA RTX 2000 Ada (workstation)")
    if not shutil.which("bwrap"):
        print("[workstation] bwrap is not installed", flush=True)
        return 1
    jobs_dir.mkdir(parents=True, exist_ok=True)
    agent = Agent(http_post(url, token), lambda i, e, d: spawn_job(i, e, d, python, cache), kill_job, jobs_dir, slots, label,
                  finish=lambda d: finish_job(d, cache))
    print(f"[workstation] checking in at {url} every {POLL_SEC} s, {slots} slots", flush=True)
    while True:
        agent.tick()
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    sys.exit(main())
