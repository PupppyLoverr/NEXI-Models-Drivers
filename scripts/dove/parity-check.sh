#!/usr/bin/env bash
# Check that `main` is the `upstream` branch plus exactly the Dove changes:
# rebuild the expected tree from `upstream` with apply-dove-changes.sh and
# compare it with this checkout's tracked files. Any other difference fails
# the check, so the fork cannot silently lose or alter upstream behaviour.
#
# Ignored: the Dove-only files (dove-only-files.sh) and rust/Cargo.lock,
# which cargo prunes after crates are removed.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/dove-only-files.sh"
work="$(mktemp -d)"
trap 'git -C "$repo_root" worktree remove --force "$work/expected" 2>/dev/null || true; rm -rf "$work"' EXIT

git -C "$repo_root" worktree add --quiet --detach "$work/expected" upstream
(cd "$work/expected" && bash "$here/apply-dove-changes.sh" >/dev/null && git add -A)
expected_tree="$(git -C "$work/expected" write-tree)"

pathspec=(. ':(top,exclude)rust/Cargo.lock')
for path in "${DOVE_ONLY_FILES[@]}"; do
  pathspec+=(":(top,exclude)$path")
done

cd "$repo_root"
base="$(git log -1 --format=%s upstream | sed -E 's/.* at ([^ ]+) .*/\1/')"
if git diff --quiet "$expected_tree" -- "${pathspec[@]}"; then
  echo "parity: main = upstream $base + Dove changes"
else
  echo "parity: main differs from upstream $base + Dove changes:" >&2
  git diff --stat "$expected_tree" -- "${pathspec[@]}" >&2
  exit 1
fi
