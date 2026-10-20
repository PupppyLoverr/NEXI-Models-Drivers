#!/usr/bin/env bash
# Run one optional CI gate if the work item that owns it has provided it.
#
#   ci/dove/run-gate.sh <name>
#
# A gate is the Dove-only script ci/dove/gates/<name>.sh. Until it exists,
# this prints a notice and passes, so the CI slot is in place before the gate
# is. Once it exists, it runs, and its exit status is the step's.
#
# Gates get these variables, set by the workflow:
#   DOVE_CI_OS              windows | macos | linux-x11 | linux-sway
#   DOVE_CI_DRIVER_BIN      absolute path of the built dove-driver
#   DOVE_CI_ARTIFACTS       directory whose contents the job uploads
#   DOVE_CI_GROUNDER_WEIGHTS  (grounder gate only) absolute path of the weights
#
# Known gates (ROADMAP): `latency` (W4.5, latency budget on the W7 fixture
# apps) and `grounder` (W9, local grounder accuracy; the workflow runs it only
# when weights are available).
set -euo pipefail
name="${1:?usage: run-gate.sh <name>}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
gate="$here/gates/$name.sh"

if [ ! -f "$gate" ]; then
  msg="gate '$name' is not provided yet (no ci/dove/gates/$name.sh); slot passes"
  if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::notice title=dove-driver gate::$msg"; fi
  echo "$msg"
  exit 0
fi
: "${DOVE_CI_DRIVER_BIN:?DOVE_CI_DRIVER_BIN is required}"
: "${DOVE_CI_OS:?DOVE_CI_OS is required}"
export DOVE_CI_ARTIFACTS="${DOVE_CI_ARTIFACTS:-$PWD/artifacts/gates}"
mkdir -p "$DOVE_CI_ARTIFACTS/$name"
echo "running gate '$name' on $DOVE_CI_OS with $DOVE_CI_DRIVER_BIN"
exec bash "$gate"
