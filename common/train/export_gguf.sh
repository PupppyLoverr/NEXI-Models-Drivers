#!/usr/bin/env bash
# Export a merged HF checkpoint to quantized GGUF via llama.cpp.
# Usage: common/train/export_gguf.sh <merged_dir> <out_gguf> [quant]
set -euo pipefail
MERGED=${1:?merged dir}
OUT=${2:?output gguf}
QUANT=${3:-Q4_K_M}
LLAMA=${LLAMA_CPP_DIR:-/opt/llama.cpp}
python "$LLAMA/convert_hf_to_gguf.py" "$MERGED" --outfile "$OUT.f16.gguf" --outtype f16
"$LLAMA/build/bin/llama-quantize" "$OUT.f16.gguf" "$OUT" "$QUANT"
echo "wrote $OUT ($QUANT)"
