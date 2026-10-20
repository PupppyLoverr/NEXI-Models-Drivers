#!/usr/bin/env bash
# Download the W9 grounder weights for the `grounder` gate and print their
# absolute path on stdout (everything else goes to stderr).
#
#   WEIGHTS_URL=<url> [WEIGHTS_SHA256=<hex>] ci/dove/fetch-grounder-weights.sh
#
# The workflow sets WEIGHTS_URL from the repository variable
# DOVE_GROUNDER_WEIGHTS_URL and runs this only when it is set. When
# WEIGHTS_SHA256 is set, a download that does not match it fails the step.
set -euo pipefail
url="${WEIGHTS_URL:?WEIGHTS_URL is required}"
dir="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/dove-grounder-weights"
mkdir -p "$dir"
file="$dir/$(basename "${url%%\?*}")"

echo "downloading grounder weights from $url" >&2
curl --fail --location --silent --show-error --retry 3 --output "$file" "$url"
if [ -n "${WEIGHTS_SHA256:-}" ]; then
  if command -v sha256sum >/dev/null; then
    actual="$(sha256sum "$file" | cut -d' ' -f1)"
  else
    actual="$(shasum -a 256 "$file" | cut -d' ' -f1)"
  fi
  expected="$(printf '%s' "$WEIGHTS_SHA256" | tr '[:upper:]' '[:lower:]')"
  if [ "$actual" != "$expected" ]; then
    echo "grounder weights sha256 $actual does not match $expected" >&2
    exit 1
  fi
fi
echo "$file"
