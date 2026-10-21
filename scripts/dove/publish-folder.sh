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
#    attached. The same commit places the fork's CI workflows at the
#    repository root, where GitHub runs them: every
#    ci/github-workflows/dove-driver-*.yml becomes
#    .github/workflows/dove-driver-*.yml, and a root dove-driver-*.yml the fork
#    no longer has is removed. Nothing else in the repository changes, and none
#    of it is downloaded here.
#
# Requires `gh` signed in with push access, and with the `workflow` scope when
# the root workflows change (GitHub refuses workflow edits without it). Run from a clean `main` that passes
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

# Root workflows: wanted (from the fork's ci/github-workflows/) against present
# (dove-driver-*.yml in the root .github/workflows/). Both as "name sha" lines.
wanted_workflows="$(git ls-tree main ci/github-workflows/ |
  awk '$2 == "blob" && $4 ~ /\/dove-driver-[^\/]*\.yml$/ { sub(".*/", "", $4); print $4, $3 }' | sort)"
subtree() {  # subtree <tree sha> <name>: sha of that child tree, or nothing
  gh api "repos/$repo/git/trees/$1" --jq ".tree[] | select(.path == \"$2\" and .type == \"tree\") | .sha"
}
present_workflows=""
github_tree="$(subtree "$base_tree" .github)"
workflows_tree=""
[ -n "$github_tree" ] && workflows_tree="$(subtree "$github_tree" workflows)"
[ -n "$workflows_tree" ] && present_workflows="$(gh api "repos/$repo/git/trees/$workflows_tree" \
    --jq '.tree[] | select(.type == "blob" and (.path | test("^dove-driver-.*[.]yml$"))) | "\(.path) \(.sha)"' |
  sort)"

if [ "$current" = "$fork_tree" ] && [ "$wanted_workflows" = "$present_workflows" ]; then
  echo "$repo main already has $folder/ at ${fork_commit:0:7} and its workflows"
  exit 0
fi
if [ "$wanted_workflows" != "$present_workflows" ] &&
   ! gh api -i user 2>/dev/null | grep -i '^x-oauth-scopes:' | grep -qw workflow; then
  echo "the root workflows change, but gh's token lacks the 'workflow' scope;" >&2
  echo "run: gh auth refresh -s workflow" >&2
  exit 1
fi

entries="$(printf '{"path":"%s","mode":"040000","type":"tree","sha":"%s"}' "$folder" "$fork_tree")"
while read -r name sha; do
  [ -n "$name" ] || continue
  entries="$entries,$(printf '{"path":".github/workflows/%s","mode":"100644","type":"blob","sha":"%s"}' "$name" "$sha")"
done <<< "$wanted_workflows"
while read -r name _; do
  [ -n "$name" ] || continue
  grep -q "^$name " <<< "$wanted_workflows" ||
    entries="$entries,$(printf '{"path":".github/workflows/%s","mode":"100644","type":"blob","sha":null}' "$name")"
done <<< "$present_workflows"

new_tree="$(printf '{"base_tree":"%s","tree":[%s]}' "$base_tree" "$entries" |
  gh api "repos/$repo/git/trees" --input - --jq .sha)"

verb="Add"
[ -n "$current" ] && verb="Update"
[ "$current" = "$fork_tree" ] && verb="Refresh workflows of"
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
