#!/usr/bin/env bash
# Find the W9 grounder weights for the CI grounder gate, if any are available.
#
#   ci/dove/grounder-weights.sh <download dir>
#
# In order:
#   1. the file named by GROUNDER_WEIGHTS in scripts/dove/release/grounder.env
#      (R0.6; a path relative to the fork root), when it exists;
#   2. WEIGHTS_URL with WEIGHTS_SHA256 (the repository variables
#      DOVE_GROUNDER_WEIGHTS_URL and DOVE_GROUNDER_WEIGHTS_SHA256): downloaded
#      and refused unless the SHA-256 matches.
# Writes available=true|false and path=<absolute path> to $GITHUB_OUTPUT.
# No weights is not a failure: the gate is skipped with a notice.
set -euo pipefail
dir="${1:?usage: grounder-weights.sh <download dir>}"
fork_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
out="${GITHUB_OUTPUT:-/dev/stdout}"

found() { echo "available=true" >> "$out"; echo "path=$1" >> "$out"; echo "grounder weights: $1"; exit 0; }

env_file="$fork_root/scripts/dove/release/grounder.env"
if [ -f "$env_file" ]; then
  weights="$(sed -n 's/^GROUNDER_WEIGHTS=//p' "$env_file" | tail -1 | tr -d '"'"'"'\r')"
  if [ -n "$weights" ] && [ -f "$fork_root/$weights" ]; then
    found "$fork_root/$weights"
  fi
fi

if [ -n "${WEIGHTS_URL:-}" ]; then
  [[ "${WEIGHTS_SHA256:-}" =~ ^[0-9a-f]{64}$ ]] ||
    { echo "WEIGHTS_URL is set but WEIGHTS_SHA256 is not a lowercase SHA-256" >&2; exit 1; }
  mkdir -p "$dir"
  file="$dir/$(basename "${WEIGHTS_URL%%\?*}")"
  curl -fsSL --retry 3 -o "$file" "$WEIGHTS_URL"
  actual="$( (sha256sum "$file" 2>/dev/null || shasum -a 256 "$file") | cut -d' ' -f1)"
  [ "$actual" = "$WEIGHTS_SHA256" ] ||
    { echo "grounder weights SHA-256 mismatch: got $actual, expected $WEIGHTS_SHA256" >&2; exit 1; }
  found "$file"
fi

echo "available=false" >> "$out"
msg="no grounder weights (no file from scripts/dove/release/grounder.env, no DOVE_GROUNDER_WEIGHTS_URL); grounder gate skipped"
[ -n "${GITHUB_ACTIONS:-}" ] && echo "::notice title=dove-driver gate::$msg"
echo "$msg"
