# NEXI-CUA Architecture

## System boundary

NEXI-CUA is a model-powered computer-use runtime, not a single monolithic
model. It separates intent selection from operating-system and browser control:

```text
User goal
   |
   v
Perception adapter ---> NormalizedObservation
   |                            |
   |                            v
   |                    Candidate generator
   |                            |
   |                            v
   |                    NEXI-CUA-1 policy
   |                     |             |
   |                  action        abstain
   |                     |
   v                     v
Safety gate ------> Typed executor ------> OS / browser driver
                                           |
                                           v
                                    Re-observe and verify
```

This boundary keeps platform-specific APIs out of the learned policy. The same
model can choose an action for macOS Accessibility, Windows UI Automation,
Linux AT-SPI, or Chromium DOM elements because every adapter produces the same
schema.

## Observation protocol

`NormalizedObservation` contains:

- Platform, application, window, screen, and optional browser state.
- A list of normalized elements.
- Optional screenshot information for visual fallback.
- The active user goal.

Each `Element` can include a stable identifier, role, name, value, state,
bounds, hierarchy depth, child count, source, and interaction properties.
Adapters preserve the strongest stable identity available. The Chromium path
adds `data-nxcid` markers so actions can survive ordinary DOM mutation.

## Candidate action protocol

The runtime enumerates actions that are valid for the current observation.
Examples include:

- Element actions: click, double-click, right-click, focus, type, select, check,
  and drag.
- Browser and window actions: navigate, switch tab, new tab, close tab, back,
  forward, refresh, and switch window.
- Global actions: keypress, scroll, wait, and done.
- Visual fallback actions: coordinate click, coordinate drag, coordinate
  scroll, and text or key input.

Every action is represented by the typed `Action` schema. The policy cannot
emit arbitrary code, shell commands, or unstructured JSON.

## NEXI-CUA-1 policy

NEXI-CUA-1 is a 1,606,418-parameter goal-conditioned action ranker.

### Inputs

- Hashed character n-gram features for the user goal.
- Hashed text features for element labels and action descriptions.
- Element role embeddings.
- Action verb embeddings.
- Numeric geometry, state, hierarchy, and ordinal-position features.
- Masks identifying valid elements and actions.

### Network

1. Encode the goal.
2. Encode every normalized element.
3. Combine element text, role, and numeric features.
4. Attend from the goal to relevant elements.
5. Encode each candidate action and its target element.
6. Score all valid candidates.
7. Estimate correctness for calibration and abstention.

The model performs no runtime text generation. It returns a probability
distribution over the candidates already supplied by the runtime.

## Decision pipeline

`decide()` runs three stages, cheapest first:

1. **Semantic resolver** (`nexi_cua/policy/resolver.py`): deterministic
   resolution for unambiguous goals — an element whose full accessible name
   is contained in the goal, a valid ordinal in an explicit role ("the
   second link"), browser-tab intents, explicit key chords, and session
   commands, keyboard-shortcut phrases ("select all text" → cmd+a, mapped to
   ctrl on Windows/Linux), and semantic intents ("cancel" → the single
   Cancel/Back/Close control). Verb words inside element names or quoted
   text are ignored when detecting intent. Duplicate names resolve to the
   topmost match in reading order; fuzzy goals defer to the ranker;
   an element named "New Tab" outranks the new-tab phrase.
2. **NEXI-CUA-1 ranker**: scores candidates on goal-conditioned element and
   action encodings for fuzzy, compositional, or ambiguous goals.
3. **Abstention**: below the calibrated threshold the decision is refused.
   A decisive softmax can rescue an element pick only when its target
   shares content words with the goal, and global actions can never
   satisfy a goal that names an element interaction.

The resolver exists because exact accessible-name matches carry no model
uncertainty; it is the same hybrid pattern production UI automation uses.
Fuzzy goals still exercise the learned ranker, and nothing bypasses the
safety gate — resolver output goes through the same `Action` objects and
the same executor.

### Decision and abstention

The highest-ranked candidate is returned only when calibration or a restricted
ranking-margin rule indicates sufficient confidence. Global actions are
prevented from satisfying goals that explicitly name an element interaction.
If no action is reliable, the policy abstains.

## Semantic-first perception

The observation priority is:

1. Native accessibility or UI automation.
2. Browser DOM and accessibility state.
3. Other structured application state.
4. Local screenshot grounding.
5. Raw coordinates.

This reduces latency, memory, and visual ambiguity. A screenshot is not needed
when the runtime already knows that a visible element is a button named
`Save`.

## Drivers

### macOS

- Perception: Accessibility API.
- Input: AX actions and Quartz CGEvent.
- Capture: CGWindowList and system screen capture.

### Windows

- Perception: UI Automation through COM.
- Input: UIA patterns and SendInput.
- Capture: MSS or BitBlt-compatible capture.

### Linux

- Perception: AT-SPI, with X11 fallback where necessary.
- Input: XTest and available desktop input tools.
- Capture: MSS, grim, or scrot depending on the session.

### Chromium

- Perception: DOM, browser state, tabs, and element geometry through raw Chrome
  DevTools Protocol.
- Input: CDP DOM and Input domains.
- Identity: stable `data-nxcid` markers.

Drivers translate typed semantic actions into platform operations. They do not
contain the learned goal-selection logic.

## Local vision fallback

When semantics are missing or the goal is inherently visual, the runtime can:

1. Capture a screenshot.
2. Ask a local VLM to locate the described target.
3. Refine the result with a zoomed crop or labeled grid.
4. Re-rank semantic candidates against image regions when possible.
5. Emit a visual action only when the result clears confidence checks.

The preferred Apple Silicon path uses MLX. A llama.cpp GGUF path supports
macOS, Windows, and Linux. Optional third-party vision weights retain their own
licenses and are downloaded separately.

## Safety architecture

Safety is enforced outside the neural policy:

- Typed actions prevent arbitrary execution.
- Sensitive operations require explicit confirmation.
- Destructive shell and malicious-intent classes are blocked.
- Model confidence never grants authorization.
- `--yes` can approve confirmation-gated actions but cannot override blocked
  classes.
- The agent has a finite step budget.
- Every executed action is followed by re-observation and verification.
- The policy can abstain instead of inventing an action.

The executor is the final authorization boundary before any action reaches the
computer.

## Verification

After execution, NEXI-CUA observes the interface again and compares semantic
state. Verification can report success, failure, unchanged state, or
uncertainty. Browser URL changes, element values, selection state, focus, and
structural differences are used when available.

## Training and evaluation

Training uses generated interface structures with programmatic ground truth,
including dense layouts, ambiguous controls, positional goals, unsupported
visual attributes, and abstention examples. The repository also contains:

- A held-out synthetic semantic evaluation.
- Five captured real-web fixtures with self-labeled goals.
- Live desktop and Chromium scenarios.
- Latency and memory benchmarks.

See `STATUS.md` for exact results and their limitations.

## Extending NEXI-CUA

To support another computer-use surface:

1. Implement the normalized perception interface.
2. Implement typed action execution for that surface.
3. Preserve stable element identifiers where possible.
4. Route the adapter through the executor.
5. Add native verification and regression fixtures.

The policy does not need platform-specific branches as long as the adapter
honors the shared protocol.
