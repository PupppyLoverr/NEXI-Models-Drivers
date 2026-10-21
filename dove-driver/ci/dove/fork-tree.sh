#!/usr/bin/env bash
# Give CI a checkout shaped like the fork, from a NEXI-Models-Drivers checkout
# that carries it as the dove-driver/ folder.
#
#   ci/dove/fork-tree.sh <dest> [<folder>]
#
# scripts/dove/parity-check.sh needs the fork at a repository root and an
# `upstream` branch. In NEXI-Models-Drivers the fork is a folder of HEAD and
# upstream is the dove-driver/upstream branch, so this makes a commit whose
# root tree is HEAD:<folder> (default dove-driver), checks it out at <dest>
# as a detached worktree, and points a local `upstream` branch at
# origin/dove-driver/upstream (fetched if missing). Nothing is pushed.
set -euo pipefail
dest="${1:?usage: fork-tree.sh <dest> [<folder>]}"
folder="${2:-dove-driver}"
repo="$(git rev-parse --show-toplevel)"
cd "$repo"

tree="$(git rev-parse "HEAD:$folder")"
git rev-parse -q --verify origin/dove-driver/upstream >/dev/null ||
  git fetch --no-tags --depth=1 origin \
    "+refs/heads/dove-driver/upstream:refs/remotes/origin/dove-driver/upstream"
git branch -f upstream origin/dove-driver/upstream

commit="$(git -c user.name=dove-ci -c user.email=dove-ci@invalid \
  commit-tree "$tree" -m "CI: $folder/ of $(git rev-parse --short HEAD)")"
git worktree add --detach "$dest" "$commit" >/dev/null
echo "fork tree $tree checked out at $dest (upstream = $(git rev-parse --short upstream))"
