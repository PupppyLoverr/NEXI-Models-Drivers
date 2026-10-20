# NEXI-CUA

NEXI-CUA is a **complete local computer-use system**. It combines:

- **NEXI-CUA-1, the learned model:** a small goal-conditioned neural ranker
  that selects the most appropriate valid action for the current screen, or
  abstains when it is not confident.
- **A typed control protocol:** platform-independent observations, elements,
  actions, decisions, verification results, and safety outcomes.
- **Computer-use drivers:** real macOS, Windows, Linux, and Chromium adapters
  that observe interfaces and execute clicks, typing, scrolling, dragging,
  navigation, tab operations, and keyboard input.
- **An agent runtime:** the observe, decide, authorize, act, and verify loop.
- **Local vision fallback:** screenshot grounding for targets that cannot be
  resolved from accessibility data or the browser DOM.

The model is the decision-making brain. The typed protocol constrains what it
can request. The drivers are the hands that control the computer. The complete
package is the computer-use system.

**$0 recurring cost, no cloud inference, no paid AI APIs.** It works with any
computer-use surface that implements the normalized observation schema.

## What the model actually does

NEXI-CUA-1 is not a general chat model and does not generate free-form plans
or JSON. For each step, the runtime:

1. Reads the current accessibility tree, browser DOM, or visual state.
2. Normalizes visible controls into the same cross-platform element schema.
3. Generates only actions that are valid for the current state.
4. Scores those candidates against the user's goal.
5. Selects one typed action, or abstains.
6. Lets a deterministic driver execute it and verifies the resulting state.

This is best described as a **type-safe, goal-conditioned action-ranking
model inside a cross-platform computer-use runtime**.

## The one rule that shapes everything

**Screenshots are the exception, not the default.** Observation hierarchy:

1. Accessibility / semantic state
2. Browser DOM / accessibility state
3. Application structure
4. Screenshot / visual state *(escalation only)*
5. Pixel coordinates *(last resort)*

If the a11y tree says `button "Save"`, the model emits `click("Save")` —
no screenshot is captured, decoded, or inferred from. The vision path is
only consulted when the semantic path abstains or the goal is intrinsically
visual.

## Architecture

```
                USER GOAL
                    │
                OBSERVE ───── NormalizedObservation (same schema on every OS)
                    │
        ┌───────────┴───────────┐
   SEMANTIC PATH            VISION PATH (escalation)
   a11y / DOM / UIA         screenshot → small VLM → region
   AT-SPI                   grounding
        │                        │
        └───────────┬────────────┘
                DECIDE ─── NEXI-CUA-1 (1.6M-param specialist model)
                    │      option-attention over candidate actions,
                    │      softmax probability + correctness head
                    │      → calibrated confidence + ABSTAIN
                ACT ──────── typed action space, safety-gated executor
                    │
                VERIFY ───── re-observe, semantic diff
                    │      success / failed / unchanged / uncertain
                RESULT
```

- **NEXI-CUA-1** (`nexi_cua/policy/model.py`): 1,606,418 params, ~6.1 MiB
  fp32. No tokenizer, no text generation — hashed char-ngram encoders,
  per-element encoders, goal→element attention, per-candidate scorer plus a
  correctness sigmoid for calibrated confidence and abstention.
- **Vision** (`nexi_cua/vision/`): Qwen2-VL-2B-Instruct — 4bit via
  `mlx-vlm` on Apple Silicon (preferred, ~6s/query), or a Q4_K_M GGUF
  served by `llama-server` on macOS/Windows/Linux. Answers exactly one
  question — *where is the described thing?* — via the model's native
  bounding-box output (with a labeled-grid fallback for models without
  box training). Honest caveat: at 2B/4bit the locator is useful but not
  perfect, so low confidence or an unparseable answer abstains instead of
  fabricating coordinates. Hybrid mode re-ranks semantic candidates
  against pixel crops when the goal is visually discriminative.

## Download and install

The repository includes the NEXI-CUA-1 policy weights and calibration file.
Large optional vision weights are downloaded separately and are not required
for semantic accessibility-tree or DOM control.

### One-line installers

| OS | Command |
|---|---|
| macOS / Linux | `curl -fsSL https://raw.githubusercontent.com/PupppyLoverr/NEXI-Models-Drivers/main/nexi-cua/install/install.sh \| sh` |
| Windows (PowerShell) | `irm https://raw.githubusercontent.com/PupppyLoverr/NEXI-Models-Drivers/main/nexi-cua/install/install.ps1 \| iex` |

The installers create an isolated venv (`~/.nexi-cua` or
`%LOCALAPPDATA%\nexi-cua`), install the platform extra and policy weights,
link the `nexi-cua` command and run `nexi-cua doctor`. Pass `--with-vision`
(`-WithVision`) for the optional local VLM, or `--uninstall` (`-Uninstall`).

### Prebuilt files

- Wheel (driver + NEXI-CUA-1 weights): [`releases/nexi_cua-0.4.0-py3-none-any.whl`](releases/nexi_cua-0.4.0-py3-none-any.whl), installable with `pip install <wheel>[macos|windows|linux]`
- Source distribution: [`releases/nexi_cua-0.4.0.tar.gz`](releases/nexi_cua-0.4.0.tar.gz)
- Checksums: [`releases/SHA256SUMS`](releases/SHA256SUMS)

Documents: [ARCHITECTURE.md](ARCHITECTURE.md) · [USE_CASES.md](USE_CASES.md) ·
[BENCHMARKS.md](BENCHMARKS.md) (comparison table) · [STATUS.md](STATUS.md)

### From source

Download the v0.4.0 source distribution (driver source and policy bundle):
[nexi_cua-0.4.0.tar.gz](https://github.com/PupppyLoverr/NEXI-Models-Drivers/raw/main/nexi-cua/releases/nexi_cua-0.4.0.tar.gz).
Or check out only this folder:

```bash
git clone --filter=blob:none --sparse https://github.com/PupppyLoverr/NEXI-Models-Drivers.git
cd NEXI-Models-Drivers
git sparse-checkout set nexi-cua
cd nexi-cua
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[macos]"       # use .[windows] or .[linux] on those systems
nexi-cua doctor
```

Release archives contain the driver source, policy weights, calibration,
documentation, tests, and evaluation fixtures in one folder.

## Quickstart (macOS)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[macos]"
pip install mlx-vlm             # vision path on Apple Silicon (preferred)
brew install llama.cpp          # or the llama.cpp vision path
nexi-cua download-weights       # GGUFs for the llama.cpp vision path

nexi-cua doctor                 # environment + permission checks
nexi-cua train --steps 3500     # train NEXI-CUA-1 (~10 min on M-series)
nexi-cua observe                # dump normalized AX state
nexi-cua decide "save the file"
nexi-cua run "compute 7 times 8" --app Calculator
nexi-cua bench                  # real latency/RSS numbers
nexi-cua eval                   # held-out semantic eval
python -m nexi_cua.eval.live_eval   # real-app E2E (Calculator + Chromium)
```

Grant **Accessibility** (and Screen Recording for the vision path) to your
terminal/python when macOS asks.

## API

```python
from nexi_cua import NexiCUA
nx = NexiCUA(browser=True)          # desktop adapter + Chromium over CDP
obs = nx.observe("click Save")
dec = nx.decide(obs, "click Save")  # Decision: action+prob+confidence+abstain
res = nx.act(dec.action, "click Save")
vr  = nx.verify(dec.action, obs, nx.observe())
run = nx.run("fill in the login form")   # full loop, ≤20 steps, safety-gated
```

`nx.run` stops on `done`, `abstained`, `failed`, `confirm` (needs your
approval), or `max_steps`.

## Measured (this machine: macOS arm64, MPS)

| metric | value |
|---|---|
| model size | 1,606,418 params / 6.29 MB fp32 |
| cold load | ~45 ms |
| decide() | p50 25.7 ms / p99 28.1 ms on a real 357-element page (≈12 ms on typical synth screens) |
| held-out accuracy (answerable) | **98.8%** full pipeline on the harder v3 distribution (2000 screens, `python -m nexi_cua.eval.semantic_eval`); **92.1% ranker-only** (`--ranker-only`, learned model alone, was 87.9% before the v0.4.0 training run). Every verb 1.0 except click 0.97, focus 0.97, type 0.996. v0.4.0 also fixed the scorer, which used to build the expected answer with the same argument parser it was testing; the old 89.2% was scored that way. |
| real-web accuracy | **98.6% (71/72), identical on CPU and MPS** on 5 captured real pages (Wikipedia ×2, DuckDuckGo, GitHub Trending, w3schools form; 72 self-labeled goals, `eval/real_eval.py`). Unanswerable goals: 10/10 abstained. Was 51.4% before the semantic resolver |
| abstain | **10/10 CPU / 9/10 MPS** unanswerable real goals correctly abstain — a goal naming an element interaction can no longer resolve to a global keypress/wait. Margin rescue: softmax top-1 ≥0.30 with ≥1.5× margin overrides an under-calibrated correctness head, element-targeted verbs only |
| peak RSS (policy+torch) | ~458 MB |
| context cap | 512 elements / 112 candidates per decision |
| vision (MLX, Qwen2-VL-2B-4bit) | ~6 s / grounding query |

Live E2E verified on real apps: Calculator `7×8 → 56` via AX presses,
Chromium form submit + typing over CDP, VLM-grounded click on the green
button → verified page state. Run `python -m nexi_cua.eval.live_eval`.

These numbers are engineering measurements, not a claim of state-of-the-art
general reliability — the semantic resolver handles unambiguous goals deterministically. The real-web set contains five captured pages and 72
self-labeled goals. Windows and Linux adapters are implemented but have not
yet been verified on native Windows and Linux machines.

## Action space

semantic: `click, double_click, right_click, type, keypress, scroll, drag,
select, focus, check, switch_window, switch_tab, navigate, new_tab,
close_tab, back, forward, refresh, wait, done`
visual fallback: `click_xy, double_click_xy, right_click_xy, type_text,
keypress_keys, drag_xy, scroll_xy`

## Safety

The executor owns authorization — model confidence is never permission.
Deletion, purchases and transfers, sending/submitting, account/security
changes, software installation, permission changes, and irreversible actions
require confirmation. Malicious intent, destructive shell operations, and
safety-control bypass attempts are blocked. `--yes` can approve confirmation
classes but cannot override blocked classes.

## Platform adapters

| OS      | Perception             | Input                    | Capture          |
|---------|------------------------|--------------------------|------------------|
| macOS   | Accessibility API      | AX actions + CGEvent     | CGWindowList     |
| Windows | UI Automation          | UIA patterns + SendInput | mss / BitBlt     |
| Linux   | AT-SPI (+X11 fallback) | XTest / xdotool / wtype  | mss / grim/scrot |
| Browser | DOM + CDP (Chromium)   | CDP Input/DOM            | CDP screenshot   |

The model sees only the normalized schema — zero platform-specific logic in
`nexi_cua/policy/`.

## Training

`nexi-cua train` generates synthetic GUI screens (dialogs, forms, toolbars,
browsers, settings…) with programmatic ground truth, including abstention
cases (~8%) and ambiguous cases (~6%). Losses: candidate cross-entropy +
correctness BCE; temperature + abstain threshold fitted on a held-out split.

## Layout

```
nexi_cua/
  types.py           normalized observation schema (platform-agnostic)
  actions.py         typed action space + candidate enumeration
  safety.py          authorization classes (confirm/blocked)
  verify.py          post-action semantic verification
  agent.py           observe→decide→act→verify loop
  cli.py             nexi-cua command line
  perceive/          macos.py windows.py linux.py base.py
  browser/cdp.py     raw CDP client (no playwright)
  policy/            features.py model.py infer.py
  vision/            backend.py vlm_llamacpp.py vlm_mlx.py grounding.py
  exec/executor.py   surface routing + safety interception
  training/          synth.py dataset.py train.py
  bench/latency.py   real latency/RAM measurements
  eval/              semantic_eval.py (held-out) live_eval.py (real apps)
weights/             nexi-cua-1.pt + calib + vision GGUFs
```

See `ARCHITECTURE.md` for the full model and driver design. See `STATUS.md` for
the canonical implementation ledger, benchmark provenance, known limitations,
release contents, and next milestones.
