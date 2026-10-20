# dove-driver roadmap

dove-driver is the engine behind **Dove Computer Use**, an installable Dove plugin. The goal is the best open
computer-use driver: tree-first, screenshot-optional and token-efficient, with background control on macOS,
Windows and Linux. This file turns the eight "What makes it #1" points of the Dove plan (§11) into work items mapped
to source files, followed by the benchmark plan.

Paths are relative to `rust/crates/` unless they start with `/`. "Upstream" means `trycua/cua` `libs/cua-driver`.

## Where we start

- Base: upstream `cua-driver-rs-v0.34.0` (`b0968e1`, 2026-10-05), with `cua-perception` removed (see NOTICE.md).
- Already in 0.34.0: element tokens (`cua-driver-core/src/element_token.rs`), `get_window_state` with `query`,
  `max_elements`, `max_depth`, `include_screenshot`, `max_image_dimension` and a walk budget
  (`cua-driver-contract/src/windows.rs`, `cua-driver-core/src/walk_budget.rs`), `verify_state`
  (`cua-driver-contract/src/verification.rs`, `cua-driver-core/src/expectation.rs`), action effects
  (`cua-driver-core/src/action_record.rs`), delivery modes (`cua-driver-core/src/delivery.rs`,
  `background_input.rs`) and the standard/bounded permission modes (`cua-driver-core/src/authorization.rs`).
- **Not in 0.34.0, but upstream ships it in 0.35.0 (2026-10-12):** `get_window_state since:<snapshot_id>` row diffs
  (CUA-1193), lean default output (compact markdown, at most 250 nodes, `full_output: true` for the old shape),
  `run_actions`, renamed to `run_steps`, with find, wait and check steps (CUA-1194), and `run_script` (sandboxed
  QuickJS). Upstream adds `cua-driver-core/src/batch_tools.rs`, `batch_nudge.rs`, `step_pacing.rs` and
  `script_tool.rs` for these.
- **Not upstream at all:** lazy tool disclosure (`describe_tools`, `DOVE_TOOL_DISCLOSURE=lazy`) and per-result token
  usage metadata (`ai.dove/token-usage`, `DOVE_USAGE_TOKENS=1`). Both exist only in the prebuilt
  `dove-driver 0.34.0` Windows binary, whose source was not found (see "Provenance" below).
  These are rebuilt here as W5 and as part of W8.

## R0. Foundation (before any feature work)

| # | Work item | Files | Done when |
|---|---|---|---|
| R0.1 | **Move the base to upstream `cua-driver-rs-v0.35.0` or later** (`v0.36.0` is current). Import the tag on the `upstream` branch, merge it into `main`, and rerun the rebrand edits. This brings in `since` diffs, `run_steps`, lean output and `run_script`, so W1 and W3 do not port them by hand. | whole tree; the rebrand list in NOTICE.md | `main` builds and its tests pass on the new base |
| R0.2 | **Finish the identity rename** so dove-driver never shares state with a stock `cua-driver` on the same machine. Rename the state dir to `~/.dove-driver(-local)`, the named pipes (`\\.\pipe\cua-driver*`), Unix sockets, Linux secret-service names, MCP `serverInfo.name`, the skill pack name and the cursor/browser profile dirs. Add `DOVE_DRIVER_*` env aliases while still reading `CUA_DRIVER_*`. | `cua-driver/src/bundle.rs`, `serve.rs`, `history_runtime.rs`, `skills.rs`, `telemetry.rs`, `version_check.rs`; `cua-driver-core/src/protocol.rs`, `mcp_wire.rs`, `policy.rs`, `browser/prepare.rs`; `cua-driver-sdk/src/lib.rs`, `embedded.rs`; `cua-driver-uia/src/main.rs`; `cursor-overlay/src/theme_artifact.rs`, `motion_defaults.rs`; `pip-preview/src/lib.rs`; `platform-linux/src/history.rs`, `session_bus.rs` | dove-driver and cua-driver run side by side with separate state, and an e2e test proves it |
| R0.3 | **macOS identity.** `DoveDriver.app`, bundle id under Dove's Apple team, entitlements, TCC strings. This needs Dove's Developer ID. | `cua-driver/src/bundle.rs`, `/rust/scripts/CuaDriverBundle`, `/rust/scripts/CuaDriver.entitlements`, `platform-macos/src/tools/check_permissions.rs` | a signed, notarized app gets AX and Screen Recording grants under its own identity |
| R0.4 | **Cut the upstream phone-home.** Telemetry posts to Cua's PostHog (`cua-driver/src/telemetry.rs`), the update check reads `trycua/cua` releases (`version_check.rs`), and `updater.rs` would replace dove-driver with stock cua-driver. Point telemetry at Dove's opt-in pipeline or turn it off. Read updates from Dove's release manifest, or turn updates off and let Dove's plugin manager own them. | `cua-driver/src/telemetry.rs`, `version_check.rs`, `updater.rs`, `check_update_tool.rs`; `cua-telemetry` | no network request leaves the driver unless Dove asks for one |
| R0.5 | **Windows build prerequisite.** `regorus` turns on `msvc_spectre_libs` with `error`, so a build fails without the VS "MSVC Spectre-mitigated libs" component. Install it on dev machines and CI, and document it in README. | `/README.md`, CI images | a clean Windows box builds with the documented steps |
| R0.6 | **Release pipeline.** Signed release assets per OS/arch, a SHA-256 manifest that Dove compiles in, Authenticode on Windows, notarization on macOS. Port from upstream `.github/workflows/cd-rust-cua-driver.yml` and `cua-driver-release-signatures.yml`. | `/.github/workflows/` (new), `/scripts/` | Dove's Install button can fetch and verify a tagged release |

## W1. Tree-first, screenshot-optional observation

**Goal:** the default observation is a pruned tree of interactive and labelled nodes, one compact row per node
(`[N] role "name" value state`), each row carrying an element token. Screenshots appear only when asked for, when
the surface has no tree, or when the session declares vision.

| # | Work item | Files |
|---|---|---|
| W1.1 | Lean output by default: compact rows, a node cap, `full_output` opt-in. Comes with R0.1. Then tune pruning: drop unlabelled containers, collapse single-child chains, merge static text into its labelled parent. | `cua-driver-core/src/window_inspection.rs` (tree markdown), `walk_budget.rs`; `platform-windows/src/uia/snapshot.rs`; `platform-macos/src/ax/tree.rs`, `ax/snapshot.rs`; `platform-linux/src/atspi/snapshot.rs`, `snapshot_queries.rs` |
| W1.2 | `since:"latest"` as well as `since:<snapshot_id>`: diff against the session's last snapshot of that window, and return `no change` when nothing changed. | `cua-driver-core/src/snapshot_store.rs`, `element_token.rs`, `session.rs`; `cua-driver-contract/src/windows.rs` |
| W1.3 | Screenshot policy: window-scoped, downscaled, JPEG by default, returned only when (a) `include_screenshot: true`, (b) the tree is empty or below a node threshold (canvas, games, remote desktop), or (c) the session opened with `start_session {vision: true}`. Tokens stay valid when the tree is skipped. | `cua-driver-core/src/image_utils.rs` (`png_bytes_to_jpeg`, `resize_png_if_needed`), `capture_mode.rs`, `capture_scope.rs`, `session.rs`, `session_tools.rs`; `platform-windows/src/capture.rs`, `wgc.rs`; `platform-macos/src/capture.rs`; `platform-linux/src/capture.rs` |
| W1.4 | Set-of-marks mode: draw each row's `[N]` on the screenshot at its element frame, so a vision model clicks by token instead of by pixel. | `cua-driver-core/src/image_utils.rs` (next to `crosshair_png_bytes`), `element_frame.rs`; a `marks: true` input in `cua-driver-contract/src/windows.rs` |

**Done when:** on the W8 task set, median observation tokens per step drop at least 10× against a screenshot-only
baseline at equal or better success rate, and a `since:"latest"` re-read after a small change is under 15% of a
full read.

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
| W3.1 | `run_steps` with early stop and an `observe` diff. Comes with R0.1 (`batch_tools.rs`). | `cua-driver-core/src/batch_tools.rs` (upstream 0.35+) |
| W3.2 | `wait_for {query, gone, timeout}` and assertion steps (`expect` reusing `verify_state` predicates) inside `run_steps`, with Playwright-style auto-wait before each action: target exists, enabled, on screen and stable. | `batch_tools.rs`, `cua-driver-core/src/expectation.rs` (`evaluate_predicates`), `element_query.rs` |
| W3.3 | Decide `run_script` (QuickJS): keep it on for loops and branches, keep it off in `bounded` mode, and cover it with the W6 policy. | `cua-driver-core/src/script_tool.rs` (upstream 0.35+), `authorization.rs` |

**Done when:** a typical "open dialog, fill three fields, submit, check result" flow is one `run_steps` call,
and W8 reports round trips per task.

## W4. Speed

**Goal:** p50 under 40 ms for `get_window_state` with a `query` on a typical app; p95 under 150 ms.

| # | Work item | Files |
|---|---|---|
| W4.1 | Keep one daemon per user session, warm across MCP clients; the MCP stdio process proxies to it. Measure cold and warm start. | `cua-driver/src/serve.rs`, `proxy.rs`, `cua-driver-core/src/daemon.rs` |
| W4.2 | Cache tree walkers per window and invalidate them on events: UIA `StructureChanged`, `PropertyChanged` and focus events, macOS `AXObserver` notifications, AT-SPI `object:children-changed` / `state-changed`. Re-walk only the dirty subtree. None of these subscriptions exist in 0.34.0. | `platform-windows/src/uia/mod.rs`, `uia/snapshot.rs`; `platform-macos/src/window_change_detector.rs`, `ax/`; `platform-linux/src/atspi/mod.rs`; `cua-driver-core/src/snapshot_store.rs` |
| W4.3 | Use a UIA `CacheRequest` with only the properties the rows need, so one cross-process call replaces a call per property. | `platform-windows/src/uia/snapshot.rs` |
| W4.4 | Snapshot several windows in parallel for `get_desktop_state` and multi-window flows. | `cua-driver-core/src/window_observation.rs`; per-platform `get_desktop_state` |
| W4.5 | Latency harness: p50/p95 per tool per fixture app, run in CI, failing on a regression above 20%. Start from upstream's `ci-cua-driver-bench.yml` and `cua-driver-core/tests/recording_turn_latency.rs`. | `cua-driver-e2e/tests/` (new `latency_test.rs`), `/.github/workflows/` |

## W5. Lazy tool disclosure

**Goal:** a harness sees a tiny tool list until it needs more.

| # | Work item | Files |
|---|---|---|
| W5.1 | `DOVE_TOOL_DISCLOSURE=lazy`: `tools/list` returns full schemas for `list_windows`, `get_window_state`, `run_steps`, `verify_state` and `describe_tools` only, and names plus one-line descriptions for the rest. | `cua-driver-core/src/server.rs` (`tools_list`), `tool.rs`, `tool_schema.rs`, `mcp_wire.rs`; `cua-driver/src/serve.rs`, `mcp_envelope.rs` |
| W5.2 | `describe_tools {names: [...]}` returns full input schemas on demand. Calling a tool whose schema was withheld still works, and a bad call returns the schema in the error. | `cua-driver-core/src/tool.rs`; each platform's `tools/mod.rs` (`build_registry`) |
| W5.3 | MCP server instructions (the "efficient loop") and the bundled `dove-computer` skill describe the lazy flow. | `cua-driver-core/src/mcp_skills.rs`, `/rust/Skills/` |

**Done when:** the `tools/list` payload in lazy mode is under 3 KB, and W8 shows no success-rate loss against eager
mode.

## W6. Safety

| # | Work item | Files |
|---|---|---|
| W6.1 | Keep the `standard` / `bounded` permission modes. Dove sets the mode at launch. | `cua-driver-core/src/authorization.rs`, `session_authorization.rs`, `policy.rs` |
| W6.2 | Never type into password or secure fields: UIA `IsPassword`, `AXSecureTextField`, AT-SPI `ROLE_PASSWORD_TEXT`, browser `input[type=password]`. Refuse with a typed error that tells the model to hand off. In 0.34.0 the only guard is on Linux, where `atspi/native.rs` hides a password field's text. No platform refuses typing into one. | `platform-windows/src/tools/impl_.rs`, `uia/snapshot.rs`; `platform-macos/src/tools/type_text.rs`, `set_value.rs`; `platform-linux/src/tools/impl_.rs`; `cua-driver-core/src/browser/` |
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

## W8. Benchmarks published per release

See the benchmark plan below. Work items: W8.1 a harness adapter that runs any MCP computer-use driver under the
same agent loop; W8.2 per-call token accounting (`DOVE_USAGE_TOKENS=1` adds input/output token estimates to each
result's `_meta["ai.dove/token-usage"]`, in `cua-driver-core/src/mcp_result.rs`); W8.3 a results page generated per
release tag.

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
  Upstream's MIT `libs/cua-bench` and `ci-cua-driver-bench.yml` are the starting point.
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

1. R0.1 rebase, then R0.2 identity, R0.4 phone-home and R0.5 build prerequisite. Nothing ships before these.
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
