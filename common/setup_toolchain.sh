#!/usr/bin/env bash
set -euo pipefail

LLAMA_CPP_TAG="b11580"
TOOLCHAIN_DIR="${HOME}/nexi-toolchain"
LLAMA_CPP_DIR="${TOOLCHAIN_DIR}/llama.cpp"
VENV_DIR="${HOME}/nexi-venv"

has_cxx_compiler() {
    command -v c++ >/dev/null 2>&1 ||
        command -v g++ >/dev/null 2>&1 ||
        command -v clang++ >/dev/null 2>&1
}

if ! command -v cmake >/dev/null 2>&1 || ! has_cxx_compiler; then
    if [[ "$(uname -s)" != "Linux" ]]; then
        printf 'Error: cmake and a C++ compiler are required; automatic installation is supported on Linux only.\n' >&2
        exit 1
    fi
    if ! command -v sudo >/dev/null 2>&1 || ! command -v apt-get >/dev/null 2>&1; then
        printf 'Error: missing cmake or C++ compiler; sudo and apt-get are required to install cmake build-essential.\n' >&2
        exit 1
    fi
    if ! sudo apt-get install -y cmake build-essential; then
        printf 'Error: failed to install cmake build-essential with apt-get.\n' >&2
        exit 1
    fi
    if ! command -v cmake >/dev/null 2>&1 || ! has_cxx_compiler; then
        printf 'Error: cmake or a C++ compiler is still missing after package installation.\n' >&2
        exit 1
    fi
fi

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
