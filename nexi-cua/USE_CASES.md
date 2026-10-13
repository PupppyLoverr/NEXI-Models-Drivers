# NEXI-CUA Use Cases

NEXI-CUA works best when a goal names something on the screen and the app
exposes accessibility or DOM data. Each item below names the stage that
handles it.

## Verified live in this repository (macOS + Chrome, recorded demos)
| Use case | What happens | Path |
|---|---|---|
| Calculator arithmetic (7×8=56) | Real AX button presses, result read back | macOS AX + CGEvent |
| TextEdit writing + Bold | Real keystrokes, toolbar toggle, verified via AXValue | macOS AX |
| Wikipedia research | Search field, per-character typing, OS cursor travels to the article link, scroll | Chromium CDP |
| DuckDuckGo search → result | VLM grounds the search box, then types and clicks the first result | Vision fallback |
| Visual target ("the globe logo") | Qwen2-VL grounding followed by an OS click | Vision fallback |

## Supported workflows
- **Browser automation:** navigate, search, follow named or ordinal links ("the second link"), fill forms, use dropdowns, check boxes, and handle tabs (new, close, switch by title), back/forward/refresh.
- **Desktop apps:** click named buttons and menu items, type into fields, use keyboard chords ("press cmd+s"), scroll, drag between named items, double-click and right-click.
- **Accessibility assistant:** voice or text goals become exact accessible-name actions, with no screenshots needed.
- **QA and regression testing:** deterministic actions plus post-action verification (`VerifyResult`) on every step.
- **Data entry:** `type "X" into the <field>` with argument extraction that preserves case.
- **Embedding in other agents:** `observe/decide/act/verify` API, `nexi-cua serve` HTTP server, and a typed `Action` JSON contract. Any planner (local LLM, script, MCP tool) can call it.

## Safety-gated by design
- These always need confirmation: purchases, payments, transfers, sending or posting, deletion, account and security changes, software installs, permission grants.
- These are always blocked, even with `--yes`: destructive shell commands, malware, phishing or credential-theft intent, and attempts to bypass safety controls.
- Unanswerable or visual-only goals ("click the glowing purple button") lead to abstention, not a guess.

## Not a good fit (yet)
- Long multi-application projects that need open-ended planning. Pair NEXI-CUA with a planner.
- Canvas or game UIs with no accessibility data. The vision fallback works there but is slow.
- Production use on Windows or Linux before native verification (see STATUS.md).
