# dove-driver releases (ROADMAP R0.6)

Dove's Computer Use plugin installs dove-driver from a GitHub release of
[PupppyLoverr/NEXI-Models-Drivers](https://github.com/PupppyLoverr/NEXI-Models-Drivers), tagged
`dove-driver-v<version>`. Each release carries a manifest, `dove-driver-manifest.json`, that lists every asset with
its SHA-256 and size. Dove compiles that manifest in, so a download is accepted only if it matches what Dove was
built with.

This file is Dove-only. The pieces:

| Path (fork root) | What it is |
| --- | --- |
| `ci/github-workflows/dove-driver-release.yml` | The release workflow. `scripts/dove/publish-folder.sh` copies it to the NEXI-Models-Drivers root `.github/workflows/`, because GitHub only runs workflows from there. Every step runs in `dove-driver/`. |
| `scripts/dove/release/package.py` | Packs one platform archive and writes its `.meta.json` (every file, its hash, size and role). Reproducible: the same inputs give the same bytes. |
| `scripts/dove/release/build_manifest.py` | Turns the `.meta.json` files, the archives and the optional grounder weights into `dove-driver-manifest.json`. |
| `scripts/dove/release/verify_manifest.py` | Checks a manifest, and with `--assets-dir` the archives it describes. This is the same check Dove's installer makes. |
| `scripts/dove/release/dove-driver-manifest.schema.json` | JSON Schema (draft 2020-12) of the manifest. |
| `scripts/dove/release/test_manifest.py` | Tests: packages dummy binaries for every platform, builds a manifest, and checks that `verify_manifest.py` and the schema accept it and reject broken manifests, tampered archives and links. Runs in the workflow's preflight. |
| `scripts/dove/release/min-dove-version` | The oldest Dove that can run this dove-driver. Raise it when the driver needs a newer Dove. |
| `scripts/dove/release/grounder.env` | Where the release finds the optional W9 grounder weights. |

## Assets of a release

| Asset | Contents | Signing |
| --- | --- | --- |
| `dove-driver-<v>-windows-x86_64.zip` | `dove-driver.exe`, `dove-driver-uia.exe`, LICENSE, NOTICE.md, THIRD_PARTY_NOTICES.md | Authenticode (both executables), Sigstore |
| `dove-driver-<v>-windows-arm64.zip` | same, built for aarch64-pc-windows-msvc | Authenticode, Sigstore |
| `dove-driver-<v>-macos-universal.tar.gz` | universal `dove-driver`, `DoveDriver.app` (notarized and stapled), notices | Developer ID + notarization, Sigstore. **Only when macOS signing is enabled (needs R0.3).** |
| `dove-driver-<v>-linux-x86_64.tar.gz` | `dove-driver`, `wayland-helper/`, notices. Built on Debian 11, so glibc 2.31 or newer. | Sigstore |
| `dove-driver-<v>-linux-arm64.tar.gz` | same, aarch64 | Sigstore |
| `dove-grounder-<v>-fp16.<ext>` | Optional W9 grounder weights (fp16, about 3.2 MB). Present only when `grounder.env` points at weights. | Sigstore |
| `dove-driver-manifest.json` | The manifest below | Sigstore |
| `SHA256SUMS` | `sha256sum` of every asset above | Sigstore |
| `<file>.sigstore.json` | Keyless cosign bundle for each file above | |

Every archive has one top-level directory named like the archive without its extension
(`dove-driver-0.37.0-windows-x86_64/`). Nothing else is at the top level, and there are no links.

## Manifest format (`manifest_version` 1)

```json
{
  "manifest_version": 1,
  "name": "dove-driver",
  "version": "0.37.0",
  "tag": "dove-driver-v0.37.0",
  "repository": "PupppyLoverr/NEXI-Models-Drivers",
  "published_at": "2026-10-20T10:47:00Z",
  "source": {
    "commit": "<40-hex commit of the tag in NEXI-Models-Drivers>",
    "fork_tree": "<40-hex tree of dove-driver/ at that commit>",
    "upstream": "cua-driver-rs-v0.37.0"
  },
  "min_dove_version": "0.1.0",
  "sigstore": {
    "certificate_identity": "https://github.com/PupppyLoverr/NEXI-Models-Drivers/.github/workflows/dove-driver-release.yml@refs/tags/dove-driver-v0.37.0",
    "certificate_oidc_issuer": "https://token.actions.githubusercontent.com"
  },
  "platforms": {
    "windows-x86_64": {
      "name": "dove-driver-0.37.0-windows-x86_64.zip",
      "url": "https://github.com/PupppyLoverr/NEXI-Models-Drivers/releases/download/dove-driver-v0.37.0/dove-driver-0.37.0-windows-x86_64.zip",
      "sha256": "<64-hex>",
      "size": 22014679,
      "sigstore_bundle": "dove-driver-0.37.0-windows-x86_64.zip.sigstore.json",
      "os": "windows",
      "arch": "x86_64",
      "archive": "zip",
      "root": "dove-driver-0.37.0-windows-x86_64",
      "entrypoint": "dove-driver.exe",
      "files": [
        { "path": "LICENSE", "sha256": "<64-hex>", "size": 1077, "role": "license" },
        { "path": "NOTICE.md", "sha256": "<64-hex>", "size": 2140, "role": "notice" },
        { "path": "THIRD_PARTY_NOTICES.md", "sha256": "<64-hex>", "size": 5160, "role": "notice" },
        { "path": "dove-driver-uia.exe", "sha256": "<64-hex>", "size": 25298944, "executable": true, "role": "uia-sidecar" },
        { "path": "dove-driver.exe", "sha256": "<64-hex>", "size": 38398464, "executable": true, "role": "driver" }
      ],
      "signing": { "authenticode": "signed", "authenticode_subject": "<signer CN>", "apple_notarized": "not-applicable" }
    }
  },
  "optional_assets": {
    "grounder": {
      "name": "dove-grounder-0.37.0-fp16.onnx",
      "url": "https://github.com/PupppyLoverr/NEXI-Models-Drivers/releases/download/dove-driver-v0.37.0/dove-grounder-0.37.0-fp16.onnx",
      "sha256": "<64-hex>",
      "size": 3355443,
      "sigstore_bundle": "dove-grounder-0.37.0-fp16.onnx.sigstore.json",
      "format": "onnx",
      "precision": "fp16",
      "description": "W9 local grounder weights. Optional: dove-driver works without them."
    }
  }
}
```

Fields:

| Field | Meaning |
| --- | --- |
| `manifest_version` | Always `1` for this format. Dove refuses any other value. A breaking change gets a new number. |
| `version`, `tag` | dove-driver's version (`rust/VERSION`) and the release tag, `dove-driver-v<version>`. |
| `repository` | The GitHub repository holding the release. Every `url` is `https://github.com/<repository>/releases/download/<tag>/<name>`. |
| `published_at` | When the manifest was built, in UTC, exactly `YYYY-MM-DDTHH:MM:SSZ`. |
| `source.commit` | The NEXI-Models-Drivers commit the tag points at. `source.fork_tree` is the tree of its `dove-driver/` folder, which equals a commit of `dove-driver/main`. `source.upstream` is the trycua release the fork is based on. |
| `min_dove_version` | The oldest Dove that may install this release. |
| `sigstore` | The keyless signer of every asset: this workflow, at this tag, on GitHub Actions. |
| `platforms` | One entry per platform key: `windows-x86_64`, `windows-arm64`, `macos-universal`, `linux-x86_64`, `linux-arm64`. A missing key means this release does not support that platform. Each entry has the download fields (`name`, `url`, `sha256`, `size`, `sigstore_bundle`), `os` (`windows`, `macos`, `linux`) and `arch` (`x86_64`, `arm64`, `universal`), which follow from the key, the archive layout (`archive`: `zip` or `tar.gz`; `root`; `entrypoint`, relative to `root`), `files` (every regular file, sorted by path, with `sha256`, `size`, optional `executable` and `role`: `driver`, `uia-sidecar`, `app-bundle-driver`, `license`, `notice`; files without a role, such as `wayland-helper/` on Linux, are support files), and `signing`. Exactly one file has role `driver`, and it is the `entrypoint`. |
| `signing.authenticode` | Windows: `signed` or `unsigned`; elsewhere `not-applicable`. `authenticode_subject` is the signer's CN. |
| `signing.apple_notarized` | macOS: `notarized` or `unsigned`; elsewhere `not-applicable`. `apple_team_id` is the Developer ID team. |
| `optional_assets.grounder` | The W9 weights: download fields plus `format` (`onnx`, `safetensors`, `gguf`, `bin`) and `precision` (`fp16`, `fp32`, `int8`). Absent when the release has none. |

`verify_manifest.py` and the schema enforce all of this, including that `url` and `sigstore_bundle` follow from
`name`, that `root` and `name` follow from `version` and the platform key, that Windows archives contain the
`uia-sidecar`, that `entrypoint` is the `driver`, that no path is absolute or contains `..`, and that no object has
keys other than those listed here. The schema cannot express the cross-field rules (`url`, `tag`, `root`, roles,
`signing` per OS); `verify_manifest.py` checks those too, so Dove should port `verify_manifest.py`, not just the schema.

## How Dove uses it

**At Dove build time** (once per dove-driver version Dove pins):

1. Download `dove-driver-manifest.json` and `dove-driver-manifest.json.sigstore.json` from the release.
2. Check the signature:
   `cosign verify-blob --bundle dove-driver-manifest.json.sigstore.json --certificate-identity <sigstore.certificate_identity> --certificate-oidc-issuer https://token.actions.githubusercontent.com dove-driver-manifest.json`.
   The identity must be exactly
   `https://github.com/PupppyLoverr/NEXI-Models-Drivers/.github/workflows/dove-driver-release.yml@refs/tags/dove-driver-v<version>`.
3. Commit the manifest into Dove and compile it in. From here on Dove trusts only these hashes; the network copy of
   the manifest is never read at run time.

**When the user clicks Install** (the plugin installer):

1. Pick the platform key: Windows x64 → `windows-x86_64`, Windows ARM64 → `windows-arm64`, any Mac →
   `macos-universal`, Linux x86_64 / aarch64 → `linux-x86_64` / `linux-arm64`. If the key is absent, say the release
   does not support this platform. Refuse if Dove's own version is below `min_dove_version`.
2. Download `url` over HTTPS into a temporary file, stopping once more than `size` bytes arrive. Reject it unless the
   size equals `size` and the SHA-256 equals `sha256`.
3. Extract only after the hash matches. Accept regular files and directories only, all under `root/`, no absolute
   paths, no `..`, no links, and exactly the paths in `files`, each with its listed hash and size. Ignore the
   permissions stored in the archive: on Linux and macOS make a file executable (0755) only when `files` says
   `executable: true`, and everything else 0644. Extract into a new directory, then move it into place, so a failed
   install leaves the old version untouched.
4. Install into Dove's own directory (for example `%LOCALAPPDATA%\Dove\drivers\dove-driver\<version>\`). Before
   each launch, re-hash `entrypoint` (and on Windows `dove-driver-uia.exe`) against `files`.
5. The grounder is offered separately ("Download local grounder, 3.2 MB"). It is verified the same way (size and
   SHA-256), stored next to the driver, and passed to dove-driver by path.

On Windows, `dove-driver-uia.exe` asks for UIAccess. Windows grants it only to an Authenticode-signed binary that is
launched with ShellExecute from a secure location (`\Program Files\` or `\Windows\System32\`), unless an admin sets
`EnableSecureUIAPaths=0`. A per-user install under `%LOCALAPPDATA%` therefore runs the sidecar without UIAccess
(no input into elevated or UWP windows), and an unsigned build never gets it. Dove should report that state rather
than fail.

## Signing

- **Sigstore (all files).** Keyless `cosign sign-blob` from the release job, using the workflow's GitHub OIDC token
  (`id-token: write`). No key or secret. Each file gets `<file>.sigstore.json`; the job verifies every bundle
  against the expected identity before it creates the release.
- **Authenticode (Windows).** `dove-driver.exe` and `dove-driver-uia.exe` are signed and RFC 3161 timestamped, then
  checked with `Get-AuthenticodeSignature` (valid, timestamped, signer CN equals `DOVE_WINDOWS_SIGNER_SUBJECT`).
  Two ways, chosen by `vars.DOVE_WINDOWS_SIGNING`:
  - `azure`: Azure Artifact Signing (formerly Trusted Signing), as upstream uses. GitHub OIDC to Azure, no
    long-lived key.
  - `pfx`: a code-signing certificate exported as PFX, signed with `signtool`.
  - `none` (the default): archives are built unsigned and the release job refuses them unless
    `vars.DOVE_ALLOW_UNSIGNED_WINDOWS` is `true`.
- **Notarization (macOS).** Gated off. The macOS job always builds and lipo's the universal binary, but signs,
  assembles `DoveDriver.app`, notarizes (App Store Connect API key) and staples only when
  `vars.DOVE_MACOS_SIGNING` is `enabled`. Even then it refuses unless R0.3 has landed:
  `rust/scripts/DoveDriverBundle/Contents/Info.plist` with a bundle id that is not `com.trycua.*`, and
  `rust/scripts/DoveDriver.entitlements`. Until then the macOS archive is uploaded as a workflow artifact named
  `dove-driver-unsigned-macos-universal` for testing and is not part of the release.

### Secrets and settings to configure

Create two environments in NEXI-Models-Drivers (Settings → Environments):

- `dove-driver-signing`: holds the signing secrets below. Deployment rule: tags matching `dove-driver-v*` only, so
  no branch build can use them. Manual (`workflow_dispatch`) runs never use this environment and build unsigned.
- `dove-driver-release`: required reviewer = the release owner. The release job waits here for approval, and then
  only creates a **draft** release.

Windows, `azure` route (environment `dove-driver-signing`):

| Kind | Name | Value |
| --- | --- | --- |
| secret | `AZURE_CLIENT_ID` | App registration (client) id with a federated credential whose subject is `repo:PupppyLoverr/NEXI-Models-Drivers:environment:dove-driver-signing`, and Artifact Signing's "Certificate Profile Signer" role on the certificate profile |
| secret | `AZURE_TENANT_ID` | Azure tenant id |
| secret | `AZURE_SUBSCRIPTION_ID` | Subscription holding the Artifact Signing account |
| variable | `AZURE_ARTIFACT_SIGNING_ENDPOINT` | e.g. `https://eus.codesigning.azure.net/` |
| variable | `AZURE_ARTIFACT_SIGNING_ACCOUNT_NAME` | Artifact Signing account name |
| variable | `AZURE_ARTIFACT_SIGNING_CERTIFICATE_PROFILE_NAME` | Certificate profile name |

Windows, `pfx` route (environment `dove-driver-signing`):

| Kind | Name | Value |
| --- | --- | --- |
| secret | `WINDOWS_CODESIGN_PFX_BASE64` | Base64 of the code-signing certificate and key (PFX) |
| secret | `WINDOWS_CODESIGN_PFX_PASSWORD` | Its password |
| variable | `WINDOWS_TIMESTAMP_URL` | Optional; default `http://timestamp.digicert.com` |

Repository variables (Settings → Secrets and variables → Actions → Variables). These must be repository
variables, not environment variables: the release job runs in `dove-driver-release` and reads them too.

| Kind | Name | Value |
| --- | --- | --- |
| variable | `DOVE_WINDOWS_SIGNING` | `azure`, `pfx` or `none` |
| variable | `DOVE_WINDOWS_SIGNER_SUBJECT` | Expected signer CN, exactly as on the certificate |
| variable | `DOVE_ALLOW_UNSIGNED_WINDOWS` | `true` only to release unsigned Windows archives on purpose |
| variable | `DOVE_MACOS_SIGNING` | `enabled` to turn on signing and include macOS in the release. Leave unset until R0.3. |

macOS (environment `dove-driver-signing`; only after R0.3):

| Kind | Name | Value |
| --- | --- | --- |
| secret | `APPLE_DEVELOPER_ID_CERT_P12_BASE64` | Base64 of the "Developer ID Application" certificate and key (.p12) |
| secret | `APPLE_DEVELOPER_ID_CERT_PASSWORD` | Its password |
| secret | `APPLE_DEVELOPER_NAME` | The name in the identity, `Developer ID Application: <name> (<team>)` |
| secret | `APPLE_TEAM_ID` | 10-character team id |
| secret | `APPLE_NOTARY_API_KEY_P8_BASE64` | Base64 of an App Store Connect API key (.p8) with the Developer role |
| secret | `APPLE_NOTARY_API_KEY_ID` | Its key id |
| secret | `APPLE_NOTARY_API_ISSUER_ID` | Its issuer id |
| secret | `DOVE_DRIVER_PROVISIONING_PROFILE_BASE64` | Optional; only if R0.3's entitlements need a provisioning profile |

Sigstore and the release itself need no secret: the workflow's `GITHUB_TOKEN` (`contents: write`) creates the draft,
and its OIDC token (`id-token: write`) signs.

## Cutting a release

1. `rust/VERSION` holds the version (it follows upstream through `scripts/dove/sync-upstream.sh`).
   `bash scripts/dove/parity-check.sh` passes on `main`.
2. Publish the folder: `scripts/dove/publish-folder.sh` (pushes `dove-driver/main`, refreshes `dove-driver/` and the
   root workflow in NEXI-Models-Drivers `main`).
3. Optional: run the workflow by hand (Actions → "Release: dove-driver" → Run workflow). It builds and verifies every
   platform and uploads the archives as artifacts; it releases nothing.
4. Tag that NEXI-Models-Drivers `main` commit `dove-driver-v<version>` and push the tag.
5. The workflow checks that the tag matches `rust/VERSION`, that `dove-driver/` is exactly a `dove-driver/main`
   commit and that the commit passes the parity check, builds and signs everything, then waits for approval on
   `dove-driver-release`.
6. After approval it writes and verifies the manifest, signs every file with Sigstore and creates a **draft**
   release. Review the draft and publish it by hand.
7. In Dove, vendor the new `dove-driver-manifest.json` as described above.

## Checking locally (dry run)

From the fork root, with a build in `rust/target/release` (on Linux, `--platform linux-x86_64` and a build with
`--features cua-driver/portal-input`):

```bash
python scripts/dove/release/package.py --platform windows-x86_64 --version "$(cat rust/VERSION)" --bin-dir rust/target/release --out-dir /tmp/dd-release
python scripts/dove/release/build_manifest.py --assets-dir /tmp/dd-release --commit "$(git rev-parse HEAD)" --require windows-x86_64 --out /tmp/dd-release/dove-driver-manifest.json
python scripts/dove/release/verify_manifest.py /tmp/dd-release/dove-driver-manifest.json --assets-dir /tmp/dd-release
```

Add `--schema` to the last command to validate against the JSON Schema as well, and run
`python scripts/dove/release/test_manifest.py` after changing any of these scripts (both need
`pip install jsonschema==4.23.0`).

Dry runs so far: Windows x86_64 (local build); Linux x86_64 and arm64 (built in an Ubuntu 20.04 container, glibc
2.31 like the release's Debian 11; arm64 cross-compiled), packaged and checked with `--schema` into one manifest.

## Differences from upstream's release

Ported from trycua's `cd-rust-cua-driver.yml` and `cua-driver-release-signatures.yml` (at `cua-driver-rs-v0.37.0`).
Kept: the Windows matrix (x86_64 and arm64 cross-built on `windows-latest`), the Debian 11 Linux build with
`portal-input`, the universal macOS build with hardened-runtime signing, notarization and stapling, Authenticode
verification with a pinned signer, and keyless Sigstore bundles. Dropped: the SDK, Node runtime and cursor-theme
binaries, the Hyprland plugin source, the install scripts, skill packs, Release Please and attribution. Dove
installs the driver itself. Added: the parity and fork-tree check before any build, the manifest, approval and a
draft-only release, no build cache on release builds, and the Spectre-libs check on Windows (R0.5).
