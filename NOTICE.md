# Notice

dove-driver is derived from Cua Driver, part of https://github.com/trycua/cua (MIT, Copyright (c) 2025 Cua AI, Inc.).
The full license text is in [LICENSE](LICENSE), which is upstream's `LICENSE.md` with no changes.

## Base

| | |
|---|---|
| Upstream repository | https://github.com/trycua/cua |
| Path | `libs/cua-driver` |
| Tag | `cua-driver-rs-v0.34.0` |
| Commit | `b0968e1b12834e485dda68789541a3cc57664a9f` (2026-10-05) |
| Also imported | `libs/cua/crates/cua-telemetry`, vendored to `rust/crates/cua-telemetry`, because `crates/cua-driver` depends on it by an out-of-tree path |

## Excluded

- `rust/crates/cua-perception` was removed from the tree and from the workspace. It is the offline visual
  perception worker, and its model artifacts include the OmniParser icon detector, which is **AGPL-3.0-only**.
  The driver's code for talking to an *installed* perception extension (`perception_client`, `extension_manager`)
  is MIT and is kept. dove-driver does not distribute the extension, and Dove does not install it.

## Changes on `main` (relative to the `upstream` branch)

- The release executable is named `dove-driver` (local build: `dove-driver-local`). The Windows uiAccess sidecar is
  named `dove-driver-uia(.exe)`, and the Windows autostart task is `dove-driver-serve`. Product identity is in
  `rust/crates/cua-driver/src/bundle.rs`.
- Tests that locate the built binary use `CARGO_BIN_EXE_dove-driver`.
- `cua-telemetry` is a workspace member with explicit package metadata. The four files it embeds from elsewhere in
  the cua monorepo are copied, unchanged, into `rust/crates/cua-telemetry/data/`: `libs/images/sandbox-images.json`,
  `libs/cua/crates/cua-teleport/src/ux/targets.json`, and `docs/content/docs/cua-sdk/concepts/telemetry.mdx` and
  `telemetry-events.mdx` (test only).

Internal crate names (`cua-driver-core`, `cua-driver-contract` and the rest), environment variables (`CUA_DRIVER_*`),
the state directory (`~/.cua-driver`), named pipes, the `--version` string, the MCP `serverInfo.name` and the macOS
app identity are still upstream's. Renaming them is
work item R0 in [ROADMAP.md](ROADMAP.md).
