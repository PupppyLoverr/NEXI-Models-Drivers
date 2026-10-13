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

## Shared pipeline

- [`common/data/`](common/data/) builds the training mix; [`common/data/out/manifest.json`](common/data/out/manifest.json) records its counts and hashes.
- [`common/train/`](common/train/) contains LoRA training, merge, and GGUF export tools.
- [`common/eval/`](common/eval/) contains the shared evaluation runner and HumanEval+ subset wrapper.
- [`common/driver/`](common/driver/) holds the tier manifest, installer templates, renderer, and smoke responses.
- [`common/requirements.txt`](common/requirements.txt) lists the Python dependencies.

Status: M1 footprint measurements and the M2 pipeline are complete; M3 base
evaluations are in progress.
