#!/usr/bin/env bash
set -euo pipefail

LLAMA_CPP_TAG="b11580"
TOOLCHAIN_DIR="${HOME}/nexi-toolchain"
LLAMA_CPP_DIR="${TOOLCHAIN_DIR}/llama.cpp"
VENV_DIR="${HOME}/nexi-venv"

mkdir -p "$TOOLCHAIN_DIR"

if [[ ! -d "${LLAMA_CPP_DIR}/.git" ]]; then
    if [[ -e "$LLAMA_CPP_DIR" ]]; then
        printf 'Refusing to use non-git path: %s\n' "$LLAMA_CPP_DIR" >&2
        exit 1
    fi
    git clone --branch "$LLAMA_CPP_TAG" --depth 1 \
        https://github.com/ggml-org/llama.cpp.git "$LLAMA_CPP_DIR"
else
    git -C "$LLAMA_CPP_DIR" fetch --depth 1 origin "refs/tags/${LLAMA_CPP_TAG}:refs/tags/${LLAMA_CPP_TAG}"
    git -C "$LLAMA_CPP_DIR" checkout --detach "$LLAMA_CPP_TAG"
fi

(
    cd "$LLAMA_CPP_DIR"
    cmake -B build -DGGML_NATIVE=ON -DLLAMA_CURL=OFF -DCMAKE_BUILD_TYPE=Release
    cmake --build build -j8
)

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    python3 -m venv "$VENV_DIR"
fi
"${VENV_DIR}/bin/pip" install -U huggingface_hub
