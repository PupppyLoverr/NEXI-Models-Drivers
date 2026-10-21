#!/usr/bin/env bash
# Print `--skip <test>` arguments for the known, pre-existing failures on one OS,
# for `cargo test ... -- $(...)`.
#
#   ci/dove/known-failures.sh <windows|macos|linux>
#
# Each known-failures/<os>.txt line is `<exact test path>  # <reason>`.
# Only failures that also happen on the `upstream` branch belong here (SESSION
# rules: report every failure and say whether it is pre-existing). Remove a
# line as soon as the test is fixed upstream or in a Dove patch.
set -euo pipefail
os="${1:?usage: known-failures.sh <windows|macos|linux>}"
list="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/known-failures/$os.txt"
[ -f "$list" ] || exit 0
sed -e 's/#.*//' -e 's/[[:space:]]*$//' -e '/^[[:space:]]*$/d' "$list" |
  while read -r test; do
    printf -- '--skip\n%s\n' "$test"
  done
