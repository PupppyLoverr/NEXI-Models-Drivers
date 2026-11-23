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
