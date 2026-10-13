"""Convert a local trained HF Whisper checkpoint to int8 CTranslate2 with a manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nexi_stt.assets import digest
from nexi_stt.engine import offline_environment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    offline_environment()
    from ctranslate2.converters import TransformersConverter
    from transformers import WhisperTokenizerFast

    if args.output.exists():
        parser.error("Output exists; refusing to overwrite an exported model")
    if not (args.checkpoint / "model.safetensors").is_file():
        parser.error("Expected local safetensors Whisper checkpoint")
    converter = TransformersConverter(str(args.checkpoint.resolve()), load_as_float16=False)
    converter.convert(str(args.output), quantization="int8")
    tokenizer = WhisperTokenizerFast.from_pretrained(str(args.checkpoint), local_files_only=True)
    tokenizer.backend_tokenizer.save(str(args.output / "tokenizer.json"))
    files = [
        {"name": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
        for path in sorted(args.output.iterdir())
        if path.is_file()
    ]
    spec = {
        "upstream": "local Whisper export",
        "revision": digest(args.checkpoint / "model.safetensors"),
        "license": "MIT upstream; verify rights/consent for your training data",
        "provenance": "user-generated local export; quality requires held-out evaluation",
        "files": files,
    }
    (args.output / "nexi-assets.json").write_text(json.dumps(spec, indent=2) + "\n")
    print(f"Exported local int8 inference model: {args.output}")


if __name__ == "__main__":
    main()
