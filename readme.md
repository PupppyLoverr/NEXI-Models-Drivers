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
