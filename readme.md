# NEXI Models

NEXI is a local-model project focused on coding, computer and browser use, and
tool calling. Chat is a secondary use case. Each tier currently ships its base
model; fine-tuning is in progress.

| Tier | Base model | RAM target | Peak RSS | Generation | Tier folder and source |
|---|---|---:|---:|---:|---|
| 4 GB | [Qwen/Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B) | 4 GB | 1.784 GB @ 2048 | 22.289 tok/s | [nexi-4gb/](nexi-4gb/) · [footprint](nexi-4gb/results/footprint.json) |
| 8 GB | [Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) | 8 GB | 4.082 GB @ 4096 | 10.103 tok/s | [nexi-8gb/](nexi-8gb/) · [footprint](nexi-8gb/results/footprint.json) |
| 16 GB | [google/gemma-4-12B-it](https://huggingface.co/google/gemma-4-12B-it) | 16 GB | 12.753 GB @ 4096 | 5.191 tok/s | [nexi-16gb/](nexi-16gb/) · [footprint](nexi-16gb/results/footprint.json) |
| 24 GB | [Qwen/Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B) | 24 GB | 20.406 GB @ 4096 | 1.888 tok/s | [nexi-24gb/](nexi-24gb/) · [footprint](nexi-24gb/results/footprint.json) |

Peak RSS and generation rates are CPU-only measurements collected on an
8-vCPU Intel Xeon Platinum 8375C host. Generation is the measured `tg128_tps`.

Status: M1 footprint measurements and the M2 pipeline are complete; M3 base
evaluations and fine-tuning are in progress.

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
## Shared pipeline

- [`common/data/`](common/data/) builds the training mix; [`common/data/out/manifest.json`](common/data/out/manifest.json) records its counts and hashes.
- [`common/train/`](common/train/) contains LoRA training, merge, and GGUF export tools.
- [`common/eval/`](common/eval/) contains the shared evaluation runner and HumanEval+ subset wrapper.
- [`common/driver/`](common/driver/) holds the tier manifest, installer templates, renderer, and smoke responses.
- [`common/requirements.txt`](common/requirements.txt) lists the Python dependencies.
