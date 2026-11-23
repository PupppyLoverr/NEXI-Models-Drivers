"""Merge a LoRA adapter into its base and save full bf16 weights.

Usage: python -m common.train.merge_lora --base <hf> --adapter <dir> --out <dir>
"""
import argparse

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    model = AutoModelForCausalLM.from_pretrained(a.base, torch_dtype=torch.bfloat16)
    model = PeftModel.from_pretrained(model, a.adapter)
    model = model.merge_and_unload()
    model.save_pretrained(a.out)
    AutoTokenizer.from_pretrained(a.base).save_pretrained(a.out)
    print(f"merged -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
