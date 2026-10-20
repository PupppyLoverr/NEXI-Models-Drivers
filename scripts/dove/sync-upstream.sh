#!/usr/bin/env bash
# Move the fork to a new upstream cua-driver release:
#
#   scripts/dove/sync-upstream.sh cua-driver-rs-v0.37.0
#
# 1. imports the release onto `upstream` (import-upstream.sh),
# 2. records a merge of `upstream` into `main` whose tree is the upstream tree
#    with the Dove changes applied (apply-dove-changes.sh) plus the Dove-only files,
# 3. checks parity (parity-check.sh).
# The merge commit is left uncommitted for review: build, test, then commit.
set -euo pipefail

tag="${1:?usage: sync-upstream.sh <cua-driver-rs-vX.Y.Z>}"
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
here="$(dirname "$0")"
source "$here/dove-only-files.sh"

if [ "$(git rev-parse --abbrev-ref HEAD)" != main ] || [ -n "$(git status --porcelain)" ]; then
  echo "run from a clean main checkout" >&2
  exit 1
fi

bash "$here/import-upstream.sh" "$tag"

git merge --quiet --no-ff --no-commit -s ours upstream
git rm -rq .
git checkout upstream -- .
bash "$here/apply-dove-changes.sh"
git checkout HEAD -- "${DOVE_ONLY_FILES[@]}"
# Let cargo drop lock entries for removed crates without upgrading anything else.
(cd rust && cargo metadata --format-version 1 --offline >/dev/null 2>&1 ||
            cargo metadata --format-version 1 >/dev/null)
git add -A

bash "$here/parity-check.sh"
echo "Merge of $tag staged. Build and test, update NOTICE.md, then: git commit"
