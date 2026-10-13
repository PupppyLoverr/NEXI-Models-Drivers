# NEXI-CUA Benchmarks

Every NEXI-CUA number below was measured on this repository (Apple Silicon
arm64, macOS, torch 2.14.1) at v0.4.0. Reproduce with the listed command.

## NEXI-CUA measured results

| Metric | Result | Command |
|---|---|---|
| Captured real-web action accuracy (5 pages, 72 goals) | **98.6% (71/72)**, identical CPU and MPS | `python -m nexi_cua.eval.real_eval` |
| Unanswerable-goal abstention (same suite) | **10/10** | same |
| Real-web accuracy before semantic resolver (v0.3.1) | 51.4% CPU / 48.6% MPS | historical, see STATUS.md |
| Held-out synthetic accuracy (2000 screens, v3), full pipeline | **98.8%** answerable | `python -m nexi_cua.eval.semantic_eval` |
| Same, learned ranker alone (no resolver) | 92.1% (87.9% before v0.4.0 training run) | `python -m nexi_cua.eval.semantic_eval --ranker-only` |
| Synthetic unanswerable abstain recall | 0.90 full pipeline / 0.92 ranker-only | same |
| Decision latency, real 357-element page | p50 25.7 ms, p99 28.1 ms | `nexi-cua bench` |
| Decision latency, typical screen | ~12 ms | `nexi-cua bench` |
| Cold model load | ~45 ms | `nexi-cua bench` |
| Policy size | 1.6M params, 6.29 MB | `weights/nexi-cua-1.pt` |
| Peak RSS (policy + PyTorch) | ~458 MB | `nexi-cua bench` |
| LLM tokens per semantic action | 0 (no text generation) | by construction |
| Vision fallback (MLX Qwen2-VL-2B 4-bit) | ~6 s per grounding query | `nexi-cua doctor` + demos |
| Recurring cost | $0, fully local | — |

Per-verb (synthetic, full pipeline): 1.0 on every verb except click 0.97,
focus 0.97 and type 0.996. Scored against the generator's recorded answers
(v0.4.0 fixed a scorer bug; the v0.3.x 89.2% was scored the old way).

## Comparison with published systems

**Read this first:** these benchmarks are **not like-for-like**. The
NEXI-CUA suite measures single-step action selection on captured pages.
OSWorld and WebArena measure complete multi-step tasks in live
environments, which is much harder. NEXI-CUA has **not yet been run on
OSWorld, WebArena, BrowserGym or ScreenSpot**, so it has no score there.
That gap is the next milestone, and nobody should read this table as a
ranking.

| System | Type | Runs locally | Per-action LLM tokens | Published result | Source |
|---|---|---|---|---|---|
| **NEXI-CUA v0.4.0** | 6.3 MB ranker + semantic resolver + native/CDP drivers | Yes, $0 | 0 | 98.6% single-step on own 72-goal real-web suite, 98.8% held-out synthetic; ~12–26 ms/decision; OSWorld: not yet run | this repo |
| Qwen-CUA (Qwen + XLang) | screenshot-driven VLM agent | open weights, large GPU | thousands (image + reasoning) | 86.2% OSWorld-Verified | github.com/xlang-ai/Qwen-CUA |
| Claude Opus 4.8 | frontier cloud model | No (paid API) | thousands | 83.5% OSWorld-Verified; 20.6% OSWorld 2.0 (500 steps) | arxiv.org/html/2606.29537 |
| OSWorld launch baseline (2024) | best LLM/VLM agent at release | varies | thousands | 12.24% OSWorld (humans 72.36%) | os-world.github.io |
| Cua (trycua) | sandbox + driver framework, not a model | sandbox | depends on attached model | n/a (infrastructure) | cua.ai |
| Qua (qua.dev) | team AI workspace, not a computer-use agent | — | — | n/a | qua.dev |

### Where NEXI-CUA leads today (measured)
- Latency: tens of milliseconds per decision, compared with seconds per step for VLM agents.
- Cost and privacy: 0 tokens and $0. Nothing leaves the device.
- Footprint: a 6.3 MB policy, compared with multi-GB VLMs.
- Safety: deterministic confirm/block gates that sit outside the model, plus abstention on unanswerable goals (10/10).

### Where NEXI-CUA does not lead (yet)
- Long-horizon multi-app planning: NEXI-CUA picks one action per step from an explicit goal. It is not a general planner.
- Purely visual interfaces with no accessibility or DOM data: these fall back to a 2B VLM, which is slower and weaker than frontier models.
- Public benchmark evidence: there are no OSWorld, WebArena or ScreenSpot runs yet. Windows and Linux drivers are implemented but haven't been natively verified.

## Path to a public #1 claim
1. Run OSWorld-Verified and OSWorld 2.0 with NEXI-CUA as the executor and policy.
2. Run BrowserGym/WebArena and ScreenSpot-Pro grounding.
3. Verify the Windows (UIA) and Linux (AT-SPI) drivers natively.
4. Publish traces and failures for every release.
