# NEXI research — open-source landscape, November 2026

Survey date: 2026-11-24. Sources are vendor repos/model cards plus the
independent comparisons cited inline. Every pick in MASTER_PLAN.md traces back
to a row here. Re-run this survey before each release; this field moves monthly.

## 1. Small text/code LLMs (CPU-friendly, open weights)

RAM budgeting rule used across comparisons: model + KV cache ≈ 60% of system
RAM on ≤16 GB machines, ~75% above that, because the OS and apps share memory.

| Base | Sizes | Why it matters for NEXI | Watch-outs |
|---|---|---|---|
| **WePocketModel 1.0 (Tencent/WeChat AI, Nov 16)** | 2B, 4B (first-party GGUF) | Newest on-device family: one VL backbone does **generation + embedding + JEV-style typed decisions** (option/score/binary); 4B ranks #1 in all three families, 2B leads typed-decision among 2Bs (55.8 vs 35.6) — gives NEXI-4 multimodality + a built-in S1 head | License ambiguity: LICENSE.txt says Apache-2.0, model card says "pending confirmation" — verify before shipping derivatives |
| **Nemotron 3.5 Bolt E4B 4GB (NVIDIA, Oct 23 / paper Nov 16)** | E4B, ~4 GB footprint | Built for exactly the 4 GB tier: post-trained from Gemma-4-E4B, beats Gemma-4-E4B and Qwen3.5-4B on 21 benchmarks with fewest output tokens; DFlash drafter → 2.74× decode | OpenMDW license; nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-4GB + GGUF |
| **Inkling 2 Mini (Thinking Machines, Nov 20, Apache-2.0)** | 26.4B total / 3.4B active, ~20 GB | Looped-MoE multimodal (text+image): leads **every open-weights <100B model** on DeepSWE 48.2 / Vals 46.5; ~20 GB native footprint — the flagship that already hits the "shrink to ~21 GB" goal | Weights are NVFP4/MXFP8; GGUF builds exist (unsloth, ggml-org) — CPU inference speed on looped arch unproven, measure |
| **Nemotron 3.5 Bolt 74B-A9B (NVIDIA)** | 74B / 9B active | Bigger flagship option: nvidia's 24GB build = 24.1 GB RSS at 2-bit | 2-bit quant quality needs eval; OpenMDW license |
| Qwen3.5 (Alibaba, Apache-2.0) | 0.8B, 2B, 4B, 9B dense | Prior best benchmark-per-GB; hybrid Gated-DeltaNet + attention | Qwen3.5-2B is hybrid linear-attention — HF fallback kernels are slow on CPU; community GGUF only |
| Qwen3-VL (Alibaba, Apache-2.0) | 2B, 4B, 8B | Native image + video input — multimodal base for NEXI-16 | Vision tower adds RAM; verify GGUF vision support per llama.cpp build |
| **Qwen 4 status** | — | Announced Sep 22, in training. Only Qwen4-Max (2.4T/71B-active) shipped Nov 16 — **API-only, no weights**. Small Qwen4 opens "eventually", no date | Do NOT block the lineup on it; re-check at each release |
| Qwen3.6-35B-A3B (MoE) | 35B total, ~3B active | Flagship-class quality at small-model CPU speed; ~20.5 GB Q4 | Superseded by Inkling 2 Mini for NEXI-28/32 unless Inkling's CPU path fails |
| Gemma 4 (Google) | E2B, E4B, 12B, 26B-A4B | First-party GGUF; 26B-A4B MoE strong 20 GB pick | Gemma license is not OSI-approved |
| gpt-oss-20b (OpenAI) | 20B MoE | ~12 GB Q4, permissive, strong reasoning | MoE; validate tool-call behavior before adopting |
| Others to track | MiniMax-M3.1-Flash (agent/CU, ~428B), DeepSeek-V4.1-Flash, Mistral Large 4, LFM3-1.7B | Big-model context; too large for our tiers | — |

Multimodal options for the small tiers: Qwen3-VL (2B/4B/8B, image+video),
LFM3-VL-2B and LFM3-Omni-2B (video + audio soundtrack), MiniCPM-V 4.7 (1B,
document understanding), SmolVLM2 (256M/500M/2.2B, video, Apache-2.0),
InternVL 3.5 (1.1B), Moondream 3 (2B active, restricted license).
Multimodality at the 4 GB tier is plausible only with a 2B-class VL at ~Q4 —
flag as stretch, not promise.

llama.cpp accepts a video file directly (`--video`, via ffmpeg) on VL models;
Ollama takes stills only — so the driver should target llama.cpp first.

## 2. Real-time TTS (the NEXI-Voice-TTS base decision)

The bar: ElevenLabs (proprietary) and Fish Audio Drama 3 (35B MoE/3B active,
open weights, community license <$500k revenue, #1 on Artificial Analysis
pronunciation robustness at 93.2%).

| Candidate | Size | Streaming | Notes |
|---|---|---|---|
| **Kyutai Pocket TTS family** | 1.9M–18.2M tiny models + 100M base (Oct 2026) | 80 ms chunks, ~200 ms first audio, real-time on 1–2 CPU threads | MIT code / CC-BY weights; **training code public since Aug 2026** — the only top-tier TTS with a released trainer; **measured on this repo's bench: 603–650 MB RSS, RTF 0.10–0.17, TTFA 36–72 ms for the tiny family; flagship 1.18 GB / 0.46 / 181 ms** |
| **ZONOS3-Mini (Zyphra, Nov 9, Apache-2.0)** | 800M total / 100M active MoE | real-time on-device; <150 ms TTFA (M3), <570 ms (Pixel 9) | Voice cloning + word-level delivery control; runtimes for WebGPU/GGML/vLLM — the quality challenger to Pocket flagship; ~400–800 MB at 4–8 bit |
| **LFM3-Audio-2B (Liquid, Oct 27)** | 2B unified | live ASR in ~0.96 s chunks; interleaved text+speech output | One checkpoint = ASR + TTS + voice chat — architecturally ideal for calling; LFM Open License v1.0 (not OSI); English-only live modes |
| Qwen3-TTS (Alibaba) | open weights | 97 ms first audio (vendor figure), HTTP + WebSocket | 9 preset voices, instruction-controlled tone, 10 languages |
| Kokoro-82M | 326 MB ONNX | per-utterance only | 8 languages, no cloning, quality plateau |
| Linnet-35M | 83 MB, Rust runtime | 80 ms chunks | English-only, voice cloning, single vendor |
| Piper | 16–28M per voice | per-sentence | lowest quality of the set, bulletproof runtime |

Decision: Pocket TTS is the base — smallest weights, true streaming, voice
cloning, and a real training path. Qwen3-TTS is the quality reference and
fallback. Voice-quality target for release: beat Kokoro/Linnet blind A-B and
approach ElevenLabs on a defined conversational set, measured, not asserted.

## 3. Real-time streaming STT (NEXI-Voice-STT)

| Candidate | Size | Streaming | Notes |
|---|---|---|---|
| **Rumble-2-Flash (Nov 18, Apache-2.0)** | 0.5B | native transformers + vLLM | Brand-new ASR: 40+ languages, "competes with models 3–60× its size"; GGUF builds already up — **bench vs faster-whisper before picking STT base** |
| **VibeVoice-ASR-BitNet** (Microsoft VibeASR.cpp) | 1.58 GB total (VAE 0.65 + LM 0.92, hetero-quant) | RTF <1 on 1–4 CPU threads; 2–2.7× whisper.cpp | Qwen2.5-1.5B LM decoder; +1–4% WER vs full-size; real-time multilingual |
| FUTO asr4all small | 28.1M + 5.3M PCEC | two latency modes from one weight set | RTFx 30–128× on desktop CPU; English only; ethical-use clause |
| Whisper tiny/base.en via faster-whisper | 78/148 MB | VAD-segmented, not true streaming | **measured here: tiny.en 505 MB RSS / WER 13.3% / RTF 0.076; base.en 627 MB / 13.4% / 0.132 — base buys nothing on LibriSpeech-clean** |
| LFM3-Audio-2B (asr mode) | 2B shared | ~0.96 s live chunks | one-model-does-both option; see TTS table |
| fela-streaming-asr | small FNO-CTC | constant memory, true streaming | early project — evaluate before adopting |

For a calling product the pipeline is VAD → streaming ASR partials (<300 ms) →
punctuation/capitalization. VibeASR-BitNet is the quality pick; asr4all-s is the
footprint pick; ship whichever wins measured WER×latency on the harness.

## 4. Decision models (NEXI-S1)

- **TypeSafe AI "Jev"** (Sept 2026): the category definer. A "System One" model:
  typed outputs (choice / score / noul / box), calibrated probabilities on every
  answer, no text generation at all, questions evaluated in parallel, ~100×
  faster than an LLM doing the same judgment. Closed API, $42/Btok input.
- **CUA-S1** (trycua, open): the same idea, open, for GUI decisions:
  cua-s1-nano-0.1 (~855K params, option-attention classifier scoring every
  (element, action) candidate in one forward pass), cua-s1-4b (Qwen3.5-4B LoRA
  + RL on live GUIs). Known trap from its model card: OOD inputs return
  **high-confidence skips** — calibration on out-of-distribution is the
  hard part, not accuracy.
- NEXI-S1 design: typed decision head over a small encoder (option-attention
  scorer like cua-s1-nano, or a 1–2B decoder with constrained decoding),
  trained on our own tasks + distilled labels, with **calibrated abstention**
  as the headline feature. This is the most tractable "best in the world"
  claim in the ecosystem — Jev is closed and CUA-S1 is early research.

## 5. Computer-use and browser-use agents (NEXI-CUA)

What we're competing against:

- **cua.ai / trycua**: Cua Driver (MIT MCP server, background input on
  macOS/Windows/Linux, ~33k stars), CUA-S1 models, Cua Bench, Lume VMs,
  Cua Spaces. The infrastructure incumbent.
- **Vercel agent-desktop / agent-browser**: accessibility-tree → JSON with
  stable `ref`s, observe-act-verify loop, CLI + C library, no model inside.
  The clean reference architecture.
- **Open agent/model families (Nov 2026 bar)**: **NorthCUA** (Nov 3 — open
  family, Nano 9B 26.5% / Mini 35B on OSWorld-Verified, beats closed
  trillion-param APIs); **CUA-Master-27B** (Nov 2 — 80.2 OSWorld-Verified,
  best hybrid GUI+CLI: 43.9 WeaveBench / 25.0 ALE; Qwen-CUA-397B still leads
  GUI-only at 84.0); **Qwen-UI-Agent 27B** (ScreenSpot-v2 top);
  UI-Venus-1.5-30B-A3B; MiniMax-M3.1-Flash (agent+CU-tuned, weights followed).
- OSWorld-Verified top is now ~84–90%; the open-weight bar for a single
  model is ~80 (CUA-Master) and ~84 (Qwen-CUA-397B).

Design direction: tree-first observation (AX/AT-SPI/UIA + DOM, not
screenshot-first), NEXI-S1 as the fast decision layer with an LLM tier behind
it, typed verification after every action, and background input. Benchmarks:
OSWorld-Verified, WebArena/BrowserGym, Cua Bench — publish all three.

## 6. Image and video

| Track | Picks | Notes |
|---|---|---|
| Image flagship | FLUX.2 Klein 4B (Apache-2.0, ~13–16 GB, gen+edit+10 refs) | Official INT8 build fits ~15 GB |
| Image mid | Z-Image-Turbo (~33 GB files, 16 GB VRAM, best text) / SDXL (~7 GB, largest LoRA ecosystem) | SDXL-Lightning-style distilled for speed |
| Image text-heavy | Qwen-Image-2512 (20B, ~57 GB) | needs quant; research |
| Image tiny | BK-SDM-class distilled | the ≤1 GB target from v1 was honestly missed — re-attack with native quant/disk-backing |
| Video | LTX-2.5 (22B, 8-step distilled, audio+video, official ltx-trainer), Wan 2.2 TI2V-5B (24 GB GPU), HunyuanVideo 1.5 (14 GB min) | No honest CPU real-time path exists today; FP8 + disk offload gets generation working on workstations, not phones. Mark research track; ship measured numbers, not vibes. |

## 7. Training stack for a ~31 GB RAM machine (CPU-only)

- **LoRA/QLoRA via HF TRL+PEFT (CPU)**: practical at ≤3B, stretches to ~7B at
  seq 2048. Steps take seconds-to-minutes; only viable for the small tiers.
- **llama.cpp finetune path (CPU LoRA)**: community data — 32 GB trains ~7B,
  ~13B only with very short context and swap.
- **mlx-lm on Apple Silicon**: if a Mac with ≥32 GB unified memory is
  available, LoRA on up to ~9B is comfortable and much faster than x86 CPU.
- **Distillation > raw SFT for SLMs**: generate teacher data with the biggest
  affordable base (or each tier's own larger sibling), then SFT the small model.
  This is how the 4/8 GB tiers get frontier-adjacent behavior.
- **Unsloth / LLaMA-Factory / Axolotl**: keep configs GPU-ready — the pipeline
  should run on a rented GPU unchanged if one ever appears.
- **Export**: llama.cpp GGUF (+imatrix where supported), MLX for Apple,
  ONNX for voice drivers.

## 8. What "best" means — quality gates

| Model | Gate before claiming release-quality |
|---|---|
| NEXI-4/8/16/20/28/32 | Tuned > base on held-out tool-call, CUA, HumanEval+, IFEval; vs Qwen3.5/Gemma4/granite same-size on a shared subset |
| NEXI-Voice-TTS | RTF <0.3, first audio <300 ms on 2 threads, <1 GB RSS, blind A-B ≥ Kokoro-82M, honest distance to ElevenLabs |
| NEXI-Voice-STT | Streaming WER within +2% of Whisper base.en on test-clean subset, real-time on 2 threads, <2 GB RSS |
| NEXI-S1 | ≥ CUA-S1 published accuracy on its own suites, calibrated abstention on OOD (the cua-s1 failure mode), p50 <30 ms |
| NEXI-CUA | Measured OSWorld-Verified + WebArena + Cua Bench runs; tree-first latency p50 <40 ms observation |
| NEXI-Image/Video | Tier RAM targets met with measured RSS; quality honestly graded vs same-size baselines |
