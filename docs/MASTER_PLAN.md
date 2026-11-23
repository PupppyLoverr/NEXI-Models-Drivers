# NEXI master plan

Status: scaffold + research (v0). Training: not started.
Last updated: 2026-11-24.

## Naming and lineup

Everything ships under the NEXI name. Text tiers are named for the machine RAM
they run on; the multimodal flag means image and video input, not generation.

| Model | RAM target | Planned base | Multimodal | Quant target |
|---|---|---|---|---|
| NEXI-4 | 4 GB | Qwen3.5-2B (stretch: Qwen3-VL-2B or LFM3-VL-2B) | stretch | Q4_K_M GGUF ≤ ~2.4 GB total |
| NEXI-8 | 8 GB | Qwen3-VL-4B | yes | ≤ ~4.8 GB |
| NEXI-16 | 16 GB | Qwen3-VL-8B (alt: Gemma 4 12B) | yes | ≤ ~9.6 GB |
| NEXI-20 | 20 GB | gpt-oss-20b or Gemma 4 26B-A4B | check | ≤ ~15 GB |
| NEXI-28 | 28 GB | Qwen3.6-35B-A3B (MoE) | check | ≤ ~21 GB |
| NEXI-32 | ≤32 GB, goal ~21 GB | Qwen3.6-35B-A3B at higher quant, or Qwen3.8-27B dense | check | ~20–21 GB incl. KV |
| NEXI-Voice-TTS | <1 GB | Kyutai Pocket TTS tiny family (1.9M–18.2M) | — | ONNX/CPU |
| NEXI-Voice-STT | <2 GB | VibeASR-BitNet vs FUTO asr4all-s, decided by measurement | — | quant native |
| NEXI-S1 | <1 GB | option-attention scorer (CUA-S1-style) on own data | — | fp32 ~tens of MB |
| NEXI-CUA | desktop | own driver + NEXI-S1 + tier LLM | — | — |
| NEXI-Image | 1 / 4 / 6 GB tiers | BK-SDM-class / SDXL distilled / FLUX.2 Klein | — | native quant |
| NEXI-Video | research | LTX-2.x distilled | — | FP8 + offload |

## Hard constraints

- **Training RAM: ~31 GB** on the primary machine (CPU-only). Practical ceiling:
  CPU LoRA on ≤7B at seq ≤2048; 13B only with heroic context cuts. Tiers above
  ~9B get their weights by distillation-assisted SFT where feasible, otherwise
  ship the best open base + NEXI adaptation (merge/quant/system level) until a
  GPU path exists.
- **Two concurrent work sessions.** The coordinator session stays mostly idle;
  two dedicated sessions do the work at any time.
- **Smallest that wins**: always pick the smallest base meeting the quality
  gate, then quantize further.

## Shared infrastructure (build once, all models use)

- `common/data` — training-mix builder with manifest (counts + sha256).
- `common/train` — LoRA trainer (TRL/PEFT CPU now; llama.cpp finetune path as
  alternate; Unsloth config ready for GPU), merge, GGUF export.
- `common/eval` — held-out runner: tool-call exact match, CUA action accuracy,
  HumanEval+, IFEval; voice and S1 get their own harnesses.
- `common/bench` — process benchmark: fresh-process wall time + peak RSS.
- `common/driver` — per-model installer templates + manifests (pinned SHA-256).

## Phases

- **P0 (done)**: wipe, research, this plan.
- **P1 — text tiers (Session A)**: rebuild common/ pipeline; latest data mix;
  fine-tune + eval NEXI-4 and NEXI-8 first (CPU-tractable), then NEXI-16 via
  distillation-SFT; document quant shrink plan for 20/28/32.
- **P1 — voice (Session B)**: stand up Pocket TTS + streaming STT candidates;
  measure RSS/RTF/first-audio; build the NEXI-Voice driver; run Pocket TTS
  fine-tune; select STT by measured WER×latency.
- **P2 — NEXI-S1 + NEXI-CUA**: typed decision model trained on synth + distilled
  labels with calibrated abstention; new tree-first driver; benchmark vs CUA-S1,
  then OSWorld-Verified / WebArena / Cua Bench.
- **P3 — image + video**: tiered image drivers; video research track with
  honest feasibility numbers.
- **P4 — release**: per-model README/ARCHITECTURE/BENCHMARKS/USE_CASES, pinned
  installers, release decision per tier only when tuned beats base.

## Session assignments

| Session | Scope | Repo branch |
|---|---|---|
| A — NEXI-Text | common/ + text tiers, starting 4 GB and 8 GB | `nexi-v2/text` |
| B — NEXI-Voice | TTS + STT selection, driver, fine-tune | `nexi-v2/voice` |

Later sessions pick up P2/P3/P4 as slots free up.

## Known risks (say them now)

1. CPU-only training caps real fine-tuning at ~7B; upper tiers lean on
   distillation + quantization more than novel training.
2. "Best in the world" is a moving target — the research doc is re-surveyed
   before every release, and gates are measured, never asserted.
3. Multimodal at 4 GB may not clear the quality gate; ship it only if it wins.
4. Video on CPU has no honest real-time path today; it stays research until
   numbers say otherwise.
