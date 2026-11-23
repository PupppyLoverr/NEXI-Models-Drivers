# NEXI

NEXI is an open, fully-local model ecosystem: small frontier-quality models that
run on ordinary hardware — no cloud, no API key, no GPU required for inference.

Goal: the best open local model in every modality we ship. Each model is named
NEXI, trained or adapted on the latest open data and techniques, and published
with measured — not claimed — benchmarks.

## The ecosystem

| Model | Job | RAM target |
|---|---|---|
| NEXI-4 | text + code + tools | 4 GB |
| NEXI-8 | text + code + tools + vision | 8 GB |
| NEXI-16 | text + code + tools + vision | 16 GB |
| NEXI-20 | text + code + tools + vision | 20 GB |
| NEXI-28 | text + code + tools + vision | 28 GB |
| NEXI-32 | flagship text + code + tools + vision | ≤32 GB, targeting ~21 GB |
| NEXI-Voice-TTS | real-time text-to-speech | <1 GB |
| NEXI-Voice-STT | real-time streaming speech-to-text | <2 GB |
| NEXI-S1 | typed decision model (no text generation) | <1 GB |
| NEXI-CUA | computer-use + browser-use agent system | desktop |
| NEXI-Image | image generation and editing | 1–6 GB |
| NEXI-Video | video generation and editing | research track |

Everything above ships local weights, a local driver, a reproducible benchmark,
and an honest ledger of what is and is not verified.

## Docs

- [docs/RESEARCH.md](docs/RESEARCH.md) — the open-source landscape this is built
  on, dated November 2026.
- [docs/MASTER_PLAN.md](docs/MASTER_PLAN.md) — model-by-model plan, bases,
  training budgets, phases and quality gates.

## Working rules

1. **Measured, not claimed.** Every advertised number comes from a run on this
   repository's hardware, recorded with input, revision and settings. Published
   third-party numbers go in a separate table.
2. **Smallest that wins.** Pick the smallest base that beats the target
   benchmark; shrink it further with quantization before shipping.
3. **Honest scope.** A driver around an upstream model says so. A smoke test is
   not a quality result. A subset eval says its n.
4. **Local after setup.** Downloads are explicit, pinned and hashed. Inference
   needs no account, network or GPU.
