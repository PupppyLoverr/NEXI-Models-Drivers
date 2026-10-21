# Notice

dove-driver is derived from Cua Driver, part of https://github.com/trycua/cua (MIT, Copyright (c) 2025 Cua AI, Inc.).
The full license text is in [LICENSE](LICENSE), which is upstream's `LICENSE.md` with no changes.

## Base

| | |
|---|---|
| Upstream repository | https://github.com/trycua/cua |
| Path | `libs/cua-driver` |
| Tag | `cua-driver-rs-v0.37.0` (released 2026-10-20) |
| Commit | `2d2f99228d4d2508dc6fcc84c176b296e146714a` |
| Also imported | `libs/cua/crates/cua-telemetry`, vendored to `rust/crates/cua-telemetry`, because `crates/cua-driver` depends on it by an out-of-tree path. The monorepo files it embeds are copied unchanged into `rust/crates/cua-telemetry/data/`. |
| History | `upstream` branch: one unmodified import per upstream tag (v0.34.0, v0.37.0) |

## Parity with upstream

`main` is the `upstream` branch with the changes below applied, plus the Dove-only files listed in
`scripts/dove/dove-only-files.sh`. Nothing else differs. `scripts/dove/parity-check.sh` rebuilds that tree from
`upstream` and fails on any other difference, and `scripts/dove/sync-upstream.sh <tag>` moves the fork to a new
upstream release. Every tool, flag and behaviour of the upstream release is therefore in dove-driver. Features Dove
adds on top must be new files or new code paths that leave upstream behaviour unchanged.

## Excluded

- `rust/crates/cua-perception` is removed from the tree and from the workspace. It is the offline visual
  perception worker, and its model artifacts include the OmniParser icon detector, which is **AGPL-3.0-only**.
  The driver's code for talking to an *installed* perception extension (`perception_client`, `extension_manager`)
  is MIT and is kept, so `parse_visual_regions` and `install_extension` behave as upstream when a user installs
  the extension themselves. dove-driver does not distribute the extension, and Dove does not install it.

## Changes on `main` (all made by `scripts/dove/apply-dove-changes.sh`)

- The release executable is named `dove-driver` (local build: `dove-driver-local`). The Windows uiAccess sidecar is
  named `dove-driver-uia(.exe)`, and the Windows autostart task is `dove-driver-serve`. Product identity is in
  `rust/crates/cua-driver/src/bundle.rs`. Tests that locate the built binary use `CARGO_BIN_EXE_dove-driver`.
- `cua-telemetry` is a workspace member with explicit package metadata. Its `include_str!` paths point at `data/`,
  and its default features are off, matching how upstream links it into the driver (`default-features = false`).
- Upstream's README is at `docs/UPSTREAM_README.md`.

Feature patches (`scripts/dove/patches/`, applied by the same script):

- `0001-own-state-and-identity.patch`. dove-driver never shares state with a stock cua-driver on the same machine:
  - state namespace `dove-driver(-local)`, which names the daemon pipe `\\.\pipe\dove-driver`, the Unix socket, the
    history store and the OS credential-store entries;
  - home directory `~/.dove-driver(-local)`, including `config.json` and the home-override fallbacks. The legacy
    `~/.cua-driver-rs` migrations point at `~/.dove-driver-rs`, so a stock install's state is never imported;
  - uiAccess worker pipe `\\.\pipe\dove-driver(-local)-uia`;
  - per-user data dirs `DoveDriver\BrowserProfiles`, `Dove Driver\cursor-themes`, `dove-driver/...` on Linux, and
    the libei token and client name;
  - the SDK's default daemon namespace;
  - it reports itself as `dove-driver`: MCP `serverInfo`, `--version`, `health_report`, `doctor`.
  - `DOVE_DRIVER_<NAME>` variables are aliases for `CUA_DRIVER_<NAME>`, applied at startup when the upstream name is
    unset (`rust/crates/cua-driver/src/dove_env.rs`). `DOVE_DRIVER_HOME` also sets `CUA_DRIVER_RS_HOME`.
- `0002-no-upstream-phone-home.patch`. The driver makes no network request Dove did not ask for:
  - usage telemetry is off by default. If an operator turns it on, events go only to `CUA_DRIVER_TELEMETRY_URL`
    (or `DOVE_DRIVER_TELEMETRY_URL`), which has no default; Cua's PostHog endpoint is removed;
  - the update check (startup banner, `check_for_update`, `dove-driver update`) never queries trycua releases, and
    the updater never runs Cua's install script. Dove's plugin manager owns installs and updates.
- `0004-lazy-tool-disclosure.patch`. With `DOVE_TOOL_DISCLOSURE=lazy` (or `DOVE_DRIVER_TOOL_DISCLOSURE` /
  `CUA_DRIVER_TOOL_DISCLOSURE`), MCP `tools/list` keeps full entries only for `list_windows`, `get_window_state`,
  `run_steps`, `verify_state`, `act` (if registered) and the new `describe_tools`, and lists every other tool with a
  one-line description and `{"type":"object"}`. `describe_tools {names}` returns the full entries, withheld tools
  still run, and a bad-arguments error carries the tool's input schema. The initialize instructions and the served
  `SKILL.md` gain one note on `describe_tools`. Unset, the tool list, instructions and skill resources are
  upstream's byte for byte (`rust/crates/cua-driver-core/src/tool_disclosure.rs`).

Still upstream's: internal crate names (`cua-driver-core` and the rest), `CUA_DRIVER_*` variable names (now with
`DOVE_DRIVER_*` aliases), protocol identifiers (history schema URNs, the policy `server` name, telemetry event
names), the bundled skill pack (`cua-driver`), and the macOS app identity (`CuaDriver.app`, `com.trycua.driver`),
which is work item R0.3 in [ROADMAP.md](ROADMAP.md). Network use that only happens on an explicit request is
unchanged: `skills install` downloads upstream's skill pack, `install_ffmpeg` downloads ffmpeg, and
`install_extension` needs a catalog the operator names.
