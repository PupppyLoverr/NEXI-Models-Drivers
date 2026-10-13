# NEXI 8GB use cases

Scope prompts to the 4096-token runtime context. These are prompt-scoping guidelines, not measured capability guarantees.

## Coding

Use for focused changes, function generation, explanations, or a small test update. Include the relevant code and expected behavior; run generated code and tests in the host environment.

**Limit:** keep the request to a small code area and provide only the context needed for it.

## Computer use

Use to choose one next action from a current accessibility snapshot. Provide the goal, accessibility tree, and numbered candidate actions as in the CUA evaluation data.

```text
Goal: ...
Elements:
[e0] button "Save"
[e1] link "Settings"
Actions:
1. click(e0 "Save")
2. click(e1 "Settings")
```

Return only the one-based candidate number (for example, `1`) or `NONE`; the host performs the selected action.

**Limit:** use compact trees and split longer interactions into short steps.

## Browser use

Use the same accessibility-tree format for page navigation and browser controls. Include the goal and current page context; candidates may include `navigate`, `back`, `forward`, `refresh`, or tab actions.

**Limit:** avoid passing a whole site or long browsing history in one request.

## Tool use

Use `/v1/chat/completions` with an OpenAI-compatible `tools` array. Read the returned function name and JSON arguments from `choices[0].message.tool_calls`; the calling application executes the function and returns its result.

**Limit:** small schemas and a few related calls; validate arguments before execution.

## Chat

Chat is secondary. Use it for concise questions, summaries, and explanations with a clear context.

**Limit:** split long conversations or documents into smaller prompts.

## Not suited for

- Prompts that exceed the configured context or require preserving a large repository state.
- Autonomous execution of consequential actions.
- Image or video input; the current NEXI runtime path is text-only.
- Unreviewed code changes or guaranteed correctness.

Measured benchmark results will be collected in `BENCHMARKS.md` after the base evaluations.
