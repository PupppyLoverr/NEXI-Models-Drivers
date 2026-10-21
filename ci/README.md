# dove-driver CI (ROADMAP W7)

Everything under `ci/` exists only in the fork (`scripts/dove/dove-only-files.sh`).

## Where the workflows run

GitHub runs workflows only from a repository's root `.github/workflows/`. dove-driver is published as the
`dove-driver/` folder of `PupppyLoverr/NEXI-Models-Drivers`, so the workflows are written here, in
`ci/github-workflows/dove-driver-*.yml`, with `working-directory: dove-driver`.
`scripts/dove/publish-folder.sh` copies each one to the root `.github/workflows/` in the same fast-forward-only
API commit that refreshes the folder (its `gh` token then needs the `workflow` scope). Edit the copies here, never
the root copies.

## dove-driver-ci.yml

| Job | Runner | What it proves |
|---|---|---|
| `windows` | windows-2025 | Spectre libs present (R0.5), parity with upstream + Dove changes, release build, unit and shared contract tests, WinUI3 fixture UIA e2e (`harness_winui3_test`) |
| `macos` | macos-26 | build, unit and contract tests, SwiftUI fixture AX e2e (`harness_swiftui_test`) through a TCC-seeded `CuaDriver.app` daemon (`ci/dove/macos/ax-daemon.sh`). Skipped for pull requests from forks |
| `linux-x11` | ubuntu-24.04 | build, unit and contract tests, GTK3 fixture AT-SPI e2e (`harness_gtk3_test`) on Xvfb + openbox |
| `linux-sway` | ubuntu-24.04 | GTK3 fixture AT-SPI e2e in a headless native Wayland Sway session |
| `side-by-side` | all three | R0.2: dove-driver and a stock cua-driver (built from `dove-driver/upstream`) run together with separate state (`ci/dove/side_by_side.py`) |
| `result` | ubuntu-24.04 | the single check to require |

Triggers: pushes to `main` and pull requests that touch `dove-driver/**` or these workflows, manual dispatch, and
`workflow_call` (the R0.6 release workflow uses it as its gate).

## Gate slots

`ci/dove/run-gate.sh <name>` runs `ci/dove/gates/<name>.sh` if it exists and otherwise passes with a notice.
Gates get `DOVE_CI_OS`, `DOVE_CI_DRIVER_BIN`, `DOVE_CI_ARTIFACTS` and, for `grounder`, `DOVE_CI_GROUNDER_WEIGHTS`.

- `latency`: W4.5 latency budget. Runs on every OS job.
- `grounder`: W9. Runs only when `ci/dove/grounder-weights.sh` finds weights: the file named in
  `scripts/dove/release/grounder.env`, or the repository variables `DOVE_GROUNDER_WEIGHTS_URL` +
  `DOVE_GROUNDER_WEIGHTS_SHA256`.

## Known failures

`ci/dove/known-failures/<os>.txt` lists unit tests that also fail on the `upstream` branch. The unit steps skip
exactly those. Keep the list short and remove entries once fixed.

## Running pieces locally

- `python3 ci/dove/side_by_side.py --dove <dove-driver> --stock <cua-driver>`; build the stock binary from the
  `upstream` branch after `ci/dove/prepare-stock-tree.sh <checkout>`.
- `ci/dove/linux/x11-session.sh <command>` / `ci/dove/linux/sway-session.sh <command>` give a command a virtual
  desktop with AT-SPI.
- `ci/dove/macos/ax-daemon.sh` edits the system TCC database and refuses to run outside a GitHub-hosted runner.
