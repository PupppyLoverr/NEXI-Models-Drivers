# NEXI 4GB use cases

Scope these tasks to the 2048-token runtime context. These are prompt-scoping guidelines, not measured capability guarantees.

## Coding

Use for short functions, explanations, and focused edits with the relevant code and expected behavior included. Ask for one change at a time and run generated code and tests in the host environment.

**Limit:** short snippets and single-file changes; avoid broad repository context.

## Computer use

Use to choose one next action from a current accessibility snapshot. Provide the goal, the accessibility tree, and numbered candidate actions in the same form as the CUA evaluation data.

```text
Goal: ...
Elements:
[e0] button "Save"
[e1] link "Settings"
Actions:
1. click(e0 "Save")
2. click(e1 "Settings")
```

The expected output is only the one-based candidate number (for example, `1`) or `NONE`. The host performs the selected action.

**Limit:** compact trees and one action per request.

## Browser use

Use the same accessibility-tree format for page navigation and browser controls. Include the goal and the current page context; candidate actions may include `navigate`, `back`, `forward`, `refresh`, or tab actions.

**Limit:** short page snapshots and one navigation or interaction at a time.

## Tool use

Use `/v1/chat/completions` with an OpenAI-compatible `tools` array. The model returns the function name and JSON arguments in `choices[0].message.tool_calls`; the calling application executes the function and returns its result.

**Limit:** simple, single-step calls with a small schema. Validate arguments before execution.

## Chat

Chat is secondary. Use it for short questions, summaries, or explanations alongside a clear context.

**Limit:** keep prompts concise and within the runtime context.

## Not suited for

- Long prompts or multi-step plans that exceed the configured context.
- Autonomous execution of destructive, financial, or otherwise consequential actions.
- Image or video input; the current NEXI runtime path is text-only.
- Unreviewed code changes or guaranteed correctness.

Measured benchmark results will be collected in `BENCHMARKS.md` after the base evaluations.
