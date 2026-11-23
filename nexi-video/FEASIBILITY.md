# NEXI-Video — honest feasibility report (2026-11-24)

Question: can a video-generation model run locally on a CPU-only box
(8 vCPU, 31 GB) — the same class of hardware our users have?

## What exists (open weights, Nov 2026)

| Model | Params | Real hardware req | Verdict for us |
|-------|--------|-------------------|----------------|
| LTX-Video / LTX-2.x (Lightricks) | 2B–13B DiT | marketed "consumer GPU" (≥8–12 GB VRAM); CPU support = days-per-clip | too heavy |
| Wan 2.1/2.2 (Alibaba) | 1.3B–14B | 1.3B T2V runs on ~8 GB VRAM; CPU ≈ hours/frame-minute | too heavy |
| HunyuanVideo (Tencent) | 13B | datacenter-class | no |
| CogVideoX-2B | 2B | the lightest mainstream; still minutes/hours per clip on CPU | too heavy |
| AnimateDiff / SD-turbo video hacks | <1B | ancient, poor quality | dead end |

## The physics, honestly

A 2B DiT at ~25 steps over a 2 s clip ≈ the FLOPs of ~50 image generations.
Our measured image floor (BK-SDM, 256px, 15 steps, CPU) is tens of seconds
per *frame-sized* image. A coherent video needs 25–50 frames' worth of
temporal attention on top. On this CPU that is **minutes-to-hours per
second of video**, not realtime, not interactive, and it would not beat any
published benchmark on quality either.

## What NEXI-Video is, then

- **Not shipped as a generated-video model tonight.** Claiming it would be
  dishonest — no open weights family can beat benchmarks AND run on a 31 GB
  CPU box today.
- **Shipped as a spec + harness:** the tier table above, the measurement
  plan (LTX-2B distilled on the biggest box we support; GGUF-style quant
  when a runtime exists), and a driver stub reserved for it.
- **Real path to "top at release":** wait for a distilled 2–4B video model
  with a CPU-capable runtime (LTX is closest trajectory), or ship
  NEXI-Video as GPU-optional: CPU generates storyboard keyframes via
  NEXI-Image + frame interpolation (filnet/RIFE-style), measured and
  labelled exactly as that — "keyframes + interpolation", not diffusion
  video.

## Open work
- re-evaluate when LTX/Wan publish sub-2B distilled CPU-realtime variants
- keyframe+interp prototype is one bench away if the user wants it
