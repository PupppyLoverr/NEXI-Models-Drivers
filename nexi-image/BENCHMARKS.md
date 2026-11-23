# nexi-image benchmarks

Measured on this machine: 8 vCPU, 31 GB RAM, CPU only. 2026-11-24.
Raw JSON in `results/bk_sdm.json`, sample outputs `results/bench_*.png`.

## Engine: BK-SDM-small (`nota-ai/bk-sdm-small`, 0.76B UNet, SD-1.5 arch)

fp32 via diffusers 0.43, 256x256, 15 steps, 3 prompts.

| Metric | Value |
|--------|-------|
| Peak RSS | 3,380 MB |
| Cold load | 45.6 s |
| Time per image | 169 s mean (164.5 / 165.9 / 175.4) |
| Output | 3 PNGs (see results/): 1 clearly on-prompt (mountain lake), 1 partial (robot+library), 1 prompt-miss (apple -> wood texture) |

## Reading — honest

- **It works and fits easily** in the 31 GB budget (3.4 GB peak); prompt
  adherence is mixed at this size/steps (see table).
- **It is slow**: ~3 min per 256px image on 8 CPU cores. Usable for
  "generate and wait" product flows; not usable for interactive generation.
- **Quality**: BK-SDM-small is a compact student model and it shows — of
  the 3 bench prompts, one rendered well, one partially, one missed the
  subject entirely. It is visibly below SDXL/FLUX-tier quality. We do not
  claim to beat any quality benchmark tonight; that claim requires a
  preference eval and a bigger tier (FLUX.2 Klein 4B is the documented
  upgrade path, but it is GPU-realistic, not CPU-realistic).
- **Footprint claim we CAN make**: a fully-local image generator at ~3.4 GB
  RAM total on CPU with no GPU, no API, no cost per image — the right
  default for the low-RAM tier of the ecosystem.

## Open work
- ONNX or torch.compile path for CPU speedup (est. 1.5–3x, unmeasured)
- distillation (LCM/Turbo-style) for step reduction: 15 -> 4 steps would
  put CPU generation near ~45 s — plausible, untested here
- quality eval vs published open image models
- FLUX.2 Klein tier driver for GPU-capable installs
