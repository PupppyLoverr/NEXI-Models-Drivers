#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
venv_dir="${VENV_DIR:-.venv}"
"${PYTHON:-python3}" -m venv "$venv_dir"
"$venv_dir/bin/python" -m pip install "pip==25.1.1"
"$venv_dir/bin/python" -m pip install --require-hashes -r requirements.txt
echo 'Setup complete. Model download is separate: .venv/bin/python -m nexi_tts download'
