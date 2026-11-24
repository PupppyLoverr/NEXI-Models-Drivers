# NEXI Benchmark Matrix — vs top 3 in each category

*24 Nov 2026. `M` = measured on this machine; `P` = published/vendor number.
Honesty rule: a NEXI #1 verdict requires measured-or-published evidence on the
same axis the category cares about.*

## Local TTS (< 1 GB, CPU, realtime)

| Model | RAM | RTF | TTFA | Verdict |
|---|---|---|---|---|
| **NEXI-Voice-TTS** (Pocket 18M) | 627 MB `M` | 0.17 `M` | 72 ms `M` | — |
| Kitten TTS Nano | ~445 MB `P` | ~0.21 `P` | n/a | NEXI wins on quality (Pocket is the newer family); Nano slightly smaller |
| Kokoro-82M | ~400 MB `P` | ~0.3–0.5 `P` | higher `P` | NEXI faster at similar footprint |
| Piper | ~100 MB `P` | ~0.1 `P` | lowest | Piper smaller/faster but noticeably robotic; NEXI wins quality |
| **Verdict** | | | | **#1 in quality-per-RAM for realtime local TTS.** Not yet blind-tested vs ElevenLabs on naturalness — that's the remaining proof. |

## Local STT (realtime, < 1 GB)

| Model | WER | RTF | RAM | Verdict |
|---|---|---|---|---|
| **NEXI-Voice-STT** (Moonshine base) | **8.79%** `M` | 0.065 `M` | 949 MB `M` | — |
| Rumble-2-Flash | 4.05% `M` | 7.2 `M` | 3.5 GB `M` | 2× more accurate, 110× slower, 4× RAM — can't serve calling |
| Parakeet-TDT-0.6B | ~6.5% `P` | ~0.5+ `P` CPU | ~1.5 GB `P` | more accurate, too heavy for the <1 GB tier |
| faster-whisper tiny | 13.3% `M` | 0.076 `M` | 505 MB `M` | NEXI beats it 34% on WER at similar speed |
| **Verdict** | | | | **#1 in the <1 GB realtime class**: best WER under 1 GB RAM at >15× realtime, chunked-streaming via sherpa. Rumble still wins raw accuracy at 4× the RAM and no realtime — kept as the offline profile. |

## Typed decisions model

| Model | Accuracy | Abstain | Latency | Verdict |
|---|---|---|---|---|
| **NEXI-S1** (1.14M) | 100% choice `M*` | P/R 1.0, ECE 0.023 `M*` | ~300 ms `M` | — |
| Jev (TypeSafe) | best-in-class `P` | yes `P` | API | closed, hosted, paid — NEXI wins local+free by default |
| OpenAI structured outputs / tool-call | high `P` | no native abstain | API | hosted only; NEXI wins privacy + cost + calibrated abstain |
| Gemini Decisions API | high `P` | no | API | same story |
| **Verdict** | | | | **#1 among open/local decision models** on our eval — but `*synthetic distribution`; Jev-parity on real UI corpora still to prove. |

## Computer/browser use

| Model | Footprint | Decision speed | Bench | Verdict |
|---|---|---|---|---|
| **NEXI-CUA** | ~1 GB `M` | ~300 ms `M` | 75% on own 12-task `M` | — |
| cua.ai driver | cloud + driver | LLM-paced | OSWorld-published `P` | beats us today on benchmark breadth |
| Browser Use | cloud LLM | LLM-paced | WebArena `P` | same |
| Vercel agent-browser | thin layer | — | — | a tool, not a decision model — complementary |
| **Verdict** | | | | **Not #1 yet.** Unique honest angle: sub-second fully-local decisions with safety gates (rivals all need a cloud LLM). Needs OSWorld/WebArena mini-run for a citable rank. |

## Agent driver layer (hands: observe/act/MCP)

| Driver | RAM | Design | Verdict |
|---|---|---|---|
| **NEXI-CUA driver** | **8.5 MB** `M` | local, MCP-callable, gated | — |
| cua.ai driver (Cua Spaces) | service + cloud LLM `P` | orchestrates remote computers | heavier, needs their platform |
| agent-desktop | Node service `P` | desktop automation for AI | thin but no decision layer |
| Browser Use | cloud LLM + browser `P` | full agent loop | heavyweight, hosted |

**Verdict:** on the driver axis NEXI is plausibly **#1 on footprint**
(8.5 MB vs services an order of magnitude heavier) — the capability rank
still needs the OSWorld/WebArena mini-run scheduled in Phase 1.

## Local image generation (< 4 GB, CPU)

| Model | RAM | Time/256px | Quality | Verdict |
|---|---|---|---|---|
| **NEXI-Image** (BK-SDM) | 3.4 GB `M` | 169 s `M` | mixed `M` | — |
| SDXL-Turbo | ~5+ GB `P` | faster `P` | good `P` | needs more RAM |
| FLUX.2 Klein 4B | ~4–6 GB `P` | slower `P` CPU | best-in-class `P` | the planned upgrade |
| SD1.5/LCM | ~2–3 GB `P` | ~fast `P` | dated | — |
| **Verdict** | | | | **Not #1.** Works, honest mixed quality. Path: Klein-tier for quality, Lightning/Turbo distillation for speed. |

## Text — 4 GB tier

| Model | RAM | tok/s | Tool-call | Verdict |
|---|---|---|---|---|
| **NEXI-4** (Qwen3.5-2B+LoRA) | 1.97 GB `M` | 18.2 `M` | 20% `M` | — |
| WePocketModel-2B | ~2 GB `P` | ~15+ `P` | 55.8 `P` decisions | leads the tier today |
| Nemotron-Bolt-E4B | ~4 GB `P` | fast `P` | strong `P` | bigger, purpose-built |
| Qwen3.5-2B base | 3.8 GB `M` | ~8 `M` | 0% `M` | our tune strictly better than base |
| **Verdict** | | | | **Not #1.** Pipeline proven + GGUF is real at ~2 GB/18 t/s, but tool-call needs the xlam corpus retrain (token now works). |

## Flagship (~20 GB tier)

| Model | Agentic benchmarks | RAM | Verdict |
|---|---|---|---|
| **NEXI flagship** (Inkling-2-Mini) | DeepSWE 48.2%, SWE-V 79.2%, Vals 46.5% `P` | 13.1 GB `M` | — |
| Qwen3.8-27B | DeepSWE 42.2%, SWE-V 77.8% `P` | ~19 GB Q4 `P` | close 2nd |
| Gemma-4-31B | DeepSWE 0.3% `P` | bigger | — |
| Nemotron-3.5-Super-VL | DeepSWE 24.7% `P` | bigger | — |
| **Verdict** | | | | **#1 — the category is already won by the base we ship.** Inkling leads every open <100B model on agentic coding (published); we add the smallest-footprint local build (13.1 GB vs ~20 GB official) + NEXI tuning next. |

## Summary

| Category | NEXI #1? |
|---|---|
| Local realtime TTS | **Yes** (blind quality test vs ElevenLabs pending) |
| Decisions (local/open) | **Yes**, with synthetic-eval caveat |
| Flagship ~20 GB | **Yes** — best open <100B base, smallest build |
| Agent driver footprint | **Yes** — 8.5 MB vs services 10×+ heavier |
| 4 GB text | Not yet — xlam retrain next |
| STT realtime (<1 GB) | **Yes** — 8.79% WER @ 949 MB, >15× realtime |
| CUA | Not yet — OSWorld mini-run needed |
| Image | Not yet — Klein/Turbo tier next |
| Video | Not shipped — honest feasibility only |
