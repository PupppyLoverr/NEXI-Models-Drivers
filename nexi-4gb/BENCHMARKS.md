# NEXI 4GB Benchmarks

Release decision pending tuned eval.

Measured locally: CPU-only (8 vCPU, no GPU), llama.cpp b11580, Q4_K_M GGUF (24gb: UD-Q4_K_XL base GGUF + LoRA at load time), temperature 0, seed 2026, thinking disabled. Base and tuned use the same GGUF export path and the same item subset.

## Held-out evals[^eval-metrics]

| Metric | n | Base | NEXI tuned | Δ |
|---|---:|---:|---:|---:|
| Tool-call exact match | 40 | 25.0% | not run | not run |
| CUA action accuracy | 100 | 19.0% | not run | not run |
| CUA abstain accuracy | 37 | 0.0% | not run | not run |
| HumanEval+ base pass@1 | 30 | 60.0% | not run | not run |
| HumanEval+ plus pass@1 | 30 | 56.7% | not run | not run |
| IFEval prompt-level strict | 30 | 60.0% | not run | not run |
| IFEval instruction-level strict | 30 | 66.7% | not run | not run |

[^eval-metrics]: The subsets are small. Tool-call exact match is canonicalized name+arguments equal to the reference. CUA action accuracy is the chosen candidate index or `NONE` equal to the reference, on the NEXI-CUA held-out synth set, seed 99991; CUA abstain accuracy is exact-match accuracy on rows whose reference is `NONE`. HumanEval base pass@1 and HumanEval+ plus pass@1 are the fractions of prompts whose single generated solution passes, respectively, the original HumanEval tests and the HumanEval+ tests. IFEval prompt-level strict is the fraction of prompts satisfying all instructions under strict scoring; instruction-level strict is the fraction of individual instructions satisfied under strict scoring.

## Footprint (llama-bench / llama-cli on the shipped base GGUF `Qwen3.5-2B-UD-Q4_K_XL.gguf`, ctx 2048)

| Metric | Value |
|---|---:|
| GGUF file size | 1,339,752,704 B |
| Context | 2048 |
| Peak RSS | 1.784 GB |
| Prompt tok/s | 349.669 tok/s |
| Generation tok/s | 22.289 tok/s |
| Base eval server peak RSS (ctx 4096) | 2,518,372 KB |
| Tuned eval server peak RSS (ctx 4096) | not run |

## Training

Training run in progress.

## Across tiers[^across-tiers]

| Metric | nexi-4gb | nexi-8gb | nexi-16gb | nexi-24gb |
|---|---:|---:|---:|---:|
| Tool | 25.0% (n=40) | 33.3% (n=30) | not run | not run |
| CUA | 19.0% (n=100) | 53.8% (n=80) | not run | not run |
| HumanEval+ plus | 56.7% (n=30) | 95.0% (n=20) | not run | not run |
| IFEval prompt-strict | 60.0% (n=30) | 90.0% (n=20) | not run | not run |

[^across-tiers]: n differs by tier and items are the first N of the same held-out sets.

## Published reference scores (vendor-reported, not measured by NEXI, full precision, different harnesses)

- No vendor numbers are reproduced here; see the [base model card](https://huggingface.co/Qwen/Qwen3.5-2B).
