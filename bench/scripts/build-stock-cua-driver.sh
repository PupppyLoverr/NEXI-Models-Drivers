#!/usr/bin/env bash
# Build stock cua-driver (configuration C) from the unmodified `upstream`
# branch. The only edit is the cua-telemetry path, which upstream points at
# its monorepo sibling (libs/cua/crates/cua-telemetry) and which this import
# vendors under crates/. No Dove transform or patch is applied, so the binary
# behaves as the upstream release at the same tag.
#
#   bash bench/scripts/build-stock-cua-driver.sh [<git-ref>] [<out-dir>]
# Prints the path of the built binary.
set -euo pipefail

ref="${1:-upstream}"
out="${2:-${TMPDIR:-/tmp}/dove-bench-stock}"
repo_root="$(git rev-parse --show-toplevel)"
src="$out/src"

if [ ! -d "$src/.git" ] && [ ! -f "$src/.git" ]; then
  git -C "$repo_root" worktree add --force --detach "$src" "$ref" >/dev/null
else
  git -C "$src" checkout --quiet --detach "$ref"
  git -C "$src" checkout --quiet -- .
fi
# Same vendoring as step 2 of scripts/dove/apply-dove-changes.sh (build metadata only).
(
  cd "$src/rust"
  grep -q '"crates/cua-telemetry"' Cargo.toml ||
    sed -i '/^    "crates\/pip-preview",/a\    "crates/cua-telemetry",' Cargo.toml
  sed -i -E 's#cua-telemetry = \{ path = "\.\./\.\./\.\./\.\./cua/crates/cua-telemetry"#cua-telemetry = { path = "../cua-telemetry"#' \
    crates/cua-driver/Cargo.toml
  sed -i 's/^version.workspace = true/version = "0.1.0"/; s/^edition.workspace = true/edition = "2024"/; s/^authors.workspace = true/authors = ["trycua"]/; s/^license.workspace = true/license = "MIT"/; s#^repository.workspace = true#repository = "https://github.com/trycua/cua"#; s/^serde.workspace = true/serde = { version = "1", features = ["derive"] }/; s/^serde_json.workspace = true/serde_json = "1"/; s/^sha2.workspace = true/sha2 = "0.10"/; s/^hex.workspace = true/hex = "0.4"/; s/^rand.workspace = true/rand = "0.9"/; s/^tempfile.workspace = true/tempfile = "3"/' \
    crates/cua-telemetry/Cargo.toml
  sed -i 's/^default = \["http"\]$/default = []/' crates/cua-telemetry/Cargo.toml
  { grep -rlE 'include_(str|bytes)!\("\.\./\.\./' crates/cua-telemetry/src crates/cua-telemetry/tests 2>/dev/null || true; } |
    xargs -r sed -i -E 's#include_(str|bytes)!\("\.\./(\.\./)+([^"]*/)?([^"/]+)"\)#include_\1!("../data/\4")#g'
)

(cd "$src/rust" && CARGO_TARGET_DIR="$out/target" cargo build --release -p cua-driver >&2)
echo "$out/target/release/cua-driver"
