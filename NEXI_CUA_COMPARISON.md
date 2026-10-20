# nexi-cua vs dove-driver

Compared on 2026-10-20 from the GitHub API, without cloning:

- nexi-cua: `PupppyLoverr/NEXI-Models-Drivers/nexi-cua`, v0.4.0, commit `fa3c797`. The private
  `gabbledobo-71588/nexi-cua` is the same v0.4.0.
- dove-driver: this repository, upstream `cua-driver-rs-v0.37.0` plus the Dove patches.

**Short answer: they are different layers, and Dove needs both ideas.** nexi-cua is ahead in one layer, the
*decider*: a tiny local model that turns an explicit goal ("click Save") into one action, with 0 LLM tokens and
the option to abstain. dove-driver is far ahead in the other, the *hands*: background input, a broad and tested
MCP tool surface, and verified behaviour on Windows. Do not replace dove-driver with nexi-cua's drivers. Port
nexi-cua's ranker on top of dove-driver's tree as an optional fast path.

## What each one is

| | nexi-cua v0.4.0 | dove-driver (cua-driver 0.37.0 fork) |
|---|---|---|
| Role | goal → action decider, plus its own drivers and agent loop | driver: an MCP server that frontier agents (Claude Code, Codex, ...) drive |
| Language and runtime | Python 3.10+, PyTorch, about 458 MB peak RSS (its own measurement) | Rust daemon, single exe |
| Interface | CLI and local HTTP API (`nexi-cua serve`, port 8090) | MCP over stdio or HTTP, 63 tools, lazy-disclosure rebuild planned (W5) |
| License | Apache-2.0 | MIT |
| Learned model | NEXI-CUA-1: 1.6M params, 6.3 MB, ranks typed candidate actions and abstains | none: the calling LLM decides |
| Vision fallback | local Qwen2-VL-2B (MLX or llama.cpp), about 6 s per query | window-scoped screenshots for the calling model; the AGPL perception extension is left out |

## Driver layer: dove-driver leads

| | nexi-cua | dove-driver |
|---|---|---|
| Background control | **No.** Windows uses `SetCursorPos`, `mouse_event`, `SendInput` and `SetForegroundWindow` (`perceive/windows.py`). macOS posts global `CGEvent`s to the frontmost app. Linux uses global XTest/xdotool. The user's cursor and focus are taken. | **Yes**, on all three OSes: semantic patterns first, background synthetic input next, foreground only when refused and reported |
| Windows semantic actions | UIA Invoke and Toggle only | Invoke, Value, Toggle, SelectionItem, ExpandCollapse, Scroll and more, plus a uiAccess worker for elevated apps |
| Tree reads | depth ≤ 12, ≤ 600 elements, one cross-process call per property | element tokens, `query`, `max_elements`, a 250-node lean default, `since` diffs, walk budget |
| Batching and checks | one action per step through its own loop | `run_steps` (find, wait and check steps), `verify_state`, `run_script` |
| Browser | raw CDP, Chromium only | typed browser tools (`browser_navigate`, `browser_click`, `browser_select`, ...) |
| Verified where | macOS only. Windows and Linux are "implemented, native verification pending" in its own STATUS.md | built and run on this Windows machine; upstream CI covers macOS, Windows and Linux |
| Tests | 19 unit tests | thousands of upstream unit and e2e tests; 1,058 core unit tests passed here |

## Decision layer: nexi-cua leads

- **Zero-token single actions.** For an explicit sub-goal it picks one action in about 12–26 ms with no LLM call.
  dove-driver always spends the calling model's tokens on every decision.
- **Abstention.** It refuses to act on unanswerable goals (10/10 on its suite) instead of guessing.
- **A deterministic resolver plus a learned ranker,** with a normalized observation schema that keeps platform
  details out of the model.
- **Goal-level safety classes.** Deletion, purchases, sending, credentials, installs and permission changes need
  confirmation; malicious or bypass intents are blocked. It works by keyword regexes over the goal and action text,
  so it is crude, but the confirm/block split is the right shape for ROADMAP W6.

## How far to trust the numbers

nexi-cua's documents are careful about this, and the caveats matter:

- 98.6% is **single-step** action choice on **5 captured pages, 72 self-labelled goals**. 98.8% is on its own
  synthetic generator. Neither is a multi-step task benchmark.
- It has **no OSWorld, WebArena, BrowserGym or ScreenSpot runs** yet. Its comparison table quotes other systems'
  published scores, which are not like-for-like.
- Weaker spots it reports itself: drag 0.70, scroll 0.68.

## Practical problems found

- The README's one-line installers and the `pyproject.toml` URLs point at `PupppyLoverr/gabbledobo-71588`, which is
  **private**, so they fail for anyone else. They should point at `NEXI-Models-Drivers`.
- Release wheels (6 MB) and an sdist (13 MB) are committed into git, not attached as GitHub release assets.

## Recommendation for Dove

1. Keep dove-driver as Dove Computer Use's driver. It is the only one of the two with background control, an MCP
   surface for every harness, and Windows behaviour verified here.
2. Add a later work item (W9, "local autopilot"): run NEXI-CUA-1 over dove-driver's `get_window_state` rows, so an
   agent can call one tool such as `act {goal}`. The tool resolves to an element token locally, acts through
   `run_steps`, and abstains back to the LLM when unsure. Its Apache-2.0 license is compatible with MIT. Benchmark it
   with the ROADMAP W8 plan against the LLM-only loop: tokens per task should drop at equal success.
3. Take its confirm/block classes into W6, attached to the target element (password fields, payment frames, UAC)
   as well as the goal text.
4. Fix the private-repo installer URLs in nexi-cua.

## What a local clone would add

All of the above comes from reading the code and documents. With a clone of only `nexi-cua/`, I could check its
Windows claims on this machine: run its 19 tests, run `nexi-cua observe` and `run` against Notepad, and measure
whether it takes the cursor, its latency, and its accuracy next to dove-driver on the same window.
