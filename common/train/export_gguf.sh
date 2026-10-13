#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
    printf 'Usage: %s <base_hf_dir> <adapter_dir|none> <out.gguf>\n' "$0" >&2
    exit 2
fi

base_hf_dir="$(realpath "$1")"
adapter_dir="$2"
out_arg="$3"
out_dir="$(dirname "$out_arg")"
mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd)"
out_gguf="${out_dir}/$(basename "$out_arg")"
if [[ "$out_gguf" == *.gguf ]]; then
    f16_gguf="${out_gguf%.gguf}.f16.gguf"
else
    f16_gguf="${out_gguf}.f16.gguf"
fi

llama_cpp_dir="${NEXI_LLAMA_CPP_DIR:-$HOME/nexi-toolchain/llama.cpp}"
python="${NEXI_PYTHON:-$HOME/nexi-venv/bin/python}"
converter="${llama_cpp_dir}/convert_hf_to_gguf.py"
quantizer="${llama_cpp_dir}/build/bin/llama-quantize"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/nexi-export.XXXXXX")"

cleanup() {
    rm -rf -- "$work_dir"
    rm -f -- "$f16_gguf"
}
trap cleanup EXIT

if [[ ! -d "$base_hf_dir" ]]; then
    printf 'Base HF directory does not exist: %s\n' "$base_hf_dir" >&2
    exit 1
fi
if [[ ! -f "$converter" ]]; then
    printf 'llama.cpp converter not found: %s\n' "$converter" >&2
    exit 1
fi
if [[ ! -x "$quantizer" ]]; then
    printf 'llama-quantize not found or not executable: %s\n' "$quantizer" >&2
    exit 1
fi
if [[ ! -x "$python" ]]; then
    printf 'Python interpreter not found or not executable: %s\n' "$python" >&2
    exit 1
fi

if [[ "$adapter_dir" == "none" ]]; then
    source_hf_dir="$base_hf_dir"
else
    "$python" "$(dirname "$0")/merge_lora.py" "$base_hf_dir" "$adapter_dir" "${work_dir}/merged-hf"
    source_hf_dir="${work_dir}/merged-hf"
fi

"$python" "$converter" "$source_hf_dir" --outfile "$f16_gguf" --outtype f16
"$quantizer" "$f16_gguf" "$out_gguf" Q4_K_M
printf 'GGUF size: %s bytes\n' "$(wc -c < "$out_gguf" | tr -d '[:space:]')"
sha256sum "$out_gguf"
