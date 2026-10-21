# dove-driver roadmap

dove-driver is the engine behind **Dove Computer Use**, an installable Dove plugin. The goal is the best open
computer-use driver: tree-first, screenshot-optional and token-efficient, with background control on macOS,
Windows and Linux. This file turns the eight "What makes it #1" points of the Dove plan (§11) into work items mapped
to source files, followed by the benchmark plan.

Paths are relative to `rust/crates/` unless they start with `/`. "Upstream" means `trycua/cua` `libs/cua-driver`.

## Rule: never behind upstream

dove-driver must do everything upstream cua-driver does. `main` is always the latest upstream release plus Dove's
changes: the rebrand transforms and the feature patches in `scripts/dove/patches/`, all applied by
`scripts/dove/apply-dove-changes.sh`. `scripts/dove/parity-check.sh` enforces this, and
`scripts/dove/sync-upstream.sh <tag>` takes each new upstream release (see NOTICE.md). Take every upstream release
within a week. A Dove change that upstream would accept goes upstream as a PR, and is dropped from the patch queue
once it lands.

## Where we start

- Base: upstream `cua-driver-rs-v0.37.0` (`2d2f992`, 2026-10-20), with `cua-perception` removed (see NOTICE.md).
  The first import was v0.34.0; R0.1 moved the base.
- From upstream 0.35–0.37, now in the fork: `get_window_state since:<snapshot_id>` row diffs (CUA-1193), lean
  default output (compact markdown, at most 250 nodes, `full_output: true` for the old shape), `run_steps` (formerly
  `run_actions`) with find, wait and check steps (CUA-1194) and a nudge to batch, `run_script` (sandboxed QuickJS),
  `browser_select`, `get_guide`, recovery hints on refusals and unverifiable results, and locked-screen reporting.
  Code: `cua-driver-core/src/batch_tools.rs`, `batch_nudge.rs`, `step_pacing.rs`, `script_tool.rs`.
- From 0.34.0 and earlier: element tokens (`cua-driver-core/src/element_token.rs`), `get_window_state` with `query`,
  `max_elements`, `max_depth`, `include_screenshot`, `max_image_dimension` and a walk budget
  (`cua-driver-contract/src/windows.rs`, `cua-driver-core/src/walk_budget.rs`), `verify_state`
  (`cua-driver-contract/src/verification.rs`, `cua-driver-core/src/expectation.rs`), action effects
  (`cua-driver-core/src/action_record.rs`), delivery modes (`cua-driver-core/src/delivery.rs`,
  `background_input.rs`) and the standard/bounded permission modes (`cua-driver-core/src/authorization.rs`).
- **Not upstream at all:** lazy tool disclosure (`describe_tools`, `DOVE_TOOL_DISCLOSURE=lazy`) and per-result token
  usage metadata (`ai.dove/token-usage`, `DOVE_USAGE_TOKENS=1`). Both exist only in the prebuilt
  `dove-driver 0.34.0` Windows binary, whose source was not found (see "Provenance" below).
  These are rebuilt here as W5 and as part of W8.

## R0. Foundation (before any feature work)

| # | Work item | Files | Done when |
|---|---|---|---|
| R0.1 | **Done (2026-10-20):** base moved to `cua-driver-rs-v0.37.0` with `scripts/dove/sync-upstream.sh`. Remaining: run the full Windows test suite on the new base, and add a weekly CI job that runs `sync-upstream.sh` on the newest upstream tag and opens a PR. | `/scripts/dove/`, `/.github/workflows/` (new) | a new upstream release reaches `main` through a reviewed PR without hand edits |
| R0.2 | **Done on Windows (2026-10-20), patch `0001-own-state-and-identity.patch`:** own state namespace, home dir, daemon and uiAccess pipes, Unix socket, credential-store entries, browser-profile, cursor-theme and libei dirs, SDK default namespace, `serverInfo`/`--version`, and `DOVE_DRIVER_*` env aliases (see NOTICE.md). **Linux verified (2026-10-20, Ubuntu 24.04):** builds, and `ci/dove/side_by_side.py` passes all 30 checks against a stock `cua-driver` built from `dove-driver/upstream`. One Linux-only upstream test fails under patches 0001/0002 (`release_channel_cli_test` `pacman::fake_path_pacman_cannot_disable_unmanaged_channel_switching`: it seeds `~/.cua-driver/version_check.json` and expects an update check). Remaining: macOS (the W7 workflow runs the same test there, not yet run), that test, and decide whether Dove ships its own skill pack instead of upstream's `cua-driver` pack (see §11 `dove-computer`). | `cua-driver/src/bundle.rs`, `dove_env.rs`; the files in the patch | dove-driver and cua-driver run side by side with separate state on all three OSes, and an e2e test proves it |
| R0.3 | **macOS identity.** `DoveDriver.app`, bundle id under Dove's Apple team, entitlements, TCC strings. This needs Dove's Developer ID. | `cua-driver/src/bundle.rs`, `/rust/scripts/CuaDriverBundle`, `/rust/scripts/CuaDriver.entitlements`, `platform-macos/src/tools/check_permissions.rs` | a signed, notarized app gets AX and Screen Recording grants under its own identity |
| R0.4 | **Done (2026-10-20), patch `0002-no-upstream-phone-home.patch`:** telemetry off by default and sent only to `CUA_DRIVER_TELEMETRY_URL` (no default, PostHog removed); no trycua release lookups and no Cua installer runs. Verified: a `serve` process has no TCP or UDP connections. Remaining: a CI test that runs the daemon under a network sandbox and fails on any outbound connection. | `cua-driver/src/telemetry.rs`, `version_check.rs`, `updater.rs`, `dove_env.rs` | no network request leaves the driver unless Dove asks for one, checked in CI |
| R0.5 | **Windows build prerequisite.** `regorus` turns on `msvc_spectre_libs` with `error`, so a build fails without the VS "MSVC Spectre-mitigated libs" component. Install it on dev machines and CI, and document it in README. | `/README.md`, CI images | a clean Windows box builds with the documented steps |
| R0.6 | **Release pipeline.** Signed release assets per OS/arch on `PupppyLoverr/NEXI-Models-Drivers` releases, tagged `dove-driver-v<version>`, plus a SHA-256 manifest that Dove compiles in, Authenticode on Windows and notarization on macOS. Port from upstream `.github/workflows/cd-rust-cua-driver.yml` and `cua-driver-release-signatures.yml`. GitHub only runs workflows from the repository root, so they go in NEXI-Models-Drivers' `.github/workflows/` with `working-directory: dove-driver`. | NEXI-Models-Drivers `/.github/workflows/` (new), `/scripts/` | Dove's Install button can fetch and verify a tagged release |

## W1. Tree-first, screenshot-optional observation

**Goal:** the default observation is a pruned tree of interactive and labelled nodes, one compact row per node
(`[N] role "name" value state`), each row carrying an element token. Screenshots appear only when asked for, when
the surface has no tree, or when the session declares vision.

| # | Work item | Files |
|---|---|---|
| W1.1 | Lean output by default: compact rows, a node cap, `full_output` opt-in, already in the base. Next, tune pruning: drop unlabelled containers, collapse single-child chains, merge static text into its labelled parent. | `cua-driver-core/src/window_inspection.rs` (tree markdown), `walk_budget.rs`; `platform-windows/src/uia/snapshot.rs`; `platform-macos/src/ax/tree.rs`, `ax/snapshot.rs`; `platform-linux/src/atspi/snapshot.rs`, `snapshot_queries.rs` |
| W1.2 | `since:"latest"` as well as `since:<snapshot_id>`: diff against the session's last snapshot of that window, and return `no change` when nothing changed. | `cua-driver-core/src/snapshot_store.rs`, `element_token.rs`, `session.rs`; `cua-driver-contract/src/windows.rs` |
| W1.3 | Screenshot policy: window-scoped, downscaled, JPEG by default, returned only when (a) `include_screenshot: true`, (b) the tree is empty or below a node threshold (canvas, games, remote desktop), or (c) the session opened with `start_session {vision: true}`. Tokens stay valid when the tree is skipped. | `cua-driver-core/src/image_utils.rs` (`png_bytes_to_jpeg`, `resize_png_if_needed`), `capture_mode.rs`, `capture_scope.rs`, `session.rs`, `session_tools.rs`; `platform-windows/src/capture.rs`, `wgc.rs`; `platform-macos/src/capture.rs`; `platform-linux/src/capture.rs` |
| W1.4 | Set-of-marks mode: draw each row's `[N]` on the screenshot at its element frame, so a vision model clicks by token instead of by pixel. | `cua-driver-core/src/image_utils.rs` (next to `crosshair_png_bytes`), `element_frame.rs`; a `marks: true` input in `cua-driver-contract/src/windows.rs` |

**Done when:** on the W8 task set, median observation tokens per step drop at least 10× against a screenshot-only
baseline at equal or better success rate, and a `since:"latest"` re-read after a small change is under 15% of a
full read.

**Status (2026-10-20), patch `0005-observation.patch`:** W1.2, W1.3 and W1.4 are built and wired on Windows and
Linux (behaviour changes in NOTICE.md). On macOS only the per-session `since:"latest"` applies, because it lives in
`cua-driver-core`. Its `get_window_state` still returns a PNG on every read, and wiring it is not started. `marks` and
`screenshot_format` are not in the typed contract (`cua-driver-contract/src/windows.rs`, the SDK and the generated
bindings) yet. W1.1 pruning is not started.

Measured on Linux (Ubuntu 24.04, Xvfb 1280x1024, AT-SPI 2.52, the GTK3 harness `/tests/fixtures/apps/linux/gtk3`,
a 560x720 window with 18 element rows, debug build). The small change is a click on `btn-increment`, which turns
`counter=0` into `counter=1`. Sizes are bytes of the MCP result's text parts and of the whole JSON-RPC result.

| Read | Text | Whole result | Image |
|---|---|---|---|
| Full read, W1 default (tree-first) | 3,730 | 8,405 | none |
| `since:"latest"`, nothing changed | 257 (6.9%) | 1,093 (13.0%) | none |
| `since:"latest"` after the click | 303 (8.1%) | 1,186 (14.1%) | none |
| `include_screenshot:true` | 3,795 | 69,747 | JPEG, 61 KB base64 |
| `include_screenshot:true, screenshot_format:"png"` | 3,795 | 118,689 | PNG, 110 KB base64 |
| `marks:true` (14 labels) | 3,795 | 116,638 | JPEG, 108 KB base64 |
| Canvas window (no actionable rows), W1 default | 170 | 7,078 | JPEG, `screenshot_reason: "sparse_tree"` |
| Same full read before W1 (fork tip `a41d24f`) | 3,730 | 119,450 | PNG on every read |
| `since:"latest"` after the click before W1 | 303 | 111,319 | PNG on every read |

The re-read after a small change is 8.1% of a full read in text and 14.1% in whole-result bytes, which meets the
15% target. Most of the remaining whole-result bytes are fixed metadata in `structuredContent` (`frame_note` and
window identity). Also checked on Linux: `since:"latest"` from another session gets `no_baseline`; a
`start_session {vision:true}` session's read gets a JPEG without asking, and `include_screenshot:false` opts a read out;
element tokens from a `marks` read click the right control; and an x/y click after a tree-first re-read is accepted
(before W1 it was refused). Windows builds and type-checks for `x86_64-pc-windows-gnu`, tests included, but has not
run.

Pending on the Windows PC:

- `cargo test -p cua-driver-core -p platform-windows` on Windows (the new `dove_observation` tests run on every OS
  and pass on Linux).
- The same measurements on Windows against the WPF/WinUI3 harness: full read, `since:"latest"` unchanged and
  after a small change (target under 15%), `include_screenshot:true` JPEG against PNG, `marks:true` labels drawn on
  the right controls, a vision session, and a sparse-tree window (a canvas or game) bringing its own screenshot.
- An x/y click after a tree-first re-read, and a token click after a `marks` read.
- The W8 token comparison against a screenshot-only baseline (the 10× target); that needs the W8 harness.

## W2. Semantic actions first

**Goal:** act through accessibility patterns before synthetic input, and say exactly what happened.

| # | Work item | Files |
|---|---|---|
| W2.1 | Route `click`, `set_value`, `select`, `toggle`, `expand` and scroll-into-view through UIA patterns (Invoke, Value, SelectionItem, Toggle, ExpandCollapse, ScrollItem), AX actions (`AXPress`, `AXValue`, `AXShowMenu`) and AT-SPI Action/EditableText before falling back to background synthetic input, and to foreground input only when refused. Report the route used in every result. | `platform-windows/src/tools/impl_.rs`, `uia/mod.rs`, `uia/scroll.rs`, `msaa.rs`, `input/`; `platform-macos/src/tools/click.rs`, `set_value.rs`, `background_mutation.rs`; `platform-linux/src/tools/impl_.rs`, `atspi/native.rs`; `cua-driver-core/src/delivery.rs`, `background_input.rs` |
| W2.2 | Every action returns `effect: changed / unchanged / unverifiable` plus the tree diff of the target window (reusing W1.2). Treat `unverifiable` as not success. | `cua-driver-core/src/action_record.rs`, `mcp_result.rs`; `cua-driver-contract/src/outputs.rs` |
| W2.3 | A first-class `select` and `toggle` tool (or `set_value` modes) with readback, so models stop clicking combo boxes open and shut. | `cua-driver-contract/src/inputs.rs`; per-platform tool impls |

**Done when:** at least 80% of W8 actions on tree-backed apps complete without synthetic input, and each result
names its delivery route and effect.

## W3. Batching

**Goal:** one round trip for a whole sub-flow.

| # | Work item | Files |
|---|---|---|
| W3.1 | `run_steps` with early stop and an `observe` diff: already in the base. Measure it in W8. | `cua-driver-core/src/batch_tools.rs` (from upstream) |
| W3.2 | **Done on Linux (2026-10-20), patch `0006-batching.patch`; Windows checks pending.** `wait_for {query, gone, timeout}` and assertion steps (`expect` reusing `verify_state` predicates) inside `run_steps`, with Playwright-style auto-wait before each action: target exists, enabled, on screen and stable. Code in `batch_tools/waits.rs`, reached from small hooks in `batch_tools.rs`. Also: a bare string or `query` check, a disabled control shown as an unindexed `(disabled)` row (AT-SPI) is waited on as disabled, and the end `observe` falls back to the app's frontmost window when the last-used window closed. Cost: a ready named target takes one extra read (W8 should measure it; `auto_wait:false` turns it off). Verified: unit and fake-app flow tests, and `scripts/dove/live-tests/w3/run-linux.sh` (Xvfb, AT-SPI, openbox, GTK3 app with delayed controls): the open-dialog, fill-three-fields, submit, check flow is one call with the end diff showing the result. Pending on Windows: run `w3live.py` (WinForms app `w3form.ps1`); check that a disabled WinForms button reports `enabled:false` with an index (so auto-wait says `disabled`), that the sliding Submit is held until it stops, that `set_value` on the late-enabled fields waits, that the end observe falls back to the main window after Submit closes the dialog, and the round-trip times in a release build. | `batch_tools.rs`, `cua-driver-core/src/expectation.rs` (`evaluate_predicates`), `element_query.rs` |
| W3.3 | Decide `run_script` (QuickJS): keep it on for loops and branches, keep it off in `bounded` mode, and cover it with the W6 policy. | `cua-driver-core/src/script_tool.rs` (from upstream), `authorization.rs` |

**Done when:** a typical "open dialog, fill three fields, submit, check result" flow is one `run_steps` call,
and W8 reports round trips per task.

## W4. Speed

**Goal:** p50 under 40 ms for `get_window_state` with a `query` on a typical app; p95 under 150 ms.

| # | Work item | Files |
|---|---|---|
| W4.1 | Keep one daemon per user session, warm across MCP clients; the MCP stdio process proxies to it. Measure cold and warm start. | `cua-driver/src/serve.rs`, `proxy.rs`, `cua-driver-core/src/daemon.rs` |
| W4.2 | Cache tree walkers per window and invalidate them on events: UIA `StructureChanged`, `PropertyChanged` and focus events, macOS `AXObserver` notifications, AT-SPI `object:children-changed` / `state-changed`. Re-walk only the dirty subtree. Upstream (as of 0.37.0) subscribes to none of these. | `platform-windows/src/uia/mod.rs`, `uia/snapshot.rs`; `platform-macos/src/window_change_detector.rs`, `ax/`; `platform-linux/src/atspi/mod.rs`; `cua-driver-core/src/snapshot_store.rs` |
| W4.3 | Use a UIA `CacheRequest` with only the properties the rows need, so one cross-process call replaces a call per property. | `platform-windows/src/uia/snapshot.rs` |
| W4.4 | Snapshot several windows in parallel for `get_desktop_state` and multi-window flows. | `cua-driver-core/src/window_observation.rs`; per-platform `get_desktop_state` |
| W4.5 | Latency harness: p50/p95 per tool per fixture app, run in CI, failing on a regression above 20%. Start from upstream's `ci-cua-driver-bench.yml` and `cua-driver-core/tests/recording_turn_latency.rs`. | `cua-driver-e2e/tests/` (new `latency_test.rs`), `/.github/workflows/` |

**Status (patch 0008, 2026-10-21).** Windows verified locally; macOS and Linux code is unverified until W7 CI.
- Per-call overhead removed: the MCP layer cloned the 236 KB `tools/list` twice per call (now a name lookup);
  `get_window_state` took two full process snapshots (now one image-name query); capture now overlaps the walk;
  one shared `IUIAutomation`. Merged with W1's tree-first policy, the capture overlaps the walk only when a
  screenshot is certain beforehand (requested, out file, marks, vision session); otherwise the walk goes first and
  the capture runs only for a sparse tree. On a WinForms fixture, a query read without a screenshot went from p50 199 ms to
  23.6 ms (cache off) on a quiet machine, and the MCP floor (`get_screen_size`) from 8.1 to 2.2 ms. Walk time on
  that fixture swings 30-300 ms with machine load, which no change here controls.
- W4.3: the CacheRequest fetches `Is*PatternAvailable` properties instead of pattern objects and drops the unread
  `IsOffscreen`. No measurable effect on WinForms (noise dominates); native providers were not measured.
- W4.2: event-driven cache with dirty-subtree re-walk, built on all three OSes, **off by default**
  (`DOVE_TREE_CACHE=1`). Rows it returns are re-read live on Windows, but a row the app adds appears only once its
  UIA event arrives (350-880 ms on WinForms), so it is not safe as a default. Windows hits: p50 3-33 ms.
- W4.4: concurrent read-only calls on the direct stdio transport (Windows default; `DOVE_PARALLEL_READS`). Calls in
  one session are still serialized by session dispatch; two windows in separate sessions: 65 to 51 ms.
- W4.5: `cua-driver-e2e/tests/latency_test.rs` gates the default query read (p50 < 40 ms, p95 < 150 ms, +20%
  regression). W7 should run it on a quiet runner and feed results back as the baseline.
- Follow-ups: per-window capture (PrintWindow + PNG) costs 30-45 ms on screenshot reads; `list_windows` costs
  200-500 ms; the cache needs a sound way to see new rows before it can default on.

## W5. Lazy tool disclosure

**Goal:** a harness sees a tiny tool list until it needs more.

| # | Work item | Files |
|---|---|---|
| W5.1 | `DOVE_TOOL_DISCLOSURE=lazy`: `tools/list` returns full schemas for `list_windows`, `get_window_state`, `run_steps`, `verify_state` and `describe_tools` only, and names plus one-line descriptions for the rest. | `cua-driver-core/src/server.rs` (`tools_list`), `tool.rs`, `tool_schema.rs`, `mcp_wire.rs`; `cua-driver/src/serve.rs`, `mcp_envelope.rs` |
| W5.2 | `describe_tools {names: [...]}` returns full input schemas on demand. Calling a tool whose schema was withheld still works, and a bad call returns the schema in the error. | `cua-driver-core/src/tool.rs`; each platform's `tools/mod.rs` (`build_registry`) |
| W5.3 | MCP server instructions (the "efficient loop") and the bundled `dove-computer` skill describe the lazy flow. | `cua-driver-core/src/mcp_skills.rs`, `/rust/Skills/` |

**Done when:** the `tools/list` payload in lazy mode stays under 33 KB (`LAZY_TOOLS_LIST_LIMIT_BYTES` in
`tool_disclosure_test.rs`: 31,789 bytes measured on Linux plus a small margin, against 229,910 bytes eager), and W8
shows no success-rate loss against eager mode. The 3 KB first planned is not reachable because every tool must stay
listed, with a one-line description, so that clients such as Claude Code, which only call listed tools, can still
call all of them: 59 bare name-only entries already take 3.4 KB (user decision 2026-10-20, option A). About 22 KB of
the lazy list is the five full entries; most of that is the long usage descriptions of `get_window_state` and
`run_steps`, which lazy mode keeps. Windows size still to be measured.

## W6. Safety

| # | Work item | Files |
|---|---|---|
| W6.1 | Keep the `standard` / `bounded` permission modes. Dove sets the mode at launch. | `cua-driver-core/src/authorization.rs`, `session_authorization.rs`, `policy.rs` |
| W6.2 | Never type into password or secure fields: UIA `IsPassword`, `AXSecureTextField`, AT-SPI `ROLE_PASSWORD_TEXT`, browser `input[type=password]`. Refuse with a typed error that tells the model to hand off. In upstream 0.37.0 the only guard is on Linux, where `atspi/native.rs` hides a password field's text. No platform refuses typing into one. | `platform-windows/src/tools/impl_.rs`, `uia/snapshot.rs`; `platform-macos/src/tools/type_text.rs`, `set_value.rs`; `platform-linux/src/tools/impl_.rs`; `cua-driver-core/src/browser/` |
| W6.3 | Stop and hand off at UAC prompts (secure desktop, `consent.exe`), OS credential dialogs, and payment fields (`autocomplete=cc-*`, known payment frames). Report it as `handoff_required`. | `platform-windows/src/virtualdesk.rs`, `win32/`; `cua-driver-core/src/consent.rs`, `browser/` |
| W6.4 | Per-app allow/deny list, set in Dove Settings and passed as a policy file. Denied apps do not appear in `list_windows` and cannot be targeted. | `cua-driver-core/src/policy.rs` (Rego via `regorus`), `window_target.rs`; `cua-driver/src/serve.rs` (`CUA_DRIVER_POLICY_FILE`) |

**Done when:** a W7 fixture suite with password fields, a fake credential dialog and a payment form shows each one
refused or handed off on all three OSes.

## W7. Cross-platform CI

| # | Work item | Files |
|---|---|---|
| W7.1 | Windows job: build plus unit tests, and UIA e2e against the WinUI3 fixture harness. | `/tests/fixtures/apps/windows`, `/tests/fixtures/CuaTestHarness.sln`, `cua-driver-e2e/tests/harness_winui3_test.rs`, `/tests/runners/windows` |
| W7.2 | macOS job: AX e2e against the SwiftUI fixture, with TCC pre-seeded the way upstream's Lume runner does it. | `/tests/fixtures/apps/macos`, `cua-driver-e2e/tests/harness_swiftui_test.rs`, `/tests/runners/macos-lume` |
| W7.3 | Linux jobs: Xvfb with AT-SPI (GTK3 fixture), plus Sway headless for Wayland. | `/tests/fixtures/apps/linux`, `cua-driver-e2e/tests/harness_gtk3_test.rs`, `desktop_scope_linux_test.rs` |
| W7.4 | Shared contract tests (`cross_platform_behavior_test.rs`) and the W4.5 latency gate run on all three. Port the job shapes from upstream's `ci-cua-driver-quick.yml` and `e2e-cua-driver-release-gate.yml`. | `cua-driver-e2e/tests/`, `/.github/workflows/` |

**Status (2026-10-20, branch `dove-driver/w7-ci`):** `ci/github-workflows/dove-driver-ci.yml` holds all four jobs
(parity; Linux x11 and sway; macOS; Windows), each with contract tests and the `latency` / `grounder` gate slots
(`ci/dove/run-gate.sh`; grounder only when `vars.DOVE_GROUNDER_WEIGHTS_URL` is set). `scripts/dove/publish-folder.sh`
places it at the NEXI root as `.github/workflows/dove-driver-ci.yml`; it has not been published, so it has never run
on GitHub. Run locally on Linux: build, unit tests (2789 pass, 1 fails as above under R0.2), `cua-telemetry` 53/53
(with `--features http`, since Dove compiles its sender out and upstream's loopback test would hang), contract
tests, GTK3 AT-SPI e2e 37/37 under Xvfb (`ci/dove/linux/x11-session.sh`) and 37/37 under headless Sway, desktop
scope 5/5, R0.2 side by side, and the parity job via `ci/dove/fork-tree.sh`. macOS and Windows jobs are unrun.
The upstream import lost most scripts' executable bits, so CI runs fixture scripts through `bash`.

## W8. Benchmarks published per release

See the benchmark plan below. Work items: W8.1 a harness adapter that runs any MCP computer-use driver under the
same agent loop; W8.2 per-call token accounting (`DOVE_USAGE_TOKENS=1` adds input/output token estimates to each
result's `_meta["ai.dove/token-usage"]`, in `cua-driver-core/src/mcp_result.rs`); W8.3 a results page generated per
release tag.

Status (2026-10-20): W8.1 and W8.3 are built in `bench/` (subsets pinned, configurations A–G, resumable runs,
bootstrap CIs, gates, claim rule). W8.2 is not: the driver does not emit `ai.dove/token-usage` yet, so the harness
estimates observation tokens from the results (it uses the driver's count once the patch lands). Measured on the way:
the eager `tools/list` of dove-driver 0.37 is 66 tools in 230 KB (about 57k tokens on every model turn), the same as
stock cua-driver, which makes W5 the largest token lever; and on Linux a background pixel click on a GTK entry fires
AT-SPI `activate` without moving keyboard focus, so a following `type_text` lands in the previously focused field
(the result says "not verified"; W2).

## W9. Local Grounder

Turn an explicit sub-goal ("click Save", "type 'x' into the Email field") into one action with 0 LLM tokens, by
running nexi-cua v0.4.0's decision policy (Apache-2.0, see [NOTICE.md](NOTICE.md)) over dove-driver's own snapshot
rows. The calling model keeps every judgement call: the grounder abstains when unsure and returns its best rows.

| Item | Status | Where |
|---|---|---|
| W9.1 Port: nexi-cua's resolver, features, candidate enumeration, calibration, margin rescue and argument parsing, exactly; NEXI-CUA-1 run with tract (pure Rust) | done | `rust/crates/dove-grounder` (Dove-only) |
| W9.2 Asset: one ONNX file from `nexi-cua-1.pt` (`scripts/export_onnx.py`), optional, named by `DOVE_DRIVER_GROUNDER_MODEL`. Off when absent; loaded on first use; unloaded after `DOVE_DRIVER_GROUNDER_IDLE_SECS` (default 300) | done | `dove-grounder/src/service.rs`, `model.rs` |
| W9.3 Driver: `act {pid, window_id, intent}` and the `run_steps` step `{"intent": ...}`; both act through element tokens and return the outcome plus a `since:"latest"` diff, or on abstention the top 3-5 candidate rows | done | patch `0003-local-grounder.patch`: `cua-driver-core/src/grounder_tools.rs`, `batch_tools.rs` |
| W9.4 Windows and macOS checks of `act` on real windows | open | measured on Linux (GTK3 via AT-SPI) only |
| W9.5 W8 measurement: tokens per task with and without `act`, at equal success | open | W8 harness |

**Gate (all cargo tests; the model parts run when `DOVE_DRIVER_GROUNDER_MODEL` is set).** Measured on Linux on
2026-10-20 against the unmodified Python on the same inputs (torch 2.14.1 CPU):

- Identical decisions and identical top-ranked candidates on all 2,072 cases, with and without the resolver:
  nexi-cua's 5 captured pages (72 goals) and the 2,000 seeded synthetic screens of its `semantic_eval`
  (`dove-grounder/tests/gate.rs`). The screens are regenerated by a bit-exact Rust port of nexi-cua's generator and
  CPython's `random`; the committed goldens (135 KB) hold only labels, decisions and screen digests.
- Real-web 71/72 and abstain 10/10, as nexi-cua.
- Synthetic: 95.01% full pipeline and 61.56% ranker alone, which is exactly what nexi-cua v0.4.0 itself scores on
  these inputs. Its documents claim 98.8% and 92.1%; the committed code and weights do not reproduce those
  (Python 3.12 and 3.13, any hash seed), so the gate asserts the measured values.
- Memory: the grounder adds about 19 MB peak RSS in isolation (`tests/memory.rs`, release build, 4 ms per
  decision) and 19-21 MB to a live daemon acting on a GTK3 window over AT-SPI, whose peak is 70-72 MB
  (`tests/daemon.rs`). Budgets: 30 MB and 250 MB. Windows is still to measure (W9.4).
- The asset is fp32 (6.4 MB). An fp16 asset (`--fp16`, 3.2 MB) makes the same decisions but ranks a different
  candidate first on 3 abstained near-ties (top two within 0.6%), so it fails the gate. int8 was not tried.

---

## Benchmark plan

### Questions it answers

1. Does tree-first observation keep or raise task success compared with screenshot-driven control?
2. How many tokens and how much wall time does a task cost?
3. Is each release better than the last, and better than stock cua-driver?

### Suites

| Suite | OS | Subset for per-release runs | Full run |
|---|---|---|---|
| **OSWorld-Verified** | Ubuntu (VM) | ~100 tasks, stratified across its app domains (Chrome, LibreOffice Calc/Writer/Impress, GIMP, VS Code, Thunderbird, VLC, OS/file tasks, multi-app), excluding tasks whose checker is known to be flaky | every minor release |
| **Windows Agent Arena** | Windows 11 (VM) | ~60 tasks across its domains (Office, Edge/Chrome, File Explorer, Settings, Notepad/Paint, VS Code, utilities) | every minor release |
| **MacArena** | macOS (VM, e.g. Lume) | ~40 tasks across Finder, system apps, Safari/Chrome, Office/iWork. If MacArena has no public task set by the time we run, use macOSWorld's English tasks with the same stratification and say so in the report | every minor release |

Pin the subset task IDs in `bench/subsets/*.json` and change them only with a version bump, so numbers stay
comparable across releases. Use each suite's own checker for success.

### Configurations (same model, same prompt, same step limit)

| ID | Driver | Observation |
|---|---|---|
| A | dove-driver, this release | tree-first (W1 defaults), lazy tools, `run_steps` |
| B | dove-driver, previous release | its defaults |
| C | stock cua-driver, latest upstream release | its defaults |
| D | dove-driver | screenshot-only: tree off, pixel actions only (the vision baseline) |
| E | dove-driver | tree + set-of-marks screenshot (`vision: true`) |
| G | dove-driver, this release | A plus the W9 local grounder (`act {goal}`) |

Run each configuration with at least two models, one frontier and one small or cheap, because token savings matter
most to the cheap one. Run every task 3 times and report the mean and a 95% bootstrap confidence interval.

### Metrics

- **Success rate:** the suite checker's pass/fail, per task, averaged.
- **Tokens per task:** model input plus output tokens from the provider's usage fields, summed over the task. Also
  report observation tokens alone, from `ai.dove/token-usage`, so driver effects are separated from model verbosity.
- **Wall time per task:** from task start to the agent's final answer, split into model time and driver time
  (driver time is the sum of tool-call latencies).
- Secondary: steps per task, MCP round trips per task, screenshots per task, the share of actions delivered
  semantically against synthetically (W2), refusals and handoffs (W6), and driver errors per 100 calls.
- Driver micro-latency: p50/p95 of `get_window_state` (with and without `query`), `run_steps` and `verify_state`
  on the W7 fixture apps (from W4.5).

### Harness

- Put the harness in `/bench/` in this repo. It adapts each suite's task runner to call the driver over MCP stdio.
  Upstream's MIT `libs/cua-bench` and `ci-cua-driver-bench.yml` are the starting point. **Built (2026-10-20):**
  see `bench/README.md`. Smoke-tested on Linux with a scripted stub model (`bench/results/smoke-linux-local.md`);
  the VM suites and the paid models have not been run yet. The "#1" claim rule below (A or G against C and D) is
  enforced in `bench/dovebench/report.py`.
- VMs come from snapshots, with one fresh snapshot per task attempt. Record the driver version, OS build, model
  id and harness commit with every run.
- Store trajectories (tool calls, results, timings, token usage) as JSONL, with screenshots only where the
  configuration took them, so a failure can be replayed with `replay_trajectory`.

### Reporting and gates

- On each release tag, publish `bench/results/<version>.md` plus a JSON file, with one table per suite: configuration ×
  model → success, tokens/task, wall time/task, each with its CI. Link it from the GitHub release notes.
- A release is blocked if A's success rate falls more than 2 points below B's on any suite with non-overlapping
  CIs, or if tokens/task rises more than 10%.
- The headline claim, "#1", is made only where A beats C and D on success at equal or lower tokens/task, with
  non-overlapping CIs.

---

## Sequencing

1. R0.5 build prerequisite and the Linux/macOS checks left in R0.2. (R0.1, the Windows part of R0.2, and R0.4 are done.) Nothing ships before these.
2. W5 lazy disclosure and W1.2/W1.3 observation, because those give the token wins.
3. W7 CI and W4.5 latency harness, so later work has a gate.
4. W2 semantic actions, W3 waits and assertions, W6 safety.
5. W4 event-driven caching.
6. W8 harness, then the first published benchmark at the first Dove Computer Use release. R0.3 and R0.6 must be
   finished by that release.

## Provenance of the prebuilt `dove-driver 0.34.0`

A prebuilt `dove-driver-windows-x86_64.exe` (built 2026-10-12, rustc 1.97.1), used before this fork existed, reports
version 0.34.0, but it contains upstream 0.35.0 features (`run_steps`, `run_script` on by default, `since`). It
was most likely built from upstream `main` after `cua-driver-rs-v0.34.1` and before the 0.35.0 version bump. It
adds the fork-only lazy disclosure and token-usage metadata, and a string-level `cua-driver` → `dove-driver`
rename that leaves crate paths, most `CUA_*` env vars and upstream URLs unchanged (for example
`github.com/trycua/cua/tree/main/libs/dove-driver/rust`). No source for it was found locally or in the
PupppyLoverr GitHub repositories.
