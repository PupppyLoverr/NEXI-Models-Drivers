# NEXI Models

Local base models intended for later fine-tuning, beginning with coding, tool
calling, and browser/computer use; chat is a secondary use case. M1 records the
CPU-only runtime footprint of the four text-only base models. No training is
included in this milestone.

| Folder | Base model | License | GGUF size | Peak RSS @ context | tg128 tok/s |
|---|---|---|---:|---:|---:|
| `nexi-24gb` | [Qwen/Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B) | Apache-2.0 | 17,559,178,144 B | 20.406 GB @4096 | 1.888 |
| `nexi-16gb` | [google/gemma-4-12B-it](https://huggingface.co/google/gemma-4-12B-it) | Apache-2.0 | 7,366,423,360 B | 12.753 GB @4096 | 5.191 |
| `nexi-8gb` | [Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) | Apache-2.0 | 2,912,109,728 B | 4.082 GB @4096 | 10.103 |
| `nexi-4gb` | [Qwen/Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B) | Apache-2.0 | 1,339,752,704 B | 1.784 GB @2048 | 22.289 |

Footprints and throughput are measured on the 8-vCPU Intel Xeon Platinum 8375C
CPU box; these are CPU numbers only.

Status: M1 — base footprints measured. M2 (in progress): CPU LoRA fine-tuning on 32 GB / 8 vCPU Linux VMs (no GPU).

## Local speech and image drivers

Each modality has an independent setup and explicitly downloaded, pinned model assets.
Inference is local after setup; no cloud inference subscription or API key is required.

| Folder / guide | Architecture | Use cases | Benchmarks and comparisons |
|---|---|---|---|
| [nexi-stt — dictation](nexi-stt/README.md) | [Architecture](nexi-stt/ARCHITECTURE.md) | [Use cases](nexi-stt/USE_CASES.md) | [Benchmarks](nexi-stt/BENCHMARKS.md) |
| [nexi-tts — speech synthesis](nexi-tts/README.md) | [Architecture](nexi-tts/ARCHITECTURE.md) | [Use cases](nexi-tts/USE_CASES.md) | [Benchmarks](nexi-tts/BENCHMARKS.md) |
| [nexi-image — text-to-image](nexi-image/README.md) | [Architecture](nexi-image/ARCHITECTURE.md) | [Use cases](nexi-image/USE_CASES.md) | [Benchmarks](nexi-image/BENCHMARKS.md) |

These are NEXI drivers around identified upstream pretrained models, not newly trained
foundation models. Adaptation/fine-tuning instructions are in each guide; training
memory is separate from inference memory. Published cloud-product quality claims are
not evidence that these small local models match Wispr Flow or ElevenLabs.

STT fine-tuning/export and image LoRA paths were executed as optimizer smoke tests,
not validated quality improvements. Kitten Nano TTS has no verified released trainer;
its guide documents a separate Pocket TTS training route, not a compatible Nano adapter.

The [process benchmark harness](common/bench/README.md) records fresh-process wall time
and peak system RSS without an ML dependency. Each modality's benchmark table identifies
its input, hardware, settings and model revision and separates measurements here from
published comparison figures. **Checkpoint size, total system RAM, and GPU VRAM are
different quantities.** In particular, image generation must not be advertised as a
sub-1-GB runtime just because its quantized weights fit in a sub-1-GB file.

## NEXI-CUA (computer-use and browser-use driver + model)

[`nexi-cua/`](nexi-cua/) is a local, $0 computer-use runtime. It contains the 6.3 MB NEXI-CUA-1 action ranker, a deterministic semantic resolver, and macOS AX / Windows UIA / Linux AT-SPI / Chromium CDP drivers with safety gates and verification. Start with [`nexi-cua/README.md`](nexi-cua/README.md). Installers are in `nexi-cua/install/`, the prebuilt v0.4.0 wheel/sdist in `nexi-cua/releases/`, and the measured numbers and comparisons in `nexi-cua/BENCHMARKS.md`.
