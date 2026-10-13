# NEXI 24GB architecture

## Base configuration

Source: [Qwen/Qwen3.8-27B `config.json`](https://huggingface.co/Qwen/Qwen3.8-27B/blob/main/config.json).

- `model_type`: `qwen3_5`; architecture class: `Qwen3_5ForConditionalGeneration`; text config type: `qwen3_5_text`.
- Parameter size label: 27B in the shipped GGUF. Exact total parameter count is **unverified**; the base `config.json` has no total-parameter field.
- Text stack: 64 layers, hidden size 5120, 24 attention heads, 4 KV heads, head dimension 256, vocabulary 248320.
- Base maximum positions: 262144. This is distinct from the NEXI runtime context below.
- Attention layout: 48 `linear_attention` layers and 16 `full_attention` layers, as listed in `text_config.layer_types`; full attention repeats every four layers. No MoE expert layout is declared in the text config.
- The base config includes a vision tower (`depth=27`, hidden size 1152, 16 heads) and image/video token IDs. NEXI's shipped server path is text-only; it does not configure image or video inputs.

## Shipped base GGUF

- Source artifact: [Qwen3.8-27B-UD-Q4_K_XL.gguf](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/resolve/main/Qwen3.8-27B-UD-Q4_K_XL.gguf).
- Filename quantization label: `UD-Q4_K_XL`. GGUF metadata reports `general.file_type=15`, which the llama.cpp [`LlamaFileType` enum](https://github.com/ggml-org/llama.cpp/blob/b11580/gguf-py/gguf/constants.py) names `MOSTLY_Q4_K_M`.
- File size: 17,559,178,144 bytes.
- SHA-256: `3f227079003add2511437e5b1e94812e363385225bf6a9b47b0054a72bc8b01e`.
- The GGUF metadata license is Apache-2.0.

The default source URL and SHA-256 are recorded in [`common/driver/tiers.json`](../common/driver/tiers.json); the measured file size is in [`results/footprint.json`](results/footprint.json). GGUF metadata was read with llama.cpp's `gguf_dump.py --json --no-tensors`.

## NEXI adaptation and data

- Training run settings supplied for this docs pass: 4-bit NF4 QLoRA, sequence length 512.
- LoRA: rank 16, alpha 32, `all-linear`; excludes modules matching `.*(visual|vision|audio|multi_modal_projector|mm_projector).*`.
- A bf16 merge does not fit within the 32 GB training host. The planned tuned package therefore retains the base GGUF and loads the converted LoRA adapter at runtime with `llama-server --lora`. This release ships the base until tuned weights beat it on held-out evals.
- Training mix: 2,283 rows — coding 720, tool 720, computer use (CUA) 600, chat 243. Held-out sets contain 150 tool and 200 CUA rows.
- Source: [`common/data/out/manifest.json`](../common/data/out/manifest.json), [`common/eval/run_all.py`](../common/eval/run_all.py), and [`common/driver/tiers.json`](../common/driver/tiers.json). The 27B sequence and QLoRA settings are the reported run configuration.

## Runtime and request path

- Runtime: llama.cpp `b11580`, `llama-server --jinja`; default context 4096 from [`common/driver/tiers.json`](../common/driver/tiers.json).
- Request path:

```text
Client
  |
  | HTTP /v1/chat/completions
  v
llama-server (--jinja, ctx=4096)
  |
  +--> Qwen3.8-27B base GGUF
  `--> tuned GGUF LoRA adapter (--lora), when available
```

The shared evaluation runner accepts `--lora <adapter.gguf>` and passes it to llama-server. The generated tier launchers also forward additional llama-server arguments.
