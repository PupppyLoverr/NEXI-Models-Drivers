# NEXI 16GB architecture

## Base configuration

Source: [google/gemma-4-12B-it `config.json`](https://huggingface.co/google/gemma-4-12B-it/blob/main/config.json).

- `model_type`: `gemma4_unified`; architecture class: `Gemma4UnifiedForConditionalGeneration`; text config type: `gemma4_unified_text`.
- Parameter size label: 12B in the shipped GGUF. Exact total parameter count is **unverified**; the base `config.json` has no total-parameter field.
- Text stack: 48 layers, hidden size 3840, 16 attention heads, 8 KV heads, head dimension 256, vocabulary 262144.
- Base maximum positions: 262144. This is distinct from the NEXI runtime context below.
- Attention layout: 40 `sliding_attention` layers and 8 `full_attention` layers in `text_config.layer_types`. The config sets `num_experts` to null; it does not define an MoE expert layout.
- The base config contains both `vision_config` and `audio_config`. NEXI's shipped server path uses text requests and does not configure image or audio inputs.

## Shipped base GGUF

- Source artifact: [gemma-4-12b-it-UD-Q4_K_XL.gguf](https://huggingface.co/unsloth/gemma-4-12b-it-GGUF/resolve/main/gemma-4-12b-it-UD-Q4_K_XL.gguf).
- Filename quantization label: `UD-Q4_K_XL`. GGUF metadata reports `general.file_type=15`, which the llama.cpp [`LlamaFileType` enum](https://github.com/ggml-org/llama.cpp/blob/b11580/gguf-py/gguf/constants.py) names `MOSTLY_Q4_K_M`.
- File size: 7,366,423,360 bytes.
- SHA-256: `90fd944d227e9d9b68e7e2c7d5b57b79d4c66ed521b0919fbbd932cf834f6f8e`.
- The GGUF metadata license is Apache-2.0.

The default source URL and SHA-256 are recorded in [`common/driver/tiers.json`](../common/driver/tiers.json); the measured file size is in [`results/footprint.json`](results/footprint.json). GGUF metadata was read with llama.cpp's `gguf_dump.py --json --no-tensors`.

## NEXI adaptation and data

- Training run settings supplied for this docs pass: sequence length 512, bf16.
- LoRA: rank 16, alpha 32, `all-linear`; excludes modules matching `.*(visual|vision|audio|multi_modal_projector|mm_projector).*`. The current base release is not a tuned checkpoint.
- Training mix: 2,283 rows — coding 720, tool 720, computer use (CUA) 600, chat 243. Held-out sets contain 150 tool and 200 CUA rows.
- Source: [`common/data/out/manifest.json`](../common/data/out/manifest.json) and [`common/train/train_lora.py`](../common/train/train_lora.py).

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
  +--> base or merged GGUF
  `--> optional GGUF LoRA (--lora; used by the 27GB tier)
```

The training configuration is in [`train_lora.py`](../common/train/train_lora.py); the server-time adapter option is in [`run_all.py`](../common/eval/run_all.py), and launcher argument forwarding is in [`install.sh.tpl`](../common/driver/templates/install.sh.tpl).
