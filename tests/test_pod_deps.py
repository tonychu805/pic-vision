import hashlib
import os
import shutil
import tarfile

import pytest

from cloud_pipeline import pod_deps


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_the_real_repo_builds_with_every_listed_file(tmp_path):
    out = pod_deps.build(str(tmp_path / "deps.tar"))
    names = tarfile.open(out).getnames()
    assert names[0] == "pod_driver.py"  # extracted at /workspace root, where the pod's start command runs it
    assert names[1:] == pod_deps.POD_DEPS_FILES


def _copy_repo(tmp_path):
    """The listed files, copied, so a test can touch or delete them
    without touching the real repo (a live runner reads from it)."""
    root = tmp_path / "repo"
    for src, _ in pod_deps.members():
        dest = root / os.path.relpath(src, pod_deps.REPO_ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)
    return root


def test_the_same_code_always_builds_the_same_bytes(tmp_path):
    # What makes "which code did this job run" answerable from a hash: a
    # rebuild of the same commit (CI retry, or the runner's per-job build)
    # must not differ just because file mtimes or the builder's uid did.
    root = _copy_repo(tmp_path)
    a = pod_deps.build(str(tmp_path / "a.tar"), repo_root=str(root))
    for src, _ in pod_deps.members(str(root)):
        os.utime(src, (1_000_000_000, 1_000_000_000))  # new mtimes, same content
        os.chmod(src, os.stat(src).st_mode | 0o020)  # group-writable, as the workstation's umask checks out; CI's doesn't
    b = pod_deps.build(str(tmp_path / "b.tar"), repo_root=str(root))
    assert _sha(a) == _sha(b)
    for m in tarfile.open(a).getmembers():
        assert (m.mtime, m.uid, m.gid, m.uname, m.gname) == (0, 0, 0, "", "")
        assert m.mode in (0o644, 0o755)  # git's two file modes, nothing umask-dependent


def test_a_missing_dependency_fails_the_build_by_name(tmp_path):
    # Fails here, in CI or on the runner -- not as an ImportError on a
    # billing GPU twenty minutes later.
    fake_root = _copy_repo(tmp_path)
    os.remove(fake_root / "src" / "render.py")
    with pytest.raises(FileNotFoundError, match="src/render.py"):
        pod_deps.build(str(tmp_path / "x.tar"), repo_root=str(fake_root))


def test_ci_keys_are_per_commit_with_one_latest_pointer():
    assert pod_deps.ci_key("abc123") == "pipeline/pod_deps/abc123.tar"
    assert pod_deps.LATEST_KEY.startswith("pipeline/")


def test_pointer_key_main_is_production_staging_is_separate():
    assert pod_deps.pointer_key("refs/heads/main") == pod_deps.LATEST_KEY
    assert pod_deps.pointer_key("refs/heads/staging") == pod_deps.STAGING_KEY
    assert pod_deps.STAGING_KEY != pod_deps.LATEST_KEY


def test_pointer_key_refuses_any_other_ref():
    import pytest
    for ref in ("refs/heads/feature/x", "refs/tags/v1", "refs/heads/staging-old", ""):
        with pytest.raises(ValueError):
            pod_deps.pointer_key(ref)


def test_every_module_the_pod_imports_is_in_the_tarball():
    """pod_driver.py and the bundled files import each other, often lazily
    inside a function (so an ImportError only surfaces on a billing GPU, and
    best-effort steps swallow it). src/framing.py was missed on 2026-10-27:
    framing was silently skipped on every staging clip. Every `src.X` /
    `from src import X` / `scripts.X` named anywhere in the closure must be
    in POD_DEPS_FILES."""
    import re
    bundled = set(pod_deps.POD_DEPS_FILES)
    missing = set()
    for rel in [pod_deps.POD_DRIVER, *pod_deps.POD_DEPS_FILES]:
        text = open(os.path.join(pod_deps.REPO_ROOT, rel)).read()
        names = re.findall(r"^\s*(?:from|import)\s+((?:src|scripts)(?:\.\w+)+)", text, re.M)
        names += [f"src.{m}" for grp in re.findall(r"^\s*from\s+src\s+import\s+([\w, ]+)", text, re.M) for m in re.split(r"[,\s]+", grp) if m]
        for n in names:
            path = n.replace(".", "/") + ".py"
            if path not in bundled:
                missing.add(f"{rel}: {n}")
    assert not missing, sorted(missing)
