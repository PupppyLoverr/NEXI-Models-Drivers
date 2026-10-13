# NEXI 24GB use cases

The runtime context is 4096 tokens, even though the base config advertises a larger maximum. Scope prompts to the runtime setting. These are prompt-scoping guidelines, not measured capability guarantees.

## Coding

Use for focused implementation, code review, explanations, and test planning. Provide relevant source, constraints, and expected behavior. Review and test all generated changes in the host environment.

**Limit:** split broad work into bounded changes; do not assume the model sees repository files that are not in the prompt.

## Computer use

Use to select one action from an accessibility snapshot. Provide a goal, the tree, and numbered candidate actions using the CUA evaluation format.

```text
Goal: ...
Elements:
[e0] button "Save"
[e1] link "Settings"
Actions:
1. click(e0 "Save")
2. click(e1 "Settings")
```

Return only the one-based candidate number (for example, `1`) or `NONE`. The host executes the chosen action and should refresh the tree before the next step.

**Limit:** keep each action list bounded to the current screen and task.

## Browser use

Use the same format for browser navigation and page interaction. Include URL/title and the relevant accessibility nodes; candidates may include `navigate`, `back`, `forward`, `refresh`, or tab actions.

**Limit:** do not send an entire browsing history or assume that a selected action was successful without observing the next page state.

## Tool use

Use `/v1/chat/completions` with explicit function schemas in the `tools` array. The client receives `choices[0].message.tool_calls`, validates arguments, performs the call, and returns its result.

**Limit:** review each call and its arguments; the model proposes tool calls but does not execute them.

## Chat

Chat is secondary. Use for short explanations, summaries, or questions tied to a concrete task.

**Limit:** keep conversation context within the 4096-token runtime window.

## Not suited for

- Contexts longer than the configured runtime window.
- Unreviewed execution of consequential actions, code, or external side effects.
- Image or video input; the current NEXI runtime path is text-only.
- Guaranteed correctness or unsupervised long-running agents.

Measured benchmark results will be collected in `BENCHMARKS.md` after the base evaluations.
