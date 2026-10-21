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
adds on top must be new files or new code paths that leave upstream behaviour unchanged. The one deliberate
exception is `0005-observation.patch`, which changes `get_window_state` defaults. Its entry below lists each change.
Upstream's screenshot on every read and its PNG encoding stay one argument away (`include_screenshot:true` or
`start_session {vision:true}`, and `screenshot_format:"png"`).

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
- `0003-local-grounder.patch`. The Local Grounder (ROADMAP W9), which is off unless its weights are installed
  (`DOVE_DRIVER_GROUNDER_MODEL`):
  - `cua-driver-core` depends on the Dove-only crate `rust/crates/dove-grounder`, which joins the workspace;
  - new `cua-driver-core/src/grounder_tools.rs`: the `act {pid, window_id, intent}` tool, registered only when the
    weights exist, with the reviewed risk class, recording exclusion and origin-bypass entry `run_steps` has;
  - `run_steps` accepts a `{"intent": ...}` step (refused before anything runs when the grounder is off), and its
    description mentions it only when the grounder is on. Batches without intent steps behave as upstream.
- `0004-lazy-tool-disclosure.patch` (ROADMAP W5). With `DOVE_TOOL_DISCLOSURE=lazy` (or `DOVE_DRIVER_`/`CUA_DRIVER_TOOL_DISCLOSURE`),
  `tools/list` keeps full input schemas only for `list_windows`, `get_window_state`, `run_steps`, `verify_state`,
  `act` and the new `describe_tools {names}`, and lists every other tool with a one-line description and
  `{"type":"object"}`. Withheld tools still run, and a bad-arguments error carries the tool's schema. Measured on
  Linux: 31,789 bytes instead of 229,910. Default (unset) behaviour is upstream's.
- `0005-observation.patch` (ROADMAP W1.2-W1.4). Tree-first, screenshot-optional observation. This is the one patch
  that deliberately changes an upstream default. The per-session `since:"latest"` and `start_session {vision}` are
  in `cua-driver-core` and apply on every OS. The screenshot policy, JPEG, `marks` and the kept screenshot frame are
  wired on Windows and Linux only; macOS `get_window_state` still returns a PNG on every read, as upstream.
  - **No screenshot by default.** A read returns the tree and no image. A screenshot comes only with
    `include_screenshot:true`, `marks:true`, `screenshot_out_file`, a screenshot-only read
    (`include_accessibility_tree:false`), a session started with `start_session {vision:true}`, or a tree with fewer
    than 5 actionable elements (canvas, games, remote desktop). `screenshot_reason` says which (`requested`,
    `marks`, `vision_session`, `no_tree`, `sparse_tree`), and a tree-first read without one carries
    `screenshot_omitted`. `include_screenshot:false` still wins over everything except `screenshot_out_file`,
    as upstream. Upstream returned a screenshot on every read unless `include_screenshot:false`.
  - **JPEG by default.** The embedded image is JPEG (quality 80) with `screenshot_mime_type: "image/jpeg"`;
    `screenshot_format:"png"` restores PNG. Screenshots stay window-scoped and downscaled as upstream (at or below
    1.15 megapixels unless `max_image_dimension` says otherwise), so pixel coordinates are unchanged.
    `screenshot_out_file` still writes PNG. The capture registered for `capture_id` (pixel actions, perception) is
    the clean PNG at the same size, so its content digest is the PNG's, not the delivered JPEG's.
  - **`marks:true`** (new) returns a screenshot with each row's index `N` drawn at its element frame
    (`screenshot_frame`), so a vision model acts by `element_token` `<snapshot_id>:N`. `marks` in the structured
    output counts the drawn labels. Elements without a frame, and frames covering half the image or more (the
    window itself), get no label.
  - **`start_session {vision}`** (new, boolean). `vision:true` makes every read in that session include a
    screenshot (unless `include_screenshot:false`), and the response carries `vision: true`. `vision:false`
    clears it, omitting it keeps it, and it ends with the session.
  - **`since:"latest"` is per session.** It resolves to the calling session's last read of that window with the
    same `query`/`max_elements`/`max_depth`. The session is the `session` label, else the transport's implicit
    session. A session that has not read the window gets a full read with `since_status: "no_baseline"`. A call
    with no session keeps upstream's per-window latest. Upstream resolved `latest` across all callers, so one
    agent could diff against what another had seen.
  - **Tree-first reads keep the screenshot frame.** A read without a screenshot keeps the session's last
    screenshot frame while the window keeps its size, as upstream macOS already did, so x/y taken from that
    screenshot still work. Upstream Windows and Linux retired the frame on every tree-only read, and the next
    pixel action was refused until a new screenshot was taken.
  - The typed contract (`GetWindowStateInput`, SDK, generated bindings) does not carry `marks` or
    `screenshot_format` yet; they are inputs of the live tool schemas only. Typed SDK reads now get no screenshot
    unless they pass `include_screenshot:true`.
- `0006-batching.patch` (ROADMAP W3). `run_steps` gains `wait_for {query, gone, timeout}` and `expect` steps (verify_state
  predicates), plus Playwright-style auto-wait before actions on named targets: the target exists, is enabled, has
  a non-zero frame and the same frame across two reads, within the step's timeout. On timeout the step fails with
  `not_actionable` and the reason. `auto_wait:false` turns it off for a step or a batch.
- `0007-actions-and-safety.patch` (ROADMAP W2 and W6):
  - every action result names its exact mechanism as `via` (for example `uia_invoke`) and a `change` of
    `changed`, `unchanged` or `unverifiable`. On Windows the change comes from a before/after comparison of the
    target element's value and the target window's UIA tree and top-level windows; a click, key or scroll that
    changed the window is `effect: confirmed` with `window_change` evidence, and a `set_value` that reads back the
    requested value is `confirmed` with `value_readback` evidence. `set_value` also sets check boxes, radio
    buttons, list items and UIA combo boxes through Toggle, SelectionItem and ExpandCollapse;
  - text is never typed into a password or payment-card field (UIA `IsPassword`, `AXSecureTextField`, AT-SPI
    `password text`, `input[type=password]`, `autocomplete="cc-*"`), and no action targets a UAC prompt, the secure
    desktop or an OS credential dialog. Such calls are refused with `code: "handoff_required"` in every mode;
  - the confirm and block classes of nexi-cua (see below) are checked against the target element and the call's
    optional `intent`. Blocked: refused. Confirm: refused with a `confirm_token` in `standard` mode, refused in
    `bounded` mode, run in `unrestricted` mode. `DOVE_DRIVER_SAFETY_CLASSES=off` turns the classes off.
- `0008-speed.patch` (ROADMAP W4). Same results, less time per call:
  - tool-call admission looks the tool name up instead of copying the whole `tools/list` (lazy disclosure keeps
    `describe_tools` and withheld tools callable, and builds the full list only for `describe_tools` and for the
    schema hint on bad arguments);
  - Windows `get_window_state` makes one process-name query, shares one `IUIAutomation`, and starts the capture
    beside the UIA walk when a screenshot is certain before the walk (requested, `screenshot_out_file`, `marks`, a
    vision session). A tree-first read still walks first and captures only if the tree is sparse. The UIA
    CacheRequest fetches `Is*PatternAvailable` properties instead of pattern objects;
  - an event-driven tree cache on all three OSes, off unless `DOVE_TREE_CACHE=1`; concurrent read-only calls on the
    direct stdio transport (Windows default, `DOVE_PARALLEL_READS`); stage timers under `CUA_LOG=dove_perf=debug`;
    and the `cua-driver-e2e/tests/latency_test.rs` latency gate.

## nexi-cua (Apache-2.0)

`rust/crates/dove-grounder` (the Local Grounder, ROADMAP W9) is a Rust port of the decision policy of **nexi-cua
v0.4.0**, `nexi-cua/` in this repository's `main` branch (commit `fa3c797`), licensed under the Apache License,
Version 2.0. The full license text is in [LICENSES/nexi-cua-Apache-2.0.txt](LICENSES/nexi-cua-Apache-2.0.txt).
nexi-cua ships no NOTICE file of its own.

- Ported, with changes for Rust: `nexi_cua/policy/resolver.py`, `features.py`, `infer.py` (decision, calibrated
  abstention, margin rescue, argument resolution), `intents.py`, the network of `model.py`, and the types and
  candidate enumeration of `types.py` and `actions.py`. Each source file names the Python file it ports.
- `dove-grounder/tests/goldens/` holds observations and labels from nexi-cua's eval fixtures and synthetic
  generator, with the decisions nexi-cua itself made on them.
- The NEXI-CUA-1 weights are not in this repository. `dove-grounder/scripts/export_onnx.py` converts nexi-cua's
  `weights/nexi-cua-1.pt` into the optional asset the driver loads (`DOVE_DRIVER_GROUNDER_MODEL`); that asset is
  a derivative of the nexi-cua weights and is distributed under Apache-2.0 with this notice.

- `rust/crates/cua-driver-core/src/dove_safety.rs` ports the confirm and block classes of `nexi_cua/safety.py` from
  [PupppyLoverr/NEXI-Models-Drivers](https://github.com/PupppyLoverr/NEXI-Models-Drivers) (`nexi-cua/`), licensed
  under the Apache License 2.0 (https://www.apache.org/licenses/LICENSE-2.0). Changes: the Python regular
  expressions are rewritten as Rust word and phrase matching, `exfiltrat`, `keylog`, `phish` and `ransom` also match
  their inflections, and the classes are applied to the target element and an `intent` argument rather than to
  nexi-cua's `Action` record.

The rest of dove-driver stays under upstream's MIT license.

Still upstream's: internal crate names (`cua-driver-core` and the rest), `CUA_DRIVER_*` variable names (now with
`DOVE_DRIVER_*` aliases), protocol identifiers (history schema URNs, the policy `server` name, telemetry event
names), the bundled skill pack (`cua-driver`), and the macOS app identity (`CuaDriver.app`, `com.trycua.driver`),
which is work item R0.3 in [ROADMAP.md](ROADMAP.md). Network use that only happens on an explicit request is
unchanged: `skills install` downloads upstream's skill pack, `install_ffmpeg` downloads ffmpeg, and
`install_extension` needs a catalog the operator names.
