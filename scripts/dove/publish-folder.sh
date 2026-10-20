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
#    attached. The same commit places each ci/github-workflows/dove-driver-*.yml
#    of the fork at that branch's root as .github/workflows/dove-driver-*.yml
#    (GitHub runs workflows only from there) and removes root
#    dove-driver-*.yml workflows the fork no longer has. Nothing else in the
#    repository changes, and none of it is downloaded here.
#
# Requires `gh` signed in with push access, plus the `workflow` scope when root
# workflows change (`gh auth refresh -s workflow`). Run from a clean `main` that
# passes scripts/dove/parity-check.sh.
set -euo pipefail

repo="${DOVE_NEXI_REPO:-PupppyLoverr/NEXI-Models-Drivers}"
folder="dove-driver"
workflows_src="ci/github-workflows"
workflows_dst=".github/workflows"
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if [ "$(git rev-parse --abbrev-ref HEAD)" != main ] || [ -n "$(git status --porcelain)" ]; then
  echo "run from a clean main checkout" >&2
  exit 1
fi
bash scripts/dove/parity-check.sh

# Root workflows the fork wants: "<name> <blob>" per ci/github-workflows file.
wanted=""
while IFS=$'\t' read -r meta path; do
  read -r mode type blob <<< "$meta"
  name="${path#"$workflows_src"/}"
  case "$mode $type $name" in
    "100644 blob dove-driver-"*.yml) wanted="$wanted$name $blob"$'\n' ;;
    *) echo "$path: only regular dove-driver-*.yml files belong in $workflows_src" >&2; exit 1 ;;
  esac
done < <(git ls-tree main -- "$workflows_src/")

fork_commit="$(git rev-parse main)"
fork_tree="$(git rev-parse 'main^{tree}')"
base_commit="$(gh api "repos/$repo/git/ref/heads/main" --jq .object.sha)"
base_tree="$(gh api "repos/$repo/git/commits/$base_commit" --jq .tree.sha)"
subtree() {  # subtree <tree sha> <entry name>: sha of that subtree, or nothing
  [ -n "$1" ] || return 0
  gh api "repos/$repo/git/trees/$1" --jq ".tree[] | select(.path == \"$2\" and .type == \"tree\") | .sha"
}
current="$(subtree "$base_tree" "$folder")"
root_github="$(subtree "$base_tree" .github)"
root_workflows="$(subtree "$root_github" workflows)"
present=""
[ -n "$root_workflows" ] && present="$(gh api "repos/$repo/git/trees/$root_workflows" \
  --jq '.tree[] | select(.type == "blob" and (.path | startswith("dove-driver-"))) | "\(.path) \(.sha)"')"

# Tree entries for the merge commit: dove-driver/ if it changed, then each root
# workflow to add or update (blob from the fork) or remove (sha null).
entries="$(python -I -c '
import json, sys
folder, fork_tree, current, dst, wanted, present = sys.argv[1:]
pairs = lambda text: dict(line.split(" ", 1) for line in text.splitlines() if line)
wanted, present = pairs(wanted), pairs(present)
entries = []
if current != fork_tree:
    entries.append({"path": folder, "mode": "040000", "type": "tree", "sha": fork_tree})
for name in sorted(wanted.keys() | present.keys()):
    if wanted.get(name) != present.get(name):
        entries.append({"path": f"{dst}/{name}", "mode": "100644", "type": "blob", "sha": wanted.get(name)})
print(json.dumps(entries))
' "$folder" "$fork_tree" "$current" "$workflows_dst" "$wanted" "$present")"
workflow_changes="$(python -I -c 'import json,sys; print(sum(e["type"] == "blob" for e in json.loads(sys.argv[1])))' "$entries")"

if [ "$workflow_changes" -gt 0 ]; then
  # Classic tokens list their scopes; GitHub refuses workflow changes without
  # `workflow`. (Fine-grained tokens list none; the ref update below then
  # fails, changing nothing, if the token lacks Workflows write access.)
  scopes="$(gh api -i user | tr -d '\r' | sed -n 's/^[Xx]-[Oo][Aa]uth-[Ss]copes: //p')"
  if [ -n "$scopes" ] && ! printf '%s' "$scopes" | tr ', ' '\n\n' | grep -qx workflow; then
    echo "$workflow_changes root workflow change(s) need the gh token's workflow scope: gh auth refresh -s workflow" >&2
    exit 1
  fi
fi

# Use gh's token for this push only, so no credential prompt can appear.
git -c credential.helper= -c 'credential.helper=!gh auth git-credential' \
  push "https://github.com/$repo.git" \
  "main:refs/heads/$folder/main" "upstream:refs/heads/$folder/upstream"

if [ "$entries" = "[]" ]; then
  echo "$repo main already has $folder/ and its root workflows at ${fork_commit:0:7}"
  exit 0
fi

new_tree="$(python -I -c 'import json,sys; print(json.dumps({"base_tree": sys.argv[1], "tree": json.loads(sys.argv[2])}))' \
    "$base_tree" "$entries" |
  gh api "repos/$repo/git/trees" --input - --jq .sha)"

verb="Add"
[ -n "$current" ] && verb="Update"
message="$verb $folder/ (dove-driver $(cat rust/VERSION), fork ${fork_commit:0:7})

dove-driver is Dove's computer-use driver: a fork of trycua/cua
libs/cua-driver (MIT). Its development branches are $folder/main and
$folder/upstream. This folder is refreshed from $folder/main by
scripts/dove/publish-folder.sh, which also copies the fork's
$workflows_src/dove-driver-*.yml to $workflows_dst/."
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
