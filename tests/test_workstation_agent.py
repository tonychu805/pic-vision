"""The workstation agent (pilot phase, 2026-11-19): checks in with the
orchestrator, runs each handed-out job in its own sandbox, reports and kills."""

import os

from cloud_pipeline import workstation_agent as wa

ENV = {"BOOTSTRAP_URL": "https://r2.example/deps.tar?sig", "RUNPOD_POD_ID": "ws-0123456789ab", "R2_READ_SESSION_TOKEN": "s"}


class FakeProc:
    def __init__(self):
        self.code = None
        self.signals = []

    def poll(self):
        return self.code


def agent(tmp_path, replies):
    """An agent whose check-ins return `replies` in turn and whose jobs are FakeProcs."""
    sent, spawned, killed = [], [], []

    def post(report):
        sent.append(report)
        return replies.pop(0) if replies else {"start": [], "kill": []}

    def spawn(job_id, env, job_dir):
        spawned.append((job_id, env, job_dir))
        return FakeProc()

    a = wa.Agent(post=post, spawn=spawn, kill=lambda p: killed.append(p), jobs_dir=tmp_path, slots=2, label="RTX 2000 Ada")
    return a, sent, spawned, killed


def test_a_handed_out_job_starts_once_and_is_reported_running(tmp_path):
    a, sent, spawned, _ = agent(tmp_path, [{"start": [{"id": "ws-0123456789ab", "env": ENV}], "kill": []},
                                           {"start": [{"id": "ws-0123456789ab", "env": ENV}], "kill": []}])
    a.tick()
    a.tick()
    assert [s[0] for s in spawned] == ["ws-0123456789ab"], "a repeated start (reply lost, retried) never runs a job twice"
    assert sent[1]["procs"] == [{"id": "ws-0123456789ab", "running": True}]
    assert sent[0] == {"slots": 2, "label": "RTX 2000 Ada", "procs": []}


def test_a_finished_job_reads_as_not_running_until_the_orchestrator_removes_it(tmp_path):
    a, sent, _, killed = agent(tmp_path, [{"start": [{"id": "ws-0123456789ab", "env": ENV}], "kill": []}])
    a.tick()
    a.procs["ws-0123456789ab"].code = 0
    a.tick()
    assert sent[1]["procs"] == [{"id": "ws-0123456789ab", "running": False}]
    job_dir = tmp_path / "ws-0123456789ab"
    (job_dir / "workspace").mkdir(parents=True)
    (job_dir / "workspace" / "video.mp4").write_text("x")
    (job_dir / "job.log").write_text("log")
    a.post = lambda r: (sent.append(r), {"start": [], "kill": ["ws-0123456789ab"]})[1]
    a.tick()
    assert not (job_dir / "workspace").exists(), "a removed job's files are deleted"
    assert (job_dir / "job.log").exists(), "its log is kept"
    assert "ws-0123456789ab" not in a.procs
    assert len(killed) == 1
    a.tick()
    assert sent[-1]["procs"] == []


def test_ids_not_shaped_like_ours_are_never_started(tmp_path):
    a, _, spawned, _ = agent(tmp_path, [{"start": [{"id": "../../etc", "env": ENV}, {"id": "ws-0123456789ab", "env": ENV}], "kill": []}])
    a.tick()
    assert [s[0] for s in spawned] == ["ws-0123456789ab"]


def test_never_more_jobs_than_slots(tmp_path):
    ids = ["ws-00000000000a", "ws-00000000000b", "ws-00000000000c"]
    a, _, spawned, _ = agent(tmp_path, [{"start": [{"id": i, "env": ENV} for i in ids], "kill": []}])
    a.tick()
    assert [s[0] for s in spawned] == ids[:2]


def test_a_failed_check_in_changes_nothing(tmp_path):
    def down(_report):
        raise OSError("network down")
    a, _, spawned, killed = agent(tmp_path, [])
    a.post = down
    a.tick()
    assert spawned == [] and killed == []


# Paired: the sandbox gives the job its own /workspace and /usr/local/bin and
# the GPU -- and the job still gets what it needs to run.
def test_the_sandbox_isolates_writes_but_keeps_gpu_network_and_the_job_env(tmp_path):
    job_dir = tmp_path / "ws-0123456789ab"
    argv, env = wa.sandbox_command(ENV, job_dir, python="/opt/venv/bin/python")
    joined = " ".join(argv)
    assert argv[0] == "bwrap"
    assert f"--bind {job_dir / 'workspace'} /workspace" in joined
    assert f"--bind {job_dir / 'bin'} /usr/local/bin" in joined
    assert "--ro-bind /home /home" in joined, "the operator's home (and its keys) is read-only"
    assert "--dev-bind /dev /dev" in joined, "the GPU device files"
    assert "--die-with-parent" in argv
    assert argv[-1] == "/opt/venv/bin/python -u pod_driver.py", "the agent fetched and unpacked the job code already"
    assert env["RUNPOD_POD_ID"] == "ws-0123456789ab" and env["R2_READ_SESSION_TOKEN"] == "s"
    assert env["PATH"].split(":")[:2] == ["/usr/local/bin", "/opt/venv/bin"], "pod_driver's bare `python3` is the configured one"
    assert f"--ro-bind {job_dir / 'gai.conf'} /etc/gai.conf" in joined
    assert "::ffff:0:0/96" in (job_dir / "gai.conf").read_text(), "IPv4 first: this host's IPv6 route hangs"
    assert "RUNNER_TOKEN" not in env and "WORKSTATION_TOKEN" not in env, "the agent's own secrets never reach a job"


# --- Model and binary cache across jobs (2026-11-19: setup took 60 s per job) ---

POD_DRIVER_SRC = '''
WEIGHTS_R2_KEY = "weights/tracknet_k14_epoch19.pt"
WEIGHTS_LOCAL = "/workspace/tracknet_k14_epoch19.pt"
POSE_R2_KEY = "weights/staging-yolov8n-pose-736x1280-torch21-20261030.torchscript"
POSE_LOCAL = "/workspace/yolov8n-pose-736x1280.torchscript"
FFMPEG_R2_KEY = "pipeline/ffmpeg-btbn-nvenc-linux-x64-n8.1.2-gc573a95381"
FFMPEG_LOCAL = "/usr/local/bin/ffmpeg"
FFPROBE_R2_KEY = "pipeline/ffprobe-btbn-nvenc-linux-x64-n8.1.2-gc573a95381"
FFPROBE_LOCAL = "/usr/local/bin/ffprobe"
'''


def test_the_job_code_names_each_cached_file_by_its_storage_key(tmp_path):
    assets = wa.pod_assets(POD_DRIVER_SRC, tmp_path / "job")
    assert [(a.key, a.path.relative_to(tmp_path / "job").as_posix()) for a in assets] == [
        ("weights/tracknet_k14_epoch19.pt", "workspace/tracknet_k14_epoch19.pt"),
        ("weights/staging-yolov8n-pose-736x1280-torch21-20261030.torchscript", "workspace/yolov8n-pose-736x1280.torchscript"),
        ("pipeline/ffmpeg-btbn-nvenc-linux-x64-n8.1.2-gc573a95381", "bin/ffmpeg"),
        ("pipeline/ffprobe-btbn-nvenc-linux-x64-n8.1.2-gc573a95381", "bin/ffprobe"),
    ]


def test_a_cleanly_finished_job_fills_the_cache_and_the_next_job_starts_with_its_files(tmp_path):
    cache = tmp_path / "cache"
    first = tmp_path / "job1"
    assets = wa.pod_assets(POD_DRIVER_SRC, first)
    for a in assets:
        a.path.parent.mkdir(parents=True, exist_ok=True)
        a.path.write_bytes(b"model-bytes-" + a.key.encode())
    wa.harvest(assets, cache)

    second = tmp_path / "job2"
    seeded = wa.seed(wa.pod_assets(POD_DRIVER_SRC, second), cache)
    assert seeded == 4
    assert (second / "workspace" / "tracknet_k14_epoch19.pt").read_bytes() == b"model-bytes-weights/tracknet_k14_epoch19.pt"
    (second / "bin" / "ffmpeg").write_bytes(b"changed by the job")
    assert wa.seed(wa.pod_assets(POD_DRIVER_SRC, tmp_path / "job3"), cache) == 4
    assert (tmp_path / "job3" / "bin" / "ffmpeg").read_bytes().startswith(b"model-bytes-"), "a job's own copy never changes the cache"


# Paired with the test above: the cache never hands out a file it cannot vouch for.
# Every download pod_driver.py makes is atomic (boto3 writes a temp name then
# renames; the weights use .part), so a file at its final path is complete
# however the job ended -- a job the cleanup stopped still fills the cache.
def test_a_new_model_version_is_never_served_from_an_older_copy(tmp_path):
    cache = tmp_path / "cache"
    assets = wa.pod_assets(POD_DRIVER_SRC, tmp_path / "job1")
    for a in assets:
        a.path.parent.mkdir(parents=True, exist_ok=True)
        a.path.write_bytes(b"x")
    (assets[0].path.parent / (assets[0].path.name + ".part")).write_bytes(b"half")
    wa.harvest(assets, cache)
    assert not any(p.name.endswith(".part") for p in cache.rglob("*")), "only files at their final path"

    newer = POD_DRIVER_SRC.replace("tracknet_k14_epoch19.pt\"\nWEIGHTS_LOCAL", "tracknet_k14_epoch20.pt\"\nWEIGHTS_LOCAL")
    job2 = tmp_path / "job2"
    assert wa.seed(wa.pod_assets(newer, job2), cache) == 3, "the renamed weights key is not served from the old copy"
    assert not (job2 / "workspace" / "tracknet_k14_epoch19.pt").exists()
    assert os.access(job2 / "bin" / "ffmpeg", os.X_OK), "cached binaries stay executable"


def test_job_code_is_unpacked_safely_into_the_workspace(tmp_path):
    import io, tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, data in (("pod_driver.py", POD_DRIVER_SRC.encode()), ("../escape.txt", b"no")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    ws = tmp_path / "job" / "workspace"
    ws.mkdir(parents=True)
    src = wa.unpack_job_code(buf.getvalue(), ws)
    assert "WEIGHTS_R2_KEY" in src
    assert (ws / "pod_driver.py").exists()
    assert not (tmp_path / "job" / "escape.txt").exists(), "a path outside the workspace is refused"
