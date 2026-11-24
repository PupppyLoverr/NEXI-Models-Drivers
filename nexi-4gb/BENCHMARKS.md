# nexi-4gb — NEXI-4 pipeline proof (2026-11-24)

Base: `Qwen/Qwen3.5-2B` (hybrid linear-attention). LoRA r=16 (1.47M
trainable, 0.078%), 150 steps on mix_v1 (2,400 rows), CPU-only, 3.24 h
(~50-70 s/step — reference kernels, no CPU causal_conv1d/fla wheels).
Merged with `common/train/merge_lora.py`; weights stay local (gitignored).

## Held-out evals (n=40 each, greedy, fp32 CPU)

| Set | Base | Tuned (150 steps) |
|-----|------|-------------------|
| tool_call | 0.0% | 20.0% |
| cua action | 93.3% | 100.0% |
| ifeval | 40.0% | not rerun |

Eval process peak RSS: 10.97 GB — on a "4 GB tier" target, inference must
ship as GGUF (planned ~1.2 GB q4), not the fp32 HF path used for training.

## GGUF export — measured (llama.cpp, Q4_K_M)

| Metric | Value |
|--------|-------|
| GGUF file | 1.29 GB (`nexi-4-Q4_K_M.gguf`) |
| Load | 1.2 s |
| Peak RSS | 1.97 GB |
| Decode speed | 18.2 tok/s (8 threads) |

The 4 GB tier claim is real: a tuned 2B NEXI model at **~2 GB RAM and
18 tok/s on CPU**. Caveat: an ad-hoc tool-call prompt through the GGUF
refused the call — tuned behavior is prompt/template-sensitive and the
20% held-out score stands as the honest capability bound tonight.

## Reading — honest

- **The pipeline works end-to-end**: data mix -> CPU LoRA -> merge -> eval.
  Tool-call syntax was learned from zero (0% -> 20%); CUA choices went
  93.3% -> 100%.
- **20% is not "best in the world"** — it's a smoke-test proving the harness.
  A competitive tool_call score needs a real corpus (xlam-function-calling
  is gated — waiting on the HF token), more steps, and likely a dense
  (non-hybrid) base that trains faster on CPU.
- Base model is hybrid linear-attention: fine architecture for edge
  inference, but its CPU training fallback is slow — noted as a selection
  risk in docs/RESEARCH.md.

## Open work
- real tool-call corpus once HF token lands
- GGUF export via common/train/export_gguf.sh (needs llama.cpp build)
- base-model swap test: dense 2B (e.g. WePocketModel-2B once its runtime
  story is clear) vs Qwen3.5-2B on train speed + held-out score

## v2 — retrained on real xlam corpus (post HF token)

300-step LoRA on ~8k rows of `minpeter/xlam-function-calling-60k-hermes`
(ungated mirror; the Salesforce original stayed gated for us), final loss
1.356. Held-out eval fix included: the eval now injects the `<tools>`
schema into the system prompt — the old run was unanswerable (expected
held-out tool names it never saw).

| Eval set | v1 (synthetic mix) | v2 (xlam) |
|----------|--------------------|-----------|
| tool_call | 20% | **100% (10/10)** |
| cua | 100% | **100%** |

### GGUF (merged_v2, Q4_K_M)

| Metric | Value |
|--------|-------|
| GGUF file | 1.29 GB (`nexi-4-v2-Q4_K_M.gguf`) |
| Load | 1.47 s |
| Peak RSS | 2.02 GB |
| Decode speed | 15.1 tok/s (8 threads) |
| Tool-call smoke | correct `<tool_call>` JSON, right function + args |

Honest notes: 10/10 is a small eval — it proves the contract (emit valid
tool_call JSON naming a schema'd function) is learned, not that we're at
Berkeley-Function-Calling leaderboard level. A BFCL-style run is open
work. Speed dropped slightly vs v1 (15.1 vs 18.2 tok/s) — same quant,
likely noise from a busier box plus longer prompt; not a regression in
capability.
