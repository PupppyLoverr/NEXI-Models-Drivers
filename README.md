# dove-driver

Background computer-use driver for Dove, an MCP server for macOS (AX), Windows (UIA) and Linux (AT-SPI). It is
a fork of [Cua Driver](https://github.com/trycua/cua/tree/cua-driver-rs-v0.34.0/libs/cua-driver)
(`trycua/cua`, `libs/cua-driver`, tag `cua-driver-rs-v0.34.0`, commit `b0968e1`), MIT licensed.

Dove does not ship this driver preinstalled. Dove installs signed `dove-driver` release assets as the
**Dove Computer Use** plugin. This repository builds those assets.

- What is planned: [ROADMAP.md](ROADMAP.md)
- What changed from upstream, and what was left out: [NOTICE.md](NOTICE.md)
- Upstream's own README: [docs/UPSTREAM_README.md](docs/UPSTREAM_README.md)

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

## Branches

- `upstream`: unmodified imports of `libs/cua-driver`, one commit per upstream tag. To move the base, import a newer
  tag here and merge it into `main`.
- `main`: the Dove fork.

## License

MIT. See [LICENSE](LICENSE). Copyright (c) 2025 Cua AI, Inc. The upstream notice is kept unchanged, and Dove's
changes are released under the same license.
