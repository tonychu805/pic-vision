"""The workstation agent (pilot phase, 2026-11-19): checks in with the
orchestrator, runs each handed-out job in its own sandbox, reports and kills."""

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
    a.post = lambda r: (sent.append(r), {"start": [], "kill": ["ws-0123456789ab"]})[1]
    a.tick()
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
    assert "/opt/venv/bin/python -u pod_driver.py" in argv[-1]
    assert '"$BOOTSTRAP_URL"' in argv[-1]
    assert env["RUNPOD_POD_ID"] == "ws-0123456789ab" and env["R2_READ_SESSION_TOKEN"] == "s"
    assert env["PATH"].split(":")[:2] == ["/usr/local/bin", "/opt/venv/bin"], "pod_driver's bare `python3` is the configured one"
    assert f"--ro-bind {job_dir / 'gai.conf'} /etc/gai.conf" in joined
    assert "::ffff:0:0/96" in (job_dir / "gai.conf").read_text(), "IPv4 first: this host's IPv6 route hangs"
    assert "RUNNER_TOKEN" not in env and "WORKSTATION_TOKEN" not in env, "the agent's own secrets never reach a job"
