# dove-driver

Background computer-use driver for Dove, an MCP server for macOS (AX), Windows (UIA) and Linux (AT-SPI). It is
a fork of [Cua Driver](https://github.com/trycua/cua/tree/cua-driver-rs-v0.37.0/libs/cua-driver)
(`trycua/cua`, `libs/cua-driver`, tag `cua-driver-rs-v0.37.0`, commit `2d2f992`), MIT licensed. It does
everything that upstream release does (see "Branches" below).

Dove does not ship this driver preinstalled. Dove installs signed `dove-driver` release assets as the
**Dove Computer Use** plugin. This repository builds those assets.

- What is planned: [ROADMAP.md](ROADMAP.md)
- What changed from upstream, and what was left out: [NOTICE.md](NOTICE.md)
- How it compares with nexi-cua: [NEXI_CUA_COMPARISON.md](NEXI_CUA_COMPARISON.md)
- Upstream's own README: [docs/UPSTREAM_README.md](docs/UPSTREAM_README.md)

## Where it lives

dove-driver is the `dove-driver/` folder of
[PupppyLoverr/NEXI-Models-Drivers](https://github.com/PupppyLoverr/NEXI-Models-Drivers). Work happens on that
repository's `dove-driver/main` and `dove-driver/upstream` branches. The folder on `main` is a copy of
`dove-driver/main`, refreshed with `scripts/dove/publish-folder.sh`. To work on it:

```bash
git clone --branch dove-driver/main --single-branch https://github.com/PupppyLoverr/NEXI-Models-Drivers.git dove-driver
cd dove-driver
git fetch origin dove-driver/upstream:upstream
git checkout -b main
```

The sync and parity scripts expect the local branches to be named `main` and `upstream`.

## Build

```bash
cd rust
cargo build --release -p cua-driver -p cua-driver-uia
```

The build writes `rust/target/release/dove-driver(.exe)` and, on Windows, the `dove-driver-uia.exe` uiAccess
sidecar. The toolchain is pinned in `rust/rust-toolchain.toml` (1.97.1).

On Windows, the Visual Studio Build Tools need the **MSVC Spectre-mitigated libs** component for the toolset you
build with (for example "MSVC v143 - VS 2022 C++ x64/x86 Spectre-mitigated libs (Latest)"). The `regorus` policy
engine depends on `msvc_spectre_libs` with its `error` feature, so without the component the build stops in that
crate's build script.

## Test

```bash
cd rust
cargo test -p cua-driver
```

`cua-telemetry` comes from upstream's `libs/cua` workspace, whose cargo config sets telemetry env vars for tests.
Run its tests the same way, with its `http` sender on:

```bash
CUA_TELEMETRY=0 CUA_TELEMETRY_FORBID_NETWORK=1 CUA_TELEMETRY_SYNTHETIC=1 cargo test -p cua-telemetry --features http
```

## Branches

- `upstream`: unmodified imports of `libs/cua-driver`, one commit per upstream tag.
- `main`: `upstream` plus Dove's changes, and nothing else (checked by `scripts/dove/parity-check.sh`).

To take a new upstream release:

```bash
scripts/dove/sync-upstream.sh cua-driver-rs-vX.Y.Z
```

It imports the tag onto `upstream`, stages a merge into `main`, reapplies Dove's changes
(`scripts/dove/apply-dove-changes.sh`, including the feature patches in `scripts/dove/patches/`) and runs the parity
check. Build, test, update the base in NOTICE.md, then commit.

## License

MIT. See [LICENSE](LICENSE). Copyright (c) 2025 Cua AI, Inc. The upstream notice is kept unchanged, and Dove's
changes are released under the same license.
