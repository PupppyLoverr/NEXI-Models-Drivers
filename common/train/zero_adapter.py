"""Write an untrained (B=0) LoRA adapter with train_lora.py's config, so base models go through the same merge/export path as tuned ones.
usage: python zero_adapter.py <base_hf_dir> <adapter_out_dir>"""
import os
import sys

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM

base, adapter_dir = sys.argv[1:3]
if os.path.exists(adapter_dir):
    raise FileExistsError(f"Refusing to overwrite existing adapter: {adapter_dir}")

try:
    model = AutoModelForCausalLM.from_pretrained(
        base, dtype=torch.bfloat16, low_cpu_mem_usage=True
    )
except Exception as exc:
    print("CausalLM load failed, falling back:", repr(exc)[:300], flush=True)
    from transformers import AutoModelForImageTextToText

    model = AutoModelForImageTextToText.from_pretrained(
        base, dtype=torch.bfloat16, low_cpu_mem_usage=True
    )

model.config.use_cache = False
model = get_peft_model(
    model,
    LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules="all-linear",
        exclude_modules=r".*(visual|vision|audio|multi_modal_projector|mm_projector).*",
        task_type="CAUSAL_LM",
    ),
)
b_tensors = [p for name, p in model.named_parameters() if "lora_B" in name]
if not b_tensors:
    raise RuntimeError("No LoRA B tensors were created")
nonzero = sum(torch.count_nonzero(p).item() for p in b_tensors)
if nonzero:
    raise RuntimeError(f"LoRA B tensors are not zero-initialized: {nonzero} nonzero values")
model.save_pretrained(adapter_dir, safe_serialization=True)
print(f"Saved zero-init adapter: {adapter_dir} ({len(b_tensors)} B tensors)", flush=True)
