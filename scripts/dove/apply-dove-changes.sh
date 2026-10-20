#!/usr/bin/env bash
# Apply the Dove fork's changes to an upstream tree. Safe to run more than once.
# Every change `main` makes to upstream files is made here, so that after
# merging a new upstream release, running this script restores the fork.
# scripts/dove/parity-check.sh checks that main differs from upstream only in
# the ways listed here.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# Upstream's README becomes docs/UPSTREAM_README.md (the fork keeps its own README at the root).
if [ -f README.md ] && head -1 README.md | grep -q '^# Cua Driver'; then
  mv README.md docs/UPSTREAM_README.md
fi

cd rust

# 1. Drop the perception worker: its model artifacts include the AGPL-3.0-only
#    OmniParser detector. The driver's client for an installed extension stays.
rm -rf crates/cua-perception
sed -i '/"crates\/cua-perception",/d' Cargo.toml

# 2. Vendor cua-telemetry as a workspace member with explicit metadata.
grep -q '"crates/cua-telemetry"' Cargo.toml ||
  sed -i '/^    "crates\/pip-preview",/a\    "crates/cua-telemetry",' Cargo.toml
sed -i -E 's#cua-telemetry = \{ path = "\.\./\.\./\.\./\.\./cua/crates/cua-telemetry"#cua-telemetry = { path = "../cua-telemetry"#' \
  crates/cua-driver/Cargo.toml
sed -i 's/^version.workspace = true/version = "0.1.0"/; s/^edition.workspace = true/edition = "2024"/; s/^authors.workspace = true/authors = ["trycua"]/; s/^license.workspace = true/license = "MIT"/; s#^repository.workspace = true#repository = "https://github.com/trycua/cua"#; s/^serde.workspace = true/serde = { version = "1", features = ["derive"] }/; s/^serde_json.workspace = true/serde_json = "1"/; s/^sha2.workspace = true/sha2 = "0.10"/; s/^hex.workspace = true/hex = "0.4"/; s/^rand.workspace = true/rand = "0.9"/; s/^tempfile.workspace = true/tempfile = "3"/' \
  crates/cua-telemetry/Cargo.toml
# Upstream links cua-telemetry into the driver with default-features = false. As a
# workspace member its default `http` sender would be switched on by a whole-workspace
# build, so default it off to keep upstream's driver build.
sed -i 's/^default = \["http"\]$/default = []/' crates/cua-telemetry/Cargo.toml
if grep -q '\.workspace = true' crates/cua-telemetry/Cargo.toml; then
  echo "cua-telemetry inherits workspace keys this script does not fill in:" >&2
  grep -n '\.workspace = true' crates/cua-telemetry/Cargo.toml >&2
  exit 1
fi
# Point every out-of-crate include_str!/include_bytes! at the copy in data/.
{ grep -rlE 'include_(str|bytes)!\("\.\./\.\./' crates/cua-telemetry/src crates/cua-telemetry/tests 2>/dev/null || true; } |
  xargs -r sed -i -E 's#include_(str|bytes)!\("\.\./(\.\./)+([^"]*/)?([^"/]+)"\)#include_\1!("../data/\4")#g'

# 3. Executable identity: dove-driver and dove-driver-uia.
sed -i 's/^default-run = "cua-driver"/default-run = "dove-driver"/; /^\[\[bin\]\]/{n;s/^name = "cua-driver"$/name = "dove-driver"/}' \
  crates/cua-driver/Cargo.toml
sed -i '/^\[\[bin\]\]/{n;s/^name = "cua-driver-uia"$/name = "dove-driver-uia"/}' crates/cua-driver-uia/Cargo.toml
sed -i 's/RELEASE_CLI_NAME: &str = "cua-driver"/RELEASE_CLI_NAME: \&str = "dove-driver"/; s/LOCAL_CLI_NAME: &str = "cua-driver-local"/LOCAL_CLI_NAME: \&str = "dove-driver-local"/; s/"cua-driver-uia-local.exe"/"dove-driver-uia-local.exe"/; s/"cua-driver-uia.exe"/"dove-driver-uia.exe"/; s/"cua-driver-local-serve"/"dove-driver-local-serve"/; s/"cua-driver-serve"/"dove-driver-serve"/' \
  crates/cua-driver/src/bundle.rs
sed -i 's#MacOS/cua-driver-local"#MacOS/dove-driver-local"#; s#/dev/.cua-driver-local/cua-driver-local.exe#/dev/.cua-driver-local/dove-driver-local.exe#; s#MacOS/cua-driver"#MacOS/dove-driver"#; s#"/tmp/cua-driver-local-test"#"/tmp/dove-driver-local-test"#' \
  crates/cua-driver/src/bundle.rs
sed -i 's/eq_ignore_ascii_case("cua-driver-uia-local.exe")/eq_ignore_ascii_case("dove-driver-uia-local.exe")/' \
  crates/cua-driver-uia/src/main.rs
sed -i 's/"cua-driver.exe"/"dove-driver.exe"/; s/^        "cua-driver"$/        "dove-driver"/' \
  crates/cua-driver-testkit/src/paths.rs
{ grep -rl 'CARGO_BIN_EXE_cua-driver\b' --include=*.rs crates || true; } | xargs -r sed -i 's/CARGO_BIN_EXE_cua-driver\b/CARGO_BIN_EXE_dove-driver/g'

cd ..

# 4. Dove features: one patch per feature in scripts/dove/patches/, applied in
#    file-name order. A patch already applied is skipped; one that no longer
#    applies stops the script so an upstream sync cannot drop it silently.
patch_dir="$(dirname "${BASH_SOURCE[0]}")/patches"
for patch in "$patch_dir"/*.patch; do
  [ -e "$patch" ] || continue
  if git apply --reverse --check "$patch" 2>/dev/null; then
    continue
  fi
  if ! git apply --3way "$patch"; then
    echo "patch no longer applies: $(basename "$patch")" >&2
    exit 1
  fi
done

echo "Dove changes applied"
