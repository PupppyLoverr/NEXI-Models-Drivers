# NEXI master plan

Status: pipeline rebuilt + first fine-tune running. Research re-swept 2026-11-24
(latest releases folded in).
Last updated: 2026-11-24.

## Naming and lineup

Everything ships under the NEXI name. Text tiers are named for the machine RAM
they run on; the multimodal flag means image and video input, not generation.

| Model | RAM target | Planned base (Nov-24 sweep) | Multimodal | Quant target |
|---|---|---|---|---|
| NEXI-4 | 4 GB | **WePocketModel-2B** (multimodal + decision head, GGUF) — alt: Nemotron-3.5-Bolt-E4B; interim eval base: Qwen3.5-2B | yes (stretch→goal) | Q4_K_M GGUF ≤ ~2.4 GB total |
| NEXI-8 | 8 GB | **WePocketModel-4B** (#1 on-device: generation+embedding+decision, GGUF) — alt: Qwen3-VL-4B | yes | ≤ ~4.8 GB |
| NEXI-16 | 16 GB | Qwen3-VL-8B (alt: Gemma 4 12B) | yes | ≤ ~9.6 GB |
| NEXI-20 | 20 GB | **Inkling 2 Mini** (26.4B/3.4B-active looped MoE, ~20 GB, Apache-2.0, <100B leader) | yes (text+image) | ~20 GB native NVFP4/FP8; GGUF exists |
| NEXI-28 | 28 GB | **Nemotron-3.5-Bolt-74B-A9B @ 2-bit** (~24.1 GB, official build) — alt: Qwen3.6-35B-A3B | check | ≤ ~24 GB |
| NEXI-32 | ≤32 GB, goal ~21 GB | Inkling 2 Mini (same ~20 GB flagship) or Nemotron-74B-A9B | check | ~20–24 GB incl. KV |
| NEXI-Voice-TTS | <1 GB | Kyutai Pocket TTS tiny family (1.9M–18.2M; **measured: 603–650 MB, RTF ≤0.17, TTFA ≤72 ms**) — alt: ZONOS3-Mini | — | ONNX/CPU |
| NEXI-Voice-STT | <2 GB | faster-whisper tiny.en baseline (505 MB, WER 13.3%, RTF 0.076) vs **Rumble-2-Flash** (0.5B, Nov 18) vs asr4all-s/VibeASR — decided by measurement | — | quant native |
| NEXI-S1 | <1 GB | **WePM decision head (JEV-style) or option-attention scorer on own data** — refs: Jev (closed), CUA-S1, WePM-2B decision | — | fp32 ~tens of MB |
| NEXI-CUA | desktop | own driver + NEXI-S1 + tier LLM; bar: NorthCUA / CUA-Master-27B / Qwen-CUA | — | — |
| NEXI-Image | 1 / 4 / 6 GB tiers | BK-SDM-class / SDXL distilled / FLUX.2 Klein | — | native quant |
| NEXI-Video | research | LTX-2.x distilled | — | FP8 + offload |

## Hard constraints

- **Training RAM: ~31 GB** on the primary machine (CPU-only). Practical ceiling:
  CPU LoRA on ≤7B at seq ≤2048; 13B only with heroic context cuts. Tiers above
  ~9B get their weights by distillation-assisted SFT where feasible, otherwise
  ship the best open base + NEXI adaptation (merge/quant/system level) until a
  GPU path exists.
- **Two concurrent work sessions.** Revised 2026-11-24: the user pulled worker
  sessions back (lite mode still counted against their usage); all work now runs
  in this coordinator session.
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
| This session (coordinator) | everything, sequentially | `nexi-v2` |

Work proceeds P1-voice (done: measured + driver) → P1-text (running: base
evals + 150-step LoRA on Qwen3.5-2B; WePM swap-in eval next) → P2 → P3 → P4.

## Known risks (say them now)

1. CPU-only training caps real fine-tuning at ~7B; upper tiers lean on
   distillation + quantization more than novel training.
2. "Best in the world" is a moving target — the research doc is re-surveyed
   before every release, and gates are measured, never asserted.
3. Multimodal at 4 GB may not clear the quality gate; ship it only if it wins.
4. Video on CPU has no honest real-time path today; it stays research until
   numbers say otherwise.
