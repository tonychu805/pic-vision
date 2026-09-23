"""The code a self-driving pod runs, packaged as one tarball (ADR-093, ADR-125).

One definition, two builders:
  - job_runner.py builds it per job from the working tree (today's path);
  - .github/workflows/pod-deps.yml builds it on every push to main and
    stores it in R2 under the commit SHA, so the cloud orchestrator
    (ADR-125) hands pods committed code rather than whatever happens to be
    on the operator's disk.

The build is deterministic -- fixed member order, zeroed mtimes and
ownership -- so the same commit always produces byte-identical bytes, and
"which code did this job run" can be answered by comparing hashes.

    python -m cloud_pipeline.pod_deps build OUT.tar
"""
import os
import sys
import tarfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# pod_driver.py's own dependency closure -- an explicit list, not a glob,
# so a new unrelated src/ module doesn't silently ride along (and so a
# missing one fails the build here instead of as an ImportError on a
# billing GPU). pod_driver.py itself goes in at the tarball root.
POD_DEPS_FILES = [
    "src/__init__.py", "src/job_log.py", "src/calib.py", "src/ball.py",
    "src/track.py", "src/select.py", "src/tracknet.py", "src/render.py",
    "src/drift.py", "src/video_quality.py",
    "scripts/check_drift.py", "scripts/rank_and_reel.py",
    "scripts/burst_moment_reel.py", "scripts/top_rallies_reel.py",
    "scripts/pod_infer.py",
]
POD_DRIVER = "cloud_pipeline/pod_driver.py"

# R2 layout for CI-built tarballs, in their own bucket (pic-vision-pod-code;
# see pod-deps.yml for why not the ingest bucket). The pod reads the
# tarball through a presigned link, so no pod credential needs this bucket.
CI_PREFIX = "pipeline/pod_deps"
LATEST_KEY = f"{CI_PREFIX}/latest.json"


def ci_key(sha):
    return f"{CI_PREFIX}/{sha}.tar"


def members(repo_root=REPO_ROOT):
    """(source path, name inside the tarball), in tarball order."""
    return [(os.path.join(repo_root, POD_DRIVER), "pod_driver.py")] + \
           [(os.path.join(repo_root, rel), rel) for rel in POD_DEPS_FILES]


def _normalize(info):
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def build(out_path, repo_root=REPO_ROOT):
    """Write the tarball to out_path. Raises FileNotFoundError naming the
    first listed file that doesn't exist."""
    for src, _ in members(repo_root):
        if not os.path.isfile(src):
            raise FileNotFoundError(f"pod dependency missing: {os.path.relpath(src, repo_root)}")
    with tarfile.open(out_path, "w", format=tarfile.PAX_FORMAT) as tar:
        for src, arcname in members(repo_root):
            tar.add(src, arcname=arcname, filter=_normalize)
    return out_path


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "build":
        sys.exit("usage: python -m cloud_pipeline.pod_deps build OUT.tar")
    print(build(sys.argv[2]))
