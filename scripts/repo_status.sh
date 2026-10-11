#!/usr/bin/env bash
# Where does this repo actually stand? Fetches first, then reports -- read-only
# apart from the fetch, so it is safe to run anytime.
#
# Why this exists: PRs are merged on GitHub, which moves origin/main but not the
# local main. Judging "is it merged / is it behind" from a stale local main gave a
# wrong answer once (2026-10-11: five branches called unmerged that were merged).
# Run this (make repo-status) before reporting any branch or merge state.
#
# Branches are compared against origin/main, not the local main. A branch that
# was SQUASH-merged on GitHub will show as "not merged" here (its commits are
# new on main); check those on GitHub.
set -u
cd "$(git rev-parse --show-toplevel)" || exit 1

echo "== fetch =="
if ! git fetch --prune origin 2>&1; then
  echo "WARNING: fetch failed -- everything below is based on stale remote info" >&2
fi

base=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/main)
echo
echo "== base: $base =="
read -r lbehind lahead < <(git rev-list --left-right --count "$base"...main 2>/dev/null || echo "? ?")
echo "local main is behind $base by $lbehind, ahead by $lahead"
[ "$lbehind" != "0" ] && [ "$lbehind" != "?" ] && echo "  -> git checkout main && git pull --ff-only origin main"

echo
echo "== current branch =="
git branch --show-current
echo "-- working tree (untracked/modified):"
git status --short | sed 's/^/   /'
[ -z "$(git status --short)" ] && echo "   clean"
echo "-- stashes: $(git stash list | wc -l | tr -d ' ')"

echo
echo "== local branches vs $base =="
printf '%-48s %-12s %-14s %s\n' BRANCH "VS BASE" "MERGED?" "UNPUSHED"
for b in $(git for-each-ref --format='%(refname:short)' refs/heads); do
  [ "$b" = "main" ] && continue
  read -r behind ahead < <(git rev-list --left-right --count "$base"..."$b")
  if git merge-base --is-ancestor "$b" "$base"; then merged="merged"; else merged="NOT merged"; fi
  up=$(git rev-parse --abbrev-ref "$b@{upstream}" 2>/dev/null || true)
  if [ -z "$up" ]; then
    unpushed="no upstream"
  else
    n=$(git rev-list --count "$up..$b" 2>/dev/null || echo "?")
    gone=$(git for-each-ref --format='%(upstream:track)' "refs/heads/$b")
    if [ "$gone" = "[gone]" ]; then unpushed="remote deleted"
    elif [ "$n" = "0" ]; then unpushed="pushed"
    else unpushed="$n UNPUSHED"; fi
  fi
  printf '%-48s %-12s %-14s %s\n' "$b" "+$ahead/-$behind" "$merged" "$unpushed"
done

echo
echo "== worktrees =="
git worktree list | while read -r path sha rest; do
  dirty=$(git -C "$path" status --short 2>/dev/null | wc -l | tr -d ' ')
  printf '%s  %s  %s uncommitted\n' "$path" "$rest" "$dirty"
done

echo
echo "== remote branches already merged into $base (safe to delete on GitHub) =="
git for-each-ref --format='%(refname:short)' refs/remotes/origin |
  grep -v -E "^origin(/HEAD)?$|$base\$" |
  while read -r r; do git merge-base --is-ancestor "$r" "$base" && echo "   $r"; done
true
