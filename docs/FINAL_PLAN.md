# NEXI Final Plan

*24 Nov 2026 — post-research, post-night-build. Status: FOR USER APPROVAL.*

## Vision

The best open-source local model ecosystem: every model NEXI-named, runs on
ordinary hardware (4–32 GB RAM), beats every open alternative in its category
at release, and together powers the agentic voice product. Everything is
benchmarked honestly — we publish measured numbers, never claimed ones.

## The lineup (what exists on disk today)

| Model | What it is | Status |
|---|---|---|
| NEXI-Voice-TTS | Pocket TTS 18M/2M profiles + HTTP server | Built, measured, realtime |
| NEXI-Voice-STT | faster-whisper tiny.en + Rumble-2-Flash hiacc profile | Built, measured |
| NEXI-S1 | 1.14M-param option-attention decisions model | Trained, measured |
| NEXI-CUA | tree-observe + S1-decide + gates agent | Built, benched |
| NEXI-CUA driver | thin observe/act layer, MCP-callable | Measured 8.5 MB — see below |
| NEXI-Image | BK-SDM-small engine + bench | Built, measured |
| NEXI-Video | — | Feasibility doc only |
| NEXI-4 | Qwen3.5-2B + LoRA, Q4_K_M GGUF | Trained, exported, measured |
| NEXI flagship | Inkling-2-Mini Q4_K_M GGUF | Running, measured |
| NEXI-8/16/20/28/32 | WePM-4B, Qwen3-VL-8B, Inkling, Nemotron-Bolt | Picked, not built |

## Phases to "#1 everywhere"

### Phase 1 — Make current models #1 (this week, CPU-OK)

- **STT is the biggest gap.** tiny.en WER 13.3% loses to Rumble's 4.05%, but
  Rumble is 7× too slow. Fix: build streaming ASR on VibeASR-BitNet or
  asr4all-s → target ~5% WER at RTF < 0.2, < 1 GB.
- **NEXI-4 tool_call at 20% is not #1.** Now unblocked: retrain on real
  `xlam-function-calling-60k` (HF token verified) → target > 80% exact-match.
- **CUA driver + browser agent (user spec):** the observe/act/gates layer
  ships as a standalone driver — **measured 8.5 MB peak RSS**, target was
  < 50–100 MB. It exposes `observe`/`act`/`gates` as MCP-callable tools;
  decisions come from NEXI-S1 as a separate service (the driver itself stays
  thin by design). Benchmark it against **cua.ai (Cua Spaces), agent-desktop,
  agent-browser, Browser Use** on: RAM per MCP call, step latency, task
  completion on OSWorld/WebArena mini-runs. Expand bench 12 → 50+ tasks.
- **S1:** keep 100%/perfect-abstain but move eval onto harder, less synthetic
  distributions; add a 4B LoRA variant for hard cases.
- **Image:** add Turbo/Lightning distillation path → ~4× faster per image.

### Phase 2 — Flagship improvement (Inkling levers, per INKLING-2-MINI-PLAN)

- Q3/Q2 quant builds + measured quality deltas.
- Inkling-as-teacher: generate traces overnight (~1 tok/s is fine for data) →
  distill into NEXI-4/8.
- Post-training Inkling itself needs Tinker or rented GPU — user decision.

### Phase 3 — Remaining text tiers (NEEDS USER GO-AHEAD)

NEXI-8 (WePM-4B), NEXI-16 (Qwen3-VL-8B), NEXI-28 (Nemotron-Bolt-74B-A9B).
Held per instruction "I'll tell you when to begin the text models."

### Phase 4 — Publish

All final models → `huggingface.co/nexiloopofficial` under a "nexi models"
collection (token verified, write access confirmed). Publish GGUFs + S1
weights + model cards with honest measured benchmarks. Last step after
each model earns its claims.

## Rules we keep

- Every claim backed by a measured number on consumer-class hardware.
- No weights in git; weights go to HF only.
- CPU-first: if it can't run on a 4–32 GB laptop, it isn't NEXI.
- Text tiers wait for explicit go.
