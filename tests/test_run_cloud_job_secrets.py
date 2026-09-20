# PIC-139: the R2 credentials must not travel in a command string.
#
# They used to. `pod_r2()` built `KEY=... SECRET=... python3 pod_r2_helper.py
# ...` and handed it to ssh_run(), which puts it in two process tables at
# once: the pod's, where sshd runs the string through `sh -c`, and this
# workstation's, where it is an argv element of the local `ssh` process.
# `ps` on either end showed the secret for the duration of every transfer,
# and a job does six of them.
#
# Paired on purpose (CLAUDE.md, "remove the secret, then prove it still
# works"): the tests that the secret is gone from the command sit next to
# tests that the credentials still reach the pod in the file, with the
# right names, quoted. Asserting only the removal would pass with the
# credentials dropped entirely, which is a broken pipeline that looks
# secure.
import pytest

pytest.importorskip("dotenv")  # cloud_pipeline's own dependency

from cloud_pipeline.run_cloud_job import (  # noqa: E402
    POD_R2_ENV,
    R2_ENV_VARS,
    pod_r2_command,
    r2_env_file_contents,
)

SECRET = "s3cr3t-key-material"
ENV = {
    "CLOUDFLARE_R2_ACCESS_KEY_ID": "access-key-id",
    "CLOUDFLARE_R2_SECRET_ACCESS_KEY": SECRET,
    "CLOUDFLARE_R2_ACCOUNT_ID": "account-id",
}


def test_the_transfer_command_carries_no_credentials():
    cmd = pod_r2_command("download", "some-bucket", "some/key.mp4", "/workspace/v.mp4")
    for name in R2_ENV_VARS:
        assert ENV[name] not in cmd, f"{name}'s value is in the command string"
        assert name not in cmd, f"{name} is still being set inline"


def test_the_transfer_command_still_does_the_transfer():
    # The other half: a command with no credentials in it is only correct
    # if it still sources them and still runs the helper with the right
    # arguments.
    cmd = pod_r2_command("download", "some-bucket", "some/key.mp4", "/workspace/v.mp4")
    assert f". {POD_R2_ENV}" in cmd
    assert "python3 pod_r2_helper.py download some-bucket some/key.mp4 /workspace/v.mp4" in cmd
    # Sourced before the helper runs, not after.
    assert cmd.index(POD_R2_ENV) < cmd.index("pod_r2_helper.py")


@pytest.mark.parametrize("action", ["download", "upload"])
def test_both_directions_are_covered(action):
    # A job uploads the finished reel with the same helper it downloaded
    # the footage with; fixing only one direction would leave the secret in
    # the process table for every upload.
    cmd = pod_r2_command(action, "b", "k", "/p")
    assert SECRET not in cmd
    assert f"pod_r2_helper.py {action} " in cmd


def test_the_credentials_do_reach_the_pod():
    contents = r2_env_file_contents(ENV)
    for name in R2_ENV_VARS:
        assert f"export {name}=" in contents, f"{name} never reaches the pod"
    assert SECRET in contents, "the secret has to be in the file -- that is the point of it"


def test_a_value_with_shell_metacharacters_is_quoted():
    # An unquoted value in a `.`-sourced file is executable text. A secret
    # containing `$(...)`, a space or a quote would either break the job or
    # run something; shlex.quote is what stops both.
    hostile = "ab$(touch /tmp/pwned) 'c'"
    contents = r2_env_file_contents({**ENV, "CLOUDFLARE_R2_SECRET_ACCESS_KEY": hostile})
    line = next(l for l in contents.splitlines() if l.startswith("export CLOUDFLARE_R2_SECRET_ACCESS_KEY="))
    value = line.split("=", 1)[1]
    assert not value.startswith(hostile[:2]), "the value is being written raw"
    # Round-trips through a real shell parse back to exactly what went in.
    import shlex
    assert shlex.split(value) == [hostile]


def test_every_line_is_a_plain_export():
    # Nothing in this file should be executable beyond setting variables --
    # it is sourced by the pod's shell as root.
    contents = r2_env_file_contents(ENV)
    lines = contents.splitlines()
    assert len(lines) == len(R2_ENV_VARS)
    for line in lines:
        assert line.startswith("export CLOUDFLARE_R2_")
