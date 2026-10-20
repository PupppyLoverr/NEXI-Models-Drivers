# Benchmark sources (W8)

Pinned upstream task indexes, copied unchanged into `upstream-index/`. Subsets in `subsets/*.json` are drawn from
these and change only with a harness version bump.

| Suite | Repo | Commit | License | Tasks in index |
|---|---|---|---|---|
| OSWorld-Verified | xlang-ai/OSWorld | `b138d348256078fa634fc3b73567a7337c793e6b` (the commit upstream cua-bench's `tasks/osworld` pins) | Apache-2.0 | 369 (`test_all`), 361 without Google Drive (`test_nogdrive`), 26 infeasible |
| Windows Agent Arena | microsoft/WindowsAgentArena | `6d39ed88c545a0d40a7a02e39b928e278df7332b` | MIT | 154 (`test_all`) |
| MacArena | MacPaw/MacArena | `dcdc7d366da12641578ab90f085d69db91651c58` | MIT for MacArena's own code and tasks; its `osworld/` ports are Apache-2.0 and `macosworld/` tasks CC BY-NC 4.0 | 421 (`machine_0_test.json`): 49 MacArena-native, 151 from macOSWorld, 221 ported from OSWorld |

## macOS suite decision

MacArena **has** a public task set (checked 2026-10-20: github.com/MacPaw/MacArena, arXiv 2606.06560, VM image on
Hugging Face for UTM on Apple Silicon). So the macOS suite is MacArena, not macOSWorld. The ~40-task subset should
lean on the 49 MacArena-native and the macOSWorld-derived tasks, since the OSWorld ports overlap the Linux suite.

## Harness starting point

Upstream trycua/cua `libs/cua-bench` (MIT) already has `tasks/osworld` (BenchAdapter: OSWorld's own server on
:5000 does setup and evaluation; the agent acts through the driver) and `tasks/winarena_adapter`. Reuse the
design: the suite's own controller for setup and checking, the driver for every agent action. Read through
`gh api`, never cloned.
