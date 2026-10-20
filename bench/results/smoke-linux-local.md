# dove-driver benchmark: smoke-linux-local

- Harness commit: `6f03c05`; generated 2026-10-20T22:35:09Z
- Runs per task: 3; step limit: 30; model(s): `scripted-stub`
- Values are means over tasks with a 95% bootstrap CI (tasks resampled, 10,000 draws).

> **Smoke run with the scripted stub model.** Token counts are estimates of the requests a model would have sent; success reflects the stub's fixed plan. These numbers test the harness. They do not rank drivers, and no claim is made from them.

- B is the dove-driver/main build (a41d24f; this branch adds only bench/), i.e. the same driver code as A: there is no previous dove-driver release yet.
- C is stock cua-driver 0.37.0 built from the unmodified upstream branch (47cd531) with bench/scripts/build-stock-cua-driver.sh.
- Display stack: Xvfb + openbox + AT-SPI 2.52, GTK 3 task windows under Python 3.12 PyGObject.
- Configuration **G** (dove-driver, this release, with the W9 local grounder (act {goal})) was not run: driver offers no act tool.

## local

Environment: os `Linux-6.18.44-fc-v139-x86_64-with-glibc2.39`, display `:77`, toolkit `GTK3 via AT-SPI`

| Config | Model | Tasks×runs | Success | Tokens/task | Obs. tokens/task | Wall time/task | Model time | Driver time | Round trips | Semantic share | Screenshots | Driver errors/100 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | `scripted-stub` | 4×3 | 100.0% [100.0%, 100.0%] | 171,371 [171,316, 171,462] | 211 [181, 262] | 2.67 s [1.81, 3.65] | 0.01 s [0.01, 0.01] | 2.65 s [1.79, 3.64] | 2 [2, 2] | 100.0% [100.0%, 100.0%] | 0.0 | 0.0 |
| B | `scripted-stub` | 4×3 | 100.0% [100.0%, 100.0%] | 171,371 [171,316, 171,462] | 211 [181, 262] | 2.66 s [1.80, 3.66] | 0.01 s [0.01, 0.01] | 2.65 s [1.79, 3.65] | 2 [2, 2] | 100.0% [100.0%, 100.0%] | 0.0 | 0.0 |
| C | `scripted-stub` | 4×3 | 100.0% [100.0%, 100.0%] | 171,371 [171,316, 171,462] | 211 [181, 262] | 2.67 s [1.86, 3.61] | 0.01 s [0.01, 0.01] | 2.66 s [1.85, 3.60] | 2 [2, 2] | 100.0% [100.0%, 100.0%] | 0.0 | 0.0 |
| D | `scripted-stub` | 4×3 | 100.0% [100.0%, 100.0%] | 132,375 [113,095, 170,842] | 410 [359, 465] | 3.71 s [2.03, 6.16] | 0.01 s [0.01, 0.01] | 3.69 s [2.02, 6.14] | 6 [5, 8] | 53.6% [23.8%, 83.3%] | 1.0 | 0.0 |

Configurations: **A** dove-driver, this release (tree-first defaults, run_steps); **B** dove-driver, previous release (its defaults); **C** stock cua-driver, latest upstream release (its defaults); **D** dove-driver, screenshot-only (tree off, pixel actions only: the vision baseline).

Tool latency (ms, p50 / p95):

| Config | Tool | Calls | p50 | p95 |
|---|---|---|---|---|
| A | `list_windows` | 12 | 13.0 | 17.2 |
| A | `run_steps` | 12 | 2002.3 | 3520.3 |
| B | `list_windows` | 12 | 13.4 | 19.6 |
| B | `run_steps` | 12 | 2005.7 | 3513.3 |
| C | `list_windows` | 12 | 14.1 | 23.3 |
| C | `run_steps` | 12 | 1975.8 | 3500.2 |
| D | `click` | 33 | 342.3 | 1417.1 |
| D | `get_window_state` | 12 | 32.8 | 41.7 |
| D | `list_windows` | 12 | 13.4 | 20.4 |
| D | `scroll` | 3 | 1436.7 | 1448.4 |
| D | `type_text` | 12 | 952.0 | 1038.9 |

## Release gates

| Suite | Model | Gate | Status | Detail |
|---|---|---|---|---|
| local | `scripted-stub` | success | PASS | A 100.0% vs B 100.0% (overlapping CIs) |
| local | `scripted-stub` | tokens/task | PASS | A 171371 vs B 171371 (-0.0%) |

## Claims

- local, A with `scripted-stub`: no claim (stub model with estimated tokens; success CI does not clear C's; success CI does not clear D's; more tokens/task than D).

No "#1" claim is made from this run.
