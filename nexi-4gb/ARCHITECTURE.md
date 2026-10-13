# NEXI 4GB architecture

## Base configuration

Source: [Qwen/Qwen3.5-2B `config.json`](https://huggingface.co/Qwen/Qwen3.5-2B/blob/main/config.json).

- `model_type`: `qwen3_5`; architecture class: `Qwen3_5ForConditionalGeneration`; text config type: `qwen3_5_text`.
- Parameter size label: 2B in the shipped GGUF. Exact total parameter count is **unverified**; the base `config.json` has no total-parameter field.
- Text stack: 24 layers, hidden size 2048, 8 attention heads, 2 KV heads, head dimension 256, vocabulary 248320.
- Base maximum positions: 262144. This is distinct from the NEXI runtime context below.
- Attention layout: 18 `linear_attention` layers and 6 `full_attention` layers, as listed in `text_config.layer_types`; full attention repeats every four layers. No MoE expert layout is declared in the text config.
- The base config includes a vision tower (`depth=24`, hidden size 1024, 16 heads) and image/video token IDs. NEXI's shipped server path is text-only; it does not configure image or video inputs.

## Shipped base GGUF

- Source artifact: [Qwen3.5-2B-UD-Q4_K_XL.gguf](https://huggingface.co/unsloth/Qwen3.5-2B-GGUF/resolve/main/Qwen3.5-2B-UD-Q4_K_XL.gguf).
- Filename quantization label: `UD-Q4_K_XL`. GGUF metadata reports `general.file_type=15`, which the llama.cpp [`LlamaFileType` enum](https://github.com/ggml-org/llama.cpp/blob/b11580/gguf-py/gguf/constants.py) names `MOSTLY_Q4_K_M`.
- File size: 1,339,752,704 bytes.
- SHA-256: `0af96165ea615bea39a04118d63f0b6d35908aea850ee4a51aa6151d851b8b35`.
- The GGUF metadata license is Apache-2.0.

The default source URL and SHA-256 are recorded in [`common/driver/tiers.json`](../common/driver/tiers.json); the measured file size is in [`results/footprint.json`](results/footprint.json). GGUF metadata was read with llama.cpp's `gguf_dump.py --json --no-tensors`.

## NEXI adaptation and data

- Training run settings supplied for this docs pass: sequence length 1024, bf16.
- LoRA: rank 16, alpha 32, `all-linear`; excludes modules matching `.*(visual|vision|audio|multi_modal_projector|mm_projector).*`. The current base release is not a tuned checkpoint.
- Training mix: 2,283 rows — coding 720, tool 720, computer use (CUA) 600, chat 243. Held-out sets contain 150 tool and 200 CUA rows.
- Source: [`common/data/out/manifest.json`](../common/data/out/manifest.json) and [`common/train/train_lora.py`](../common/train/train_lora.py).

## Runtime and request path

- Runtime: llama.cpp `b11580`, `llama-server --jinja`; default context 2048 from [`common/driver/tiers.json`](../common/driver/tiers.json).
- Request path:

```text
Client
  |
  | HTTP /v1/chat/completions
  v
llama-server (--jinja, ctx=2048)
  |
  +--> base or merged GGUF
  `--> optional GGUF LoRA (--lora; used by the 27GB tier)
```

The training configuration is in [`train_lora.py`](../common/train/train_lora.py); the server-time adapter option is in [`run_all.py`](../common/eval/run_all.py), and launcher argument forwarding is in [`install.sh.tpl`](../common/driver/templates/install.sh.tpl).
