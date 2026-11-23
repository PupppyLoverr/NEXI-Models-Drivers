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
