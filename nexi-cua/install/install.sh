#!/bin/sh
set -eu

WITH_VISION=0
UNINSTALL=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --with-vision) WITH_VISION=1 ;;
        --uninstall) UNINSTALL=1 ;;
        *)
            printf 'Unknown option: %s\n' "$1" >&2
            exit 2
            ;;
    esac
    shift
done

NEXI_CUA_HOME=${NEXI_CUA_HOME:-"$HOME/.nexi-cua"}
VENV="$NEXI_CUA_HOME/venv"
ENTRYPOINT="$HOME/.local/bin/nexi-cua"

if [ "$UNINSTALL" -eq 1 ]; then
    rm -rf "$VENV"
    rm -f "$ENTRYPOINT"
    printf 'Removed %s and %s\n' "$VENV" "$ENTRYPOINT"
    exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
    printf 'Python 3.10 or newer is required; install Python 3 and try again.\n' >&2
    exit 1
fi
PYTHON=$(command -v python3)
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    printf 'Python 3.10 or newer is required; found %s.\n' "$("$PYTHON" --version 2>&1)" >&2
    exit 1
fi

SYSTEM=$(uname -s)
case "$SYSTEM" in
    Darwin) EXTRA=macos ;;
    Linux) EXTRA=linux ;;
    *)
        printf 'Unsupported platform: %s\n' "$SYSTEM" >&2
        exit 1
        ;;
esac

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
CHECKOUT=$(CDPATH= cd "$SCRIPT_DIR/.." && pwd)
mkdir -p "$NEXI_CUA_HOME"
"$PYTHON" -m venv "$VENV"

if [ -f "$CHECKOUT/pyproject.toml" ]; then
    PACKAGE_SPEC="$CHECKOUT[$EXTRA]"
else
    PACKAGE_SPEC="nexi-cua[$EXTRA] @ https://github.com/PupppyLoverr/gabbledobo-71588/raw/main/nexi-cua/releases/nexi_cua-0.4.0-py3-none-any.whl"
fi
"$VENV/bin/python" -m pip install "$PACKAGE_SPEC"

mkdir -p "$HOME/.local/bin"
ln -sf "$VENV/bin/nexi-cua" "$ENTRYPOINT"
printf 'Installed nexi-cua. Ensure %s is on your PATH.\n' "$HOME/.local/bin"

if [ "$WITH_VISION" -eq 1 ]; then
    if [ "$SYSTEM" = Darwin ] && [ "$(uname -m)" = arm64 ]; then
        "$ENTRYPOINT" download-weights --mlx
    else
        printf 'For llama.cpp vision weights, run: nexi-cua download-weights\n'
    fi
fi

"$ENTRYPOINT" doctor
