import argparse
import fnmatch
import shutil
from pathlib import Path

import torch
from peft import PeftModel


def copy_base_assets(base_dir: Path, out_dir: Path) -> None:
    patterns = (
        "tokenizer*",
        "processor*",
        "preprocessor*",
        "image_processor*",
        "feature_extractor*",
        "chat_template*",
        "special_tokens_map.json",
        "added_tokens.json",
        "vocab.*",
        "merges.txt",
        "spiece.model",
        "sentencepiece.bpe.model",
    )
    for source in base_dir.iterdir():
        if source.is_file() and any(fnmatch.fnmatch(source.name, pattern) for pattern in patterns):
            shutil.copy2(source, out_dir / source.name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_hf_dir")
    parser.add_argument("adapter_dir")
    parser.add_argument("out_hf_dir")
    args = parser.parse_args()

    base_dir = Path(args.base_hf_dir).resolve()
    adapter_dir = Path(args.adapter_dir).resolve()
    out_dir = Path(args.out_hf_dir).resolve()
    if not base_dir.is_dir():
        parser.error(f"base model directory does not exist: {base_dir}")
    if not adapter_dir.is_dir():
        parser.error(f"adapter directory does not exist: {adapter_dir}")

    try:
        from transformers import AutoModelForCausalLM

        model = AutoModelForCausalLM.from_pretrained(
            str(base_dir), dtype=torch.bfloat16, low_cpu_mem_usage=True
        )
    except Exception as exc:
        from transformers import AutoModelForImageTextToText

        print(f"CausalLM load failed, falling back: {exc!r}")
        model = AutoModelForImageTextToText.from_pretrained(
            str(base_dir), dtype=torch.bfloat16, low_cpu_mem_usage=True
        )

    merged = PeftModel.from_pretrained(model, str(adapter_dir)).merge_and_unload()
    merged.to(dtype=torch.bfloat16)
    out_dir.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(str(out_dir), safe_serialization=True)
    copy_base_assets(base_dir, out_dir)


if __name__ == "__main__":
    main()
