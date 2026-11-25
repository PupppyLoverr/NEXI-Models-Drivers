# Attempting frontier ("Opus-level") capability with Inkling-2-Mini

Honest engineering assessment + what is actually being done. Written
2026-11-25. Nothing in here is marketing.

## What "Opus level" would mean operationally

Matching frontier proprietary models across reasoning, math, coding, and
general knowledge — not one benchmark. By every public signal, no open
weights model is there today; Inkling-2-Mini is closest-in-class on
agentic coding specifically (SWE-bench Verified 79.2% `P`, inside the
range frontier models publicly report).

## What is physically possible on this machine (8 vCPU, 31 GB, no GPU)

| Lever | Feasible here? | Expected gain |
|---|---|---|
| Post-train the 26B weights (RL/SFT) | NO — needs GPU cluster | the real lever |
| imatrix/quality quants | YES (hours of CPU) | small but real quality at same size |
| Reasoning distillation into small tiers | YES (running) | small tiers inherit frontier-adjacent behavior patterns |
| Reasoning-aware inference harness | YES | measured: the 512-token eval artifact proved format scores are harness-sensitive |
| Best-of-n / self-consistency sampling | YES (slow: 1.8 tok/s) | +points on reasoning tasks at n× cost |
| Costed plan for the GPU post-training run | YES | the honest answer to "opus 5 level" |

## What is being executed now, in order

1. **Reasoning distillation program** — Inkling generates reasoning traces
   across coding/math/agentic/tool-use prompts (`common/data/inkling_traces_v2.jsonl`);
   NEXI-4 v3 trains on xlam + these traces overnight. Measured after with
   the execution-verified suite.
2. **imatrix quantization** — importance-matrix quants measurably beat naive
   quants at the same bit-width on perplexity. CPU cost: hours. Queued after
   the LoRA run (one heavy job at a time on 8 cores).
3. **Eval expansion** — bigger exec-verified suite so capability claims are
   numbers, not adjectives.

## The GPU post-training plan — the real "opus attempt"

If the decision is made to spend compute money:

1. **Base**: Inkling-2-Mini (26.4B looped-MoE, Apache-2.0 — commercially usable).
2. **Method**: distillation SFT on frontier-model outputs is legally
   fraught (ToS); the clean path is RL on verifiable tasks (code execution,
   math answers) — exactly the tasks our suite already automates, scaled up.
   Tinker (Thinking Machines' own tuning service) supports custom RL loops
   and is the natural fit for their architecture.
3. **Rough cost shape**: a meaningful RL/SFT run on a 26B MoE is hundreds
   to low-thousands of GPU-hours depending on ambition — order-of-magnitude
   $1k-10k+ at market rates. Exact quote requires scoping.
4. **What we already built for it**: the execution-verified reward harness
   (this repo's eval suite), the GGUF export pipeline, the measured
   deployment path — the outputs of a successful run plug straight in.

## What we will not claim

- That quantization or distillation makes a 26B into a frontier model.
- Any benchmark comparison to specific proprietary versions we cannot
  verify with published data.
