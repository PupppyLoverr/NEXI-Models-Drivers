#!/usr/bin/env bash
# Publish this fork as the dove-driver/ folder of PupppyLoverr/NEXI-Models-Drivers.
#
#   scripts/dove/publish-folder.sh
#
# 1. Pushes `main` to dove-driver/main and `upstream` to dove-driver/upstream in
#    that repository (fast-forward only).
# 2. Through the GitHub API, adds a merge commit to its `main` whose tree is that
#    branch's tree with dove-driver/ set to this fork's `main` tree, and whose
#    parents are its `main` and this fork's `main`, so the fork's history stays
#    attached. Nothing else in the repository changes, and none of it is
#    downloaded here.
#
# Requires `gh` signed in with push access. Run from a clean `main` that passes
# scripts/dove/parity-check.sh.
set -euo pipefail

repo="${DOVE_NEXI_REPO:-PupppyLoverr/NEXI-Models-Drivers}"
folder="dove-driver"
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if [ "$(git rev-parse --abbrev-ref HEAD)" != main ] || [ -n "$(git status --porcelain)" ]; then
  echo "run from a clean main checkout" >&2
  exit 1
fi
bash scripts/dove/parity-check.sh

# Use gh's token for this push only, so no credential prompt can appear.
git -c credential.helper= -c 'credential.helper=!gh auth git-credential' \
  push "https://github.com/$repo.git" \
  "main:refs/heads/$folder/main" "upstream:refs/heads/$folder/upstream"

fork_commit="$(git rev-parse main)"
fork_tree="$(git rev-parse 'main^{tree}')"
base_commit="$(gh api "repos/$repo/git/ref/heads/main" --jq .object.sha)"
base_tree="$(gh api "repos/$repo/git/commits/$base_commit" --jq .tree.sha)"
current="$(gh api "repos/$repo/git/trees/$base_tree" --jq ".tree[] | select(.path == \"$folder\") | .sha")"
if [ "$current" = "$fork_tree" ]; then
  echo "$repo main already has $folder/ at ${fork_commit:0:7}"
  exit 0
fi

new_tree="$(printf '{"base_tree":"%s","tree":[{"path":"%s","mode":"040000","type":"tree","sha":"%s"}]}' \
    "$base_tree" "$folder" "$fork_tree" |
  gh api "repos/$repo/git/trees" --input - --jq .sha)"

verb="Add"
[ -n "$current" ] && verb="Update"
message="$verb $folder/ (dove-driver $(cat rust/VERSION), fork ${fork_commit:0:7})

dove-driver is Dove's computer-use driver: a fork of trycua/cua
libs/cua-driver (MIT). Its development branches are $folder/main and
$folder/upstream; this folder is refreshed from $folder/main by
scripts/dove/publish-folder.sh."
# Optional trailer lines, e.g. a Co-Authored-By line.
[ -n "${DOVE_COMMIT_TRAILER:-}" ] && message="$message

$DOVE_COMMIT_TRAILER"
new_commit="$(python -I -c 'import json,sys; print(json.dumps({"message": sys.argv[1], "tree": sys.argv[2], "parents": sys.argv[3:]}))' \
    "$message" "$new_tree" "$base_commit" "$fork_commit" |
  gh api "repos/$repo/git/commits" --input - --jq .sha)"

# Fast-forward only: fails, changing nothing, if main moved since base_commit.
printf '{"sha":"%s","force":false}' "$new_commit" |
  gh api -X PATCH "repos/$repo/git/refs/heads/main" --input - --jq .object.sha
echo "$repo main: $verb $folder/ at ${new_commit:0:7}"
