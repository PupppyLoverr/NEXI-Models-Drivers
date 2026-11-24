# NEXI Model Catalog — what each model is, what it's for

*24 Nov 2026. RAM/speed measured on an 8 vCPU / 31 GB CPU-only machine —
the same class of hardware NEXI targets.*

## Voice

### NEXI-Voice-TTS (default: 18M profile)
Pocket TTS tiny family (Kyutai) wrapped in a streaming HTTP server.
- **Use case:** real-time speech for the calling product — streams audio in
  small chunks with 72 ms to first audio.
- **RAM/CPU:** 627 MB, RTF 0.17 (~6× realtime) on CPU. Tiny profile: 603 MB,
  RTF 0.10, 36 ms TTFA for the weakest devices.
- **Why this base:** only top-tier open TTS family with a released trainer,
  Apache-2.0, designed for 1-CPU-thread streaming.

### NEXI-Voice-STT (default: faster-whisper tiny.en)
faster-whisper CTranslate2 engine + Silero VAD streaming endpoint.
- **Use case:** live transcription on a call; partial transcripts as you speak.
- **RAM/CPU:** 505 MB, RTF 0.076 (~13× realtime), WER 13.3% (LibriSpeech n=40).
- **Hi-acc profile:** Rumble-2-Flash — WER 4.05% but 3.5 GB and 7× slower
  than realtime → offline/batch transcription only.

## Decisions

### NEXI-S1
Our own 1.14M-param option-attention scorer: given a goal + candidate actions,
returns a choice plus a calibrated abstain probability.
- **Use case:** the typed-decision brain — "which button/tool/file?" — for the
  agentic product; abstains instead of guessing.
- **RAM/CPU:** ~200 MB, ~300 ms per decision.
- **Measured:** 100% held-out choice accuracy, abstain P/R 1.0/1.0, ECE 0.023;
  beats string-overlap baseline 75% vs 67% on the CUA bench.

## Agents

### NEXI-CUA
From-scratch computer/browser-use loop: DOM/accessibility-tree observation →
typed candidates → S1 decision → deterministic safety gates → act → verify.
- **Use case:** hands of the product — clicks, types, navigates a real desktop
  or browser with password/payment/destructive gating.
- **RAM/CPU:** ~1 GB total incl. S1, ~300 ms/step.
- **Measured:** 75% on 12-task bench vs 67% heuristic baseline; all 3
  paraphrase tasks won; safety gates verified.

### NEXI-CUA driver (thin hands layer)
The observe/act/gates layer split out as a standalone MCP-callable driver —
flatten a DOM/AX tree to typed candidates, execute click/type/select,
enforce safety gates. Decisions come from NEXI-S1 over MCP, keeping the
driver itself tiny.
- **Use case:** drop-in hands for any agent stack; competes with cua.ai's
  driver, Vercel agent-desktop / agent-browser, Browser Use — but fully
  local and thin enough to embed per-session.
- **RAM/CPU:** **8.5 MB peak RSS** measured observing+gating a 100-candidate
  page — an order of magnitude under the <50–100 MB target.

## Media

### NEXI-Image
BK-SDM-small (Block-removed SDM) diffusers pipeline, CPU fp32.
- **Use case:** generate-and-wait local images — diagrams, product mocks.
- **RAM/CPU:** 3.4 GB peak, 169 s per 256px image, 45.6 s load.
- **Honest quality:** 1/3 prompts clearly on-prompt in the first bench.

### NEXI-Video
Not shipped — honest `nexi-video/FEASIBILITY.md`: no open video model can
generate realtime on CPU (physics, not effort). Path: keyframes+interpolation
labelled as such, or GPU-optional distillates later.

## Text / Flagship

### NEXI-4
Qwen3.5-2B + NEXI LoRA → merged → Q4_K_M GGUF.
- **Use case:** text/tool-call assistant for 4 GB RAM machines.
- **RAM/CPU:** 1.29 GB file, 1.97 GB RSS, 18.2 tok/s, 1.2 s load.
- **Measured:** tool_call 0%→20%, cua action 93.3%→100% after tuning;
  pipeline proven, capability not yet competitive (needs real xlam corpus).

### NEXI flagship (Inkling-2-Mini)
Thinking Machines' 26.4B looped MoE, Q4_K_M GGUF — best open <100B model on
agentic coding at release.
- **Use case:** shipped 20 GB flagship, distillation teacher for the small
  NEXIs, eval judge.
- **RAM/CPU:** 16.6 GB file, 13.1 GB RSS, ~1.0 tok/s — offline/agentic speed.
- **Improvement plan:** `docs/INKLING-2-MINI-PLAN.md` (distill / quantize /
  prune / loop-depth, then Tinker-or-GPU post-training).

## Held for user go-ahead

NEXI-8 (WePocketModel-4B), NEXI-16 (Qwen3-VL-8B multimodal),
NEXI-20 (Inkling role), NEXI-28 (Nemotron-3.5-Bolt-74B-A9B at NVIDIA's 24 GB
2-bit build) — all picked in `docs/MASTER_PLAN.md`, none built.
