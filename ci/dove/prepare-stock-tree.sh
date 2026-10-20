#!/usr/bin/env bash
# Make an unmodified upstream tree (the `upstream` branch) buildable, so CI can
# run a stock cua-driver next to dove-driver (ROADMAP R0.2).
#
#   ci/dove/prepare-stock-tree.sh <upstream-checkout>
#
# Upstream links cua-telemetry from outside libs/cua-driver, so its import does
# not build on its own. This applies only step 2 of
# scripts/dove/apply-dove-changes.sh (vendor cua-telemetry with its default
# sender off). Nothing is renamed and no Dove patch is applied: the result
# builds the stock `cua-driver` binary with upstream's identity and state paths.
set -euo pipefail
tree="${1:?usage: prepare-stock-tree.sh <upstream-checkout>}"
cd "$tree/rust"
[ -d crates/cua-telemetry ] || { echo "no crates/cua-telemetry in $tree; not an upstream import" >&2; exit 1; }
if grep -q '^name = "dove-driver"' crates/cua-driver/Cargo.toml; then
  echo "$tree is a dove-driver tree, not stock upstream" >&2
  exit 1
fi

grep -q '"crates/cua-telemetry"' Cargo.toml ||
  sed -i '/^    "crates\/pip-preview",/a\    "crates/cua-telemetry",' Cargo.toml
sed -i -E 's#cua-telemetry = \{ path = "\.\./\.\./\.\./\.\./cua/crates/cua-telemetry"#cua-telemetry = { path = "../cua-telemetry"#' \
  crates/cua-driver/Cargo.toml
sed -i 's/^version.workspace = true/version = "0.1.0"/; s/^edition.workspace = true/edition = "2024"/; s/^authors.workspace = true/authors = ["trycua"]/; s/^license.workspace = true/license = "MIT"/; s#^repository.workspace = true#repository = "https://github.com/trycua/cua"#; s/^serde.workspace = true/serde = { version = "1", features = ["derive"] }/; s/^serde_json.workspace = true/serde_json = "1"/; s/^sha2.workspace = true/sha2 = "0.10"/; s/^hex.workspace = true/hex = "0.4"/; s/^rand.workspace = true/rand = "0.9"/; s/^tempfile.workspace = true/tempfile = "3"/' \
  crates/cua-telemetry/Cargo.toml
sed -i 's/^default = \["http"\]$/default = []/' crates/cua-telemetry/Cargo.toml
{ grep -rlE 'include_(str|bytes)!\("\.\./\.\./' crates/cua-telemetry/src crates/cua-telemetry/tests 2>/dev/null || true; } |
  xargs -r sed -i -E 's#include_(str|bytes)!\("\.\./(\.\./)+([^"]*/)?([^"/]+)"\)#include_\1!("../data/\4")#g'
grep -q '^name = "cua-driver"' crates/cua-driver/Cargo.toml || { echo "stock binary name changed upstream" >&2; exit 1; }
echo "stock tree ready: $tree (binary cua-driver)"
