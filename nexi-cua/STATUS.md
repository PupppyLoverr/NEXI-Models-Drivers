# NEXI-CUA Status and Benchmark Ledger

This file is the canonical record of what exists, what has been measured, what
is downloadable, and what remains unverified. Update it whenever implementation
or benchmark claims change.

## Product identity

NEXI-CUA is a local, cross-platform computer-use system:

1. **NEXI-CUA-1 policy model** ranks dynamically generated typed actions.
2. **Normalized protocol** separates model decisions from platform details.
3. **Perception adapters** read macOS AX, Windows UIA, Linux AT-SPI, and DOM/CDP.
4. **Execution drivers** perform native and browser input.
5. **Safety gate** requires authorization for sensitive operations.
6. **Verifier** re-observes the interface and checks whether state changed.
7. **Safety policy** confirms financial, communication, credential, software,
   permission, and irreversible operations; destructive or malicious classes
   remain blocked even when auto-approval is enabled.
8. **Vision fallback** grounds visually described targets using a local VLM.
9. **Agent loop** coordinates observation, decisions, execution, and verification.

The learned model does not directly move the mouse or generate arbitrary plans.
The drivers do not decide what the user intended. The runtime connects both.

## Preserved implementation

| Area | Status | Primary paths |
|---|---|---|
| Typed observations and actions | Implemented | `nexi_cua/types.py`, `nexi_cua/actions.py` |
| Agent loop | Implemented | `nexi_cua/agent.py` |
| Safety and confirmation | Implemented | `nexi_cua/safety.py` |
| Semantic verification | Implemented | `nexi_cua/verify.py` |
| macOS perception and input | Implemented, exercised on macOS | `nexi_cua/perceive/macos.py` |
| Windows perception and input | Implemented, native verification pending | `nexi_cua/perceive/windows.py` |
| Linux perception and input | Implemented, native verification pending | `nexi_cua/perceive/linux.py` |
| Chromium DOM and input | Implemented, exercised through raw CDP | `nexi_cua/browser/cdp.py` |
| NEXI-CUA-1 inference | Implemented, weights included | `nexi_cua/policy/`, `weights/` |
| Local vision grounding | Implemented, optional weights downloaded separately | `nexi_cua/vision/` |
| Synthetic training | Implemented | `nexi_cua/training/` |
| Semantic evaluation | Implemented | `nexi_cua/eval/semantic_eval.py` |
| Captured real-web evaluation | Implemented | `nexi_cua/eval/real_eval.py`, `nexi_cua/eval/fixtures/` |
| Live application evaluation | Implemented | `nexi_cua/eval/live_eval.py` |
| CLI and local HTTP API | Implemented | `nexi_cua/cli.py` |
| Demonstrations and screenshots | Included | `demos/` |

## Included model artifact

- Name: NEXI-CUA-1
- Architecture: hashed character n-gram goal and element features, role and
  verb embeddings, goal-to-element attention, candidate action scorer, and
  correctness head.
- Parameters: 1,606,418.
- Policy artifact: `weights/nexi-cua-1.pt`.
- Calibration: `weights/nexi-cua-1.calib.json`.
- Approximate fp32 size: 6.29 MB.
- Runtime text generation: none.
- Required cloud inference: none.
- Required paid API: none.

The optional visual grounding model is intentionally not committed because its
files are hundreds of megabytes to several gigabytes. Use
`nexi-cua download-weights` or the MLX setup documented in `README.md`.

## Measured results

Measurements below came from the macOS arm64 development machine used for the
implementation.

| Measurement | Result | Provenance |
|---|---:|---|
| Harder v3 held-out synthetic accuracy | 98.8% full pipeline / 92.1% ranker-only (v0.4.0, corrected scoring) | `python -m nexi_cua.eval.semantic_eval [--ranker-only]` |
| Captured real-web accuracy | 98.6% (71/72), identical on CPU and MPS | `python -m nexi_cua.eval.real_eval` |
| Unanswerable real-web abstention | 10/10, identical on CPU and MPS | Same five-page fixture suite |
| Real 357-element page latency | p50 25.7 ms, p99 28.1 ms | `nexi_cua bench` |
| Typical synthetic-screen latency | approximately 12 ms | `nexi_cua bench` |
| Cold model load | approximately 45 ms | Local profiling |
| Policy plus PyTorch peak RSS | approximately 458 MB | Local profiling |
| MLX Qwen2-VL grounding | approximately 6 seconds/query | Local profiling |

The captured real-web suite contains five pages: Wikipedia main page,
Wikipedia reinforcement learning, DuckDuckGo home, GitHub Trending, and a
w3schools form. Scores vary slightly by compute backend (CPU vs Apple MPS)
because softmax margins sit close to the rescue thresholds; both variants are
reported above. It is a regression benchmark, not proof of broad web
reliability or a state-of-the-art claim.

## Verified scenarios

- macOS Calculator: entered `7 × 8` through accessibility actions and observed
  the result `56`.
- Chromium form: typed and submitted through CDP, then verified changed page
  state.
- Wikipedia: searched, navigated, clicked a semantic link with real cursor
  movement, and scrolled.
- DuckDuckGo: searched and followed a result through the browser path.
- TextEdit: typed text, used a toolbar control, and verified the document value.
- Local visual grounding: located a described target, clicked through native
  input, and verified changed state.

Screenshots for preserved demonstrations are in `demos/shots/`.

## Known limitations

- The five-page real-web score is 98.6% (one miss on the form page); duplicate element names now resolve to the topmost match (reading order), the same rule the eval labels use
  the largest measured generalization gap.
- Drag accuracy is 0.70 and scroll 0.68 (the generator randomizes direction labels on those goals) on the current harder
  synthetic evaluation.
- Windows and Linux adapters have not yet been exercised on native machines.
- Browser support currently targets Chromium through CDP.
- The optional 2B/4-bit vision locator is slower and less reliable than the
  semantic path, so the runtime abstains on low-confidence visual results.
- Public benchmark results for OSWorld, BrowserGym/WebArena, and ScreenSpot
  have not yet been produced. NEXI-CUA must not be described as number one
  until reproducible evidence supports that claim.

## Release contents

The versioned source release contains:

- Cross-platform driver and runtime source.
- NEXI-CUA-1 policy weights and calibration.
- Packaging metadata and platform extras.
- README, this ledger, and training documentation.
- Unit tests, evaluation harnesses, captured fixtures, demos, and screenshots.
- A SHA-256 checksum manifest.

Optional vision GGUF files, Python virtual environments, caches, and raw
training checkpoints are excluded.

## Verification commands

```bash
cd nexi-cua
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[macos]"
pytest -q
nexi-cua doctor
nexi-cua eval --n 2000
python -m nexi_cua.eval.real_eval
nexi-cua bench
```

Native Windows and Linux verification must be run on those operating systems.

## Development history

- `1e81eb2`: initial local computer-use runtime and policy.
- `b5ad43a`: human-like browser input and recorded live demonstrations.
- `183e370`: expanded training corpus, stable addressing, and vision cascade.
- `862097b`: real-web evaluation, positional features, dense corpus, and safer
  abstention.

## Next milestones toward best-in-class

1. Run reproducible OSWorld, BrowserGym/WebArena, and ScreenSpot evaluations.
2. Verify and profile the native Windows and Linux adapters.
3. Train on a larger, legally redistributable corpus of real interface traces.
4. Improve drag, tab selection, and dense-page ranking.
5. Add Firefox and WebKit browser adapters behind the same protocol.
6. Publish versioned benchmark artifacts and failure traces with every release.

## Release documents

README.md, ARCHITECTURE.md, USE_CASES.md, BENCHMARKS.md, installers in `install/`, prebuilt wheel/sdist + SHA256SUMS in `releases/`.

## v0.4.0 (2026-10-13)
- Fixed the eval scorer: expected answers now come from the generator's recorded value instead of the parser being tested (the old scorer expected "press the enter key" to press a key called "the").
- Driver/resolver bugs that the old scorer was hiding, now fixed: ranker-path scroll direction, dropdown option extraction, verb words inside element names, "Last name field" read as an ordinal, quoted text extraction.
- Added keyboard-shortcut intents (cmd mapped to ctrl on Windows/Linux in the executor) and semantic intents (cancel → Cancel/Back/Close; send → Send/Share/...).
- Removed contradictory training labels (scroll vs page-down, browser new-tab/back as keypress), then warm-started a 1600-step fine-tune: ranker-only 87.9% → 92.1%, synthetic abstain recall 0.81 → 0.92.
- Real-web unchanged at 71/72 on CPU and MPS, 10/10 abstention. 19/19 unit tests.
