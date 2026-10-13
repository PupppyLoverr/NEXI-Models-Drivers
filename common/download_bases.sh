#!/usr/bin/env bash
set -euo pipefail

HF="${HOME}/nexi-venv/bin/hf"
MODEL_ROOT="${HOME}/nexi-models"

models=(
    'nexi-24gb|unsloth/Qwen3.8-27B-GGUF|Qwen3.8-27B-UD-Q4_K_XL.gguf|17559178144'
    'nexi-16gb|unsloth/gemma-4-12b-it-GGUF|gemma-4-12b-it-UD-Q4_K_XL.gguf|7366423360'
    'nexi-8gb|unsloth/Qwen3.5-4B-GGUF|Qwen3.5-4B-UD-Q4_K_XL.gguf|2912109728'
    'nexi-4gb|unsloth/Qwen3.5-2B-GGUF|Qwen3.5-2B-UD-Q4_K_XL.gguf|1339752704'
)

if [[ ! -x "$HF" ]]; then
    printf 'Hugging Face CLI not found: %s\n' "$HF" >&2
    exit 1
fi

for entry in "${models[@]}"; do
    IFS='|' read -r folder repo file expected_bytes <<< "$entry"
    destination="${MODEL_ROOT}/${folder}"
    path="${destination}/${file}"

    mkdir -p "$destination"
    "$HF" download "$repo" "$file" --local-dir "$destination"

    actual_bytes="$(stat -c '%s' "$path")"
    if [[ "$actual_bytes" != "$expected_bytes" ]]; then
        printf 'Size mismatch for %s: expected %s bytes, got %s bytes\n' \
            "$path" "$expected_bytes" "$actual_bytes" >&2
        exit 1
    fi
    printf 'Verified %s: %s bytes\n' "$path" "$actual_bytes"
done
