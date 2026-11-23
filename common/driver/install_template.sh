#!/usr/bin/env bash
# NEXI tier installer template — fill MODEL_URL + SHA256 per release.
# Usage: install.sh [dest_dir]
set -euo pipefail
DEST=${1:-./models}
MODEL_URL="{{MODEL_URL}}"
SHA256="{{SHA256}}"
MODEL_FILE="{{MODEL_FILE}}"
mkdir -p "$DEST"
curl -fL --retry 3 -o "$DEST/$MODEL_FILE" "$MODEL_URL"
echo "$SHA256  $DEST/$MODEL_FILE" | sha256sum -c -
echo "verified $DEST/$MODEL_FILE"
