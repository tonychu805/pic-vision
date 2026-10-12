#!/usr/bin/env bash
# After a PR merges on GitHub: fast-forward local main to origin/main and
# delete local branches that are provably merged. Counterpart to
# repo_status.sh (which only reports).
#
# Deliberately conservative:
#   - refuses to run with uncommitted changes to tracked files (untracked
#     files never block a fast-forward and are left alone)
#   - fast-forward only: never creates a merge commit on main
#   - deletes only with `git branch -d`, and only branches that are an
#     ancestor of origin/main. A SQUASH-merged branch is not provably merged
#     from git alone, so it is kept and listed for you to check on GitHub.
#   - never touches remote branches, stashes, or worktrees
set -u
cd "$(git rev-parse --show-toplevel)" || exit 1

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "REFUSING: tracked files have uncommitted changes. Commit or stash them first:" >&2
  git status --short --untracked-files=no >&2
  exit 1
fi

git fetch --prune origin || { echo "REFUSING: fetch failed" >&2; exit 1; }

start=$(git branch --show-current)
if [ "$start" != "main" ]; then
  git checkout -q main || exit 1
  echo "switched $start -> main"
fi

if ! git merge --ff-only -q origin/main; then
  echo "REFUSING: local main cannot fast-forward to origin/main (it has commits of its own)." >&2
  echo "Nothing was changed beyond the fetch. Inspect with: make repo-status" >&2
  exit 1
fi
echo "main is at $(git log --oneline -1)"

kept=()
for b in $(git for-each-ref --format='%(refname:short)' refs/heads); do
  [ "$b" = "main" ] && continue
  if git merge-base --is-ancestor "$b" origin/main; then
    git branch -d "$b" >/dev/null && echo "deleted merged branch $b"
  else
    kept+=("$b")
  fi
done

if [ "${#kept[@]}" -gt 0 ]; then
  echo "kept (not merged into origin/main as far as git can tell -- squash-merged? check GitHub):"
  printf '   %s\n' "${kept[@]}"
fi
