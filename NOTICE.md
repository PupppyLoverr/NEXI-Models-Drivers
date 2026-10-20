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

Internal crate names (`cua-driver-core`, `cua-driver-contract` and the rest), environment variables (`CUA_DRIVER_*`),
the state directory (`~/.cua-driver`), named pipes, the `--version` string, the MCP `serverInfo.name` and the macOS
app identity are still upstream's. Renaming them is work item R0.2 in [ROADMAP.md](ROADMAP.md).
