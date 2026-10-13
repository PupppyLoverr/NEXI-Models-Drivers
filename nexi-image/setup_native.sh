#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
REV=d637cfb935feb2254898a8f1524046c958f3df80
ROOT="${NEXI_NATIVE_HOME:-$HOME/nexi-image-native}"
mkdir -p "$ROOT"
if [[ ! -d "$ROOT/stable-diffusion.cpp/.git" ]]; then
    git clone https://github.com/leejet/stable-diffusion.cpp.git "$ROOT/stable-diffusion.cpp"
fi
git -C "$ROOT/stable-diffusion.cpp" fetch origin "$REV"
git -C "$ROOT/stable-diffusion.cpp" checkout --detach "$REV"
git -C "$ROOT/stable-diffusion.cpp" submodule update --init --depth 1 ggml
python3 -m venv .venv
.venv/bin/python -m pip install cmake==3.31.6
.venv/bin/cmake -S "$ROOT/stable-diffusion.cpp" -B "$ROOT/stable-diffusion.cpp/build" \
    -DCMAKE_BUILD_TYPE=Release -DSD_WEBP=OFF -DSD_WEBM=OFF -DSD_BUILD_EXAMPLES=ON
.venv/bin/cmake --build "$ROOT/stable-diffusion.cpp/build" --target sd-cli -j4
printf '\nBinary: %s\n' "$ROOT/stable-diffusion.cpp/build/bin/sd-cli"
