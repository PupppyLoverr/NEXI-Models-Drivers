# NEXI 16GB use cases

The runtime context is 4096 tokens. Scope prompts to that limit; these are prompt-scoping guidelines, not measured capability guarantees.

## Coding

Use for focused implementation, code explanation, and small test changes. Include the relevant files or excerpts, constraints, and expected behavior; run generated code and tests in the host environment.

**Limit:** split broad changes into smaller tasks and include only relevant repository context.

## Computer use

Use to choose one action from a current accessibility snapshot. Provide a goal, the accessibility tree, and numbered action candidates in the CUA evaluation format.

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

**Limit:** keep trees and action lists compact; refresh the snapshot after actions that change the page.

## Browser use

Use the same format for browser navigation and page interaction. Include the current URL/title when available and a short list of candidate actions, such as `navigate`, `back`, `refresh`, or a tab action.

**Limit:** summarize long pages into the relevant accessibility nodes rather than sending an entire browsing session.

## Tool use

Use `/v1/chat/completions` with JSON function schemas in the `tools` array. The host receives `choices[0].message.tool_calls`, validates the name and arguments, executes the function, and returns the result.

**Limit:** use a small set of related functions per request; the model does not execute the functions itself.

## Chat

Chat is secondary. Use it for concise explanations, summaries, and questions tied to a defined task.

**Limit:** avoid long conversations that consume the runtime context.

## Not suited for

- Contexts longer than the configured runtime window.
- Unreviewed execution of consequential actions or code.
- Image and audio input; the current NEXI server path is text-only.
- Guarantees of correctness or autonomous end-to-end work.

Measured benchmark results will be collected in `BENCHMARKS.md` after the base evaluations.
