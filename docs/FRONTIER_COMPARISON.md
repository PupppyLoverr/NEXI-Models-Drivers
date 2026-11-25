# NEXI text models — benchmark comparison

Two kinds of numbers in this doc, always labeled:

- `M` = **measured by us** on this machine (8 vCPU, 31 GB, CPU-only), raw
  outputs in `common/eval_text/results_*.json`, scoring deterministic
  (code execution / exact match / JSON parse).
- `P` = **published by the model's own team** — cited, not verified by us.
  Treat as directional, not proof.

## 1. Our measured eval — NEXI text suite v1 (12 tasks, deterministic)

Execution-verified coding (4), exact-answer math/reasoning (3),
format/instruction following (3), knowledge (2). Temperature 0.
Raw outputs and scorer: `common/eval_text/`.

| Model | Total | Coding | Math | Format | Knowledge | Speed |
|---|---|---|---|---|---|---|
| NEXI-20 (Inkling-2-Mini Q3_K_XL) | **9/12** `M` | **4/4** | **3/3** | 0/3 see caveat | **2/2** | 1.79 tok/s `M` |
| NEXI-4 v2 (Qwen3.5-2B+xlam, Q4_K_M) | **9/12** `M` | 3/4 | 1/3 | **3/3** | **2/2** | ~15 tok/s uncontended `M` |

**Caveat on Inkling format scores — measured, then explained:** Inkling is a
reasoning model that emits long thinking before the answer; with the suite's
512-token cap the thinking consumed the entire budget on all 3 format tasks
(the raw outputs show correct reasoning, truncated before the answer). This
is a harness artifact, not a capability zero. Re-run with a fair token
budget reported below when complete. What IS honestly proven by the suite:
Inkling sweeps coding 4/4 (including the CSV-parsing task the 2B failed by
treating CSV text as a filename) and math 3/3 (the 2B got 1/3) — the class
gap between a 26B looped-MoE and a 2B specialist is real and visible in
execution-verified outputs, not vibes.

nexi-4 v2 detail: fails multi-step arithmetic/percentage reasoning (1/3 math)
but is perfect on JSON/tool-call format (3/3) — consistent with its design
as a tool-calling specialist, not a reasoner.
| NEXI-4 v2 (Qwen3.5-2B+xlam, Q4_K_M) | _running_ | | | | | ~15 tok/s `M` |

This is a small suite — it ranks our own models against each other and
gives hard evidence of what they can/can't do. It is NOT a substitute for
the big public benchmarks below.

## 2. Agentic coding — the benchmark category that matters most for NEXI

| Model | SWE-bench Verified | DeepSWE | Source |
|---|---|---|---|
| **NEXI-20 base (Inkling-2-Mini)** | **79.2%** | **48.2%** | `P` (Thinking Machines) |
| Qwen3.8-27B (best open <30B alt) | 77.8% | 42.2% | `P` |
| Gemma-4-31B | — | 0.3% | `P` |
| Nemotron-3.5-Super-VL | — | 24.7% | `P` |
| NEXI-4 v2 (2B specialist) | not meaningful at 2B | — | honest note |

**Frontier comparison, stated honestly:** at time of writing we could not
verify public benchmark data for the exact versions named ("Opus 5.5",
"GPT 6.2 Sol", "Gemini 4 Neon") — no published, checkable scores were
found. What is verifiable: frontier-class proprietary models have
publicly reported SWE-bench Verified scores in the 70-80%+ range over
the last year. Inkling-2-Mini's 79.2% `P` sits inside that range on this
one benchmark — which is exactly why we chose it as the flagship. That
does NOT make it "frontier overall": proprietary frontier models lead it
broadly in reasoning, math, multimodal and general knowledge, and the
gap there is real.

## 3. Where each NEXI text model actually stands

| Model | Honestly closest to | Verdict |
|---|---|---|
| NEXI-20 (Inkling) | Best open <100B on agentic coding — beats Qwen3.8-27B `P`; frontier-adjacent on SWE-bench Verified specifically | **#1 open in class** `P`, smallest measured local build `M` |
| NEXI-4 v2 | Qwen3.5-2B + xlam tool training | #1 claim limited to: measured smallest tool-calling model with proven output contract `M`; BFCL-scale open |

## 4. The path to frontier-level — honest engineering assessment

What it would actually take, in order of leverage:

1. **Post-training Inkling at scale** — RL/distillation on GPU clusters
   (Tinker or rented H100s). This is a compute-money decision
   (hundreds-thousands of GPU-hours), not something any CPU box can do.
2. **Distillation down** — what we CAN do here: Inkling teaches the 4/8/16
   GB tiers; traces pipeline already exists (`nexi-inkling-traces`).
3. **Better evals** — BFCL-scale tool_call, OSWorld-mini, bigger exec-verified
   suites: the only way any "#1" claim becomes proof rather than marketing.

## 5. What we will NOT do

- Claim parity with frontier proprietary models based on one benchmark.
- Publish benchmark numbers we didn't measure or can't cite.
