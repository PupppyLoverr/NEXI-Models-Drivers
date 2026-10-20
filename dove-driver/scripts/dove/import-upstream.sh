#!/usr/bin/env bash
# Import one trycua/cua cua-driver release onto the `upstream` branch, unchanged.
#
#   scripts/dove/import-upstream.sh cua-driver-rs-v0.37.0
#
# The `upstream` branch holds upstream files in the fork's layout:
#   libs/cua-driver/*                -> /
#   libs/cua/crates/cua-telemetry/*  -> rust/crates/cua-telemetry/
#   LICENSE.md                       -> LICENSE
#   every monorepo file cua-telemetry embeds with include_str!/include_bytes!
#                                    -> rust/crates/cua-telemetry/data/<file name>
# Then merge `upstream` into `main`, run scripts/dove/apply-dove-changes.sh, and
# run scripts/dove/parity-check.sh.
#
# DOVE_UPSTREAM_CLONE names a trycua/cua clone to reuse (default: ../.cua-upstream).
set -euo pipefail

tag="${1:?usage: import-upstream.sh <cua-driver-rs-vX.Y.Z>}"
repo_root="$(git rev-parse --show-toplevel)"
clone="${DOVE_UPSTREAM_CLONE:-$repo_root/../.cua-upstream}"
work="$(mktemp -d)"
trap 'git -C "$repo_root" worktree remove --force "$work/tree" 2>/dev/null || true; rm -rf "$work"' EXIT

if [ ! -d "$clone/.git" ]; then
  git clone --filter=blob:none --no-checkout https://github.com/trycua/cua.git "$clone"
fi
git -C "$clone" fetch --no-tags --filter=blob:none origin "refs/tags/$tag:refs/tags/$tag"
commit="$(git -C "$clone" rev-parse "$tag^{commit}")"

# `-c core.autocrlf=false` keeps upstream's LF endings on Windows checkouts.
git -C "$clone" -c core.autocrlf=false -c core.eol=lf archive --format=tar "$commit" \
  libs/cua-driver libs/cua/crates/cua-telemetry LICENSE.md > "$work/src.tar"
mkdir -p "$work/x"
tar -xf "$work/src.tar" -C "$work/x"

git -C "$repo_root" worktree add --quiet "$work/tree" upstream
tree="$work/tree"
git -C "$tree" rm -rq --ignore-unmatch . >/dev/null
cp -r "$work/x/libs/cua-driver/." "$tree/"
telemetry="$tree/rust/crates/cua-telemetry"
mkdir -p "$telemetry/data"
cp -r "$work/x/libs/cua/crates/cua-telemetry/." "$telemetry/"
cp "$work/x/LICENSE.md" "$tree/LICENSE"

# Resolve each out-of-crate embed against the crate's upstream location
# (libs/cua/crates/cua-telemetry/<dir>/) and copy it into data/.
crate_dir="libs/cua/crates/cua-telemetry"
for dir in src tests; do
  [ -d "$telemetry/$dir" ] || continue
  grep -rhoE 'include_(str|bytes)!\("\.\./\.\./[^"]+"\)' "$telemetry/$dir" \
    | sed -E 's/^include_(str|bytes)!\("(.*)"\)$/\2/' \
    | while read -r rel; do
        src="$(realpath -m --relative-to=/r "/r/$crate_dir/$dir/$rel")"
        dst="$telemetry/data/$(basename "$src")"
        if [ -e "$dst" ] && ! git -C "$clone" show "$commit:$src" | cmp -s - "$dst"; then
          echo "two embedded files are both named $(basename "$src")" >&2
          exit 1
        fi
        git -C "$clone" -c core.autocrlf=false show "$commit:$src" > "$dst"
        echo "embedded: $src -> rust/crates/cua-telemetry/data/$(basename "$src")"
      done
done

git -C "$tree" add -A
git -C "$tree" -c core.autocrlf=false commit --quiet -m "Import trycua/cua libs/cua-driver at $tag (${commit:0:7})

Snapshot of https://github.com/trycua/cua/tree/$tag/libs/cua-driver
plus libs/cua/crates/cua-telemetry, the files it embeds, and LICENSE.md,
in the fork's layout. Unmodified."
echo "upstream <- $tag ($commit)"
