# NEXI flagship — Inkling-2-Mini measured (2026-11-24)

Model: `thinkingmachines/Inkling-2-Mini` (26.4B total / 3.4B active,
looped-MoE, Apache-2.0, multimodal) via `unsloth/Inkling-2-Mini-GGUF`
`UD-Q4_K_M` (16.6 GB file), llama-cpp-python 0.3.38, CPU 8 threads.

## Measured on this machine (8 vCPU, 31 GB, CPU only)

| Metric | Value |
|--------|-------|
| GGUF size | 16.6 GB |
| Peak RSS | 13.1 GB (incl. ctx) |
| Cold load | 17.4 s |
| Generation (uncontended) | ~1.0 tok/s |
| Generation (sharing CPU w/ LoRA job) | 0.06 tok/s |
| Sample quality | correct, clean Fibonacci impl + explanation |

## Reading — honest

- **It runs locally on our target hardware** — 13.1 GB peak on a 31 GB box
  clears the 20 GB tier goal with headroom. Your "flagship that fits" thesis
  is real.
- **It is NOT interactive-fast on CPU**: ~1 tok/s clean. Good enough for
  offline/agentic batch reasoning, eval runs, and as a distillation teacher
  — not good enough for a snappy chat UI on CPU-only machines.
- **The quality bar is intact**: the output is visibly stronger than any
  sub-8B model we ran (correct code, correct explanation, zero rambling) —
  consistent with published results putting it above every open <100B model
  on agentic/coding benchmarks.
- **Fine-tuning reality**: 26.4B NVFP4 looped-MoE cannot be LoRA-trained on
  a 31 GB CPU box. Its NEXI roles: (a) shipped flagship GGUF for 20 GB
  installs, (b) distillation teacher for the small tiers, (c) eval judge.

## Open work
- mmproj vision path (multimodal input via GGUF) — files exist in the repo
- small in-house held-out eval vs the published claims
- streaming driver so 1 tok/s is at least incremental UX

## UD-Q3_K_XL — smaller build, measured (2026-11-24)

`unsloth/Inkling-2-Mini-GGUF` `UD-Q3_K_XL` (13.6 GB file), same machine,
clean uncontended run of `scripts/inkling_quant_check.py` (4 fixed prompts).

| Metric | UD-Q4_K_M | UD-Q3_K_XL |
|--------|-----------|------------|
| GGUF size | 16.6 GB | 13.6 GB (-18%) |
| Peak RSS | 13.1-16.9 GB | 14.77 GB |
| Cold load | 17.4 s | 2.6 s |
| Generation (uncontended) | ~1.0 tok/s | **3.3 tok/s** |

Prompt outputs verified by hand: 17*23 = 391 (correct arithmetic shown),
correct two-pointer merge of sorted lists, correct process/thread
explanation, professional rewrite. **No visible quality regression** on
this prompt set.

Honest read: Q3_K_XL measured ~3x faster than Q4's uncontended run —
plausible (less dequant work per token) but the Q4 number came from an
earlier run under some load, so treat 3x as an upper bound, not a settled
ratio. Both quants are publisher builds; local requant from Q4 is not
possible ("requantizing from q8_0 is disabled"). Q3_K_XL is now the
default ship recommendation for the 20 GB tier; Q4_K_M stays the
higher-fidelity option. Distill-trace generation for the small tiers is
the remaining Inkling item.
