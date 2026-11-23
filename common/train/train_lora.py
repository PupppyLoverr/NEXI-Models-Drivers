"""CPU LoRA fine-tune for NEXI tiers (TRL SFTTrainer + PEFT).

Designed for the 31 GB RAM budget: gradient checkpointing off by default on
CPU (it saves little vs LoRA memory), seq len 1024-2048, batch 1 + grad accum.

Usage:
    python -m common.train.train_lora \
        --base Qwen/Qwen3.5-2B --mix common/data/mix_v1/mix.jsonl \
        --out nexi-4gb/adapter --steps 200 --seq-len 1024
"""
import argparse
import json
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--mix", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--seq-len", type=int, default=1024)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--grad-accum", type=int, default=8)
    a = ap.parse_args()

    import torch
    from datasets import load_dataset
    from peft import LoraConfig, get_peft_model
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              Trainer, TrainingArguments)

    torch.set_num_threads(torch.get_num_threads())  # all cores

    ds = load_dataset("json", data_files=a.mix, split="train")
    tok = AutoTokenizer.from_pretrained(a.base)

    def to_text(row):
        return {"text": tok.apply_chat_template(
            row["messages"], tokenize=False, add_generation_prompt=False)}
    ds = ds.map(to_text, remove_columns=[c for c in ds.column_names
                                         if c != "text"])

    model = AutoModelForCausalLM.from_pretrained(
        a.base, torch_dtype=torch.float32)
    model.config.use_cache = False
    lora = LoraConfig(r=a.rank, lora_alpha=32, lora_dropout=0.05,
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
                      task_type="CAUSAL_LM")
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    targs = TrainingArguments(
        output_dir=a.out,
        max_steps=a.steps,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=a.grad_accum,
        learning_rate=a.lr,
        lr_scheduler_type="cosine",
        warmup_steps=max(10, a.steps // 20),
        logging_steps=10,
        save_steps=a.steps,
        report_to=[],
        bf16=False, fp16=False,
        dataloader_num_workers=0,
        use_cpu=True,
    )

    def collate(batch):
        texts = [b["text"] for b in batch]
        enc = tok(texts, return_tensors="pt", padding=True,
                  truncation=True, max_length=a.seq_len)
        enc["labels"] = enc["input_ids"].clone()
        return enc

    trainer = Trainer(model=model, args=targs, train_dataset=ds,
                      data_collator=collate)
    t0 = time.time()
    trainer.train()
    wall = time.time() - t0

    out = Path(a.out)
    model.save_pretrained(out)
    tok.save_pretrained(out)
    (out / "train_report.json").write_text(json.dumps({
        "base": a.base, "mix": a.mix, "steps": a.steps,
        "seq_len": a.seq_len, "rank": a.rank, "lr": a.lr,
        "wall_seconds": round(wall, 1),
        "train_loss": trainer.state.log_history[-1].get("loss"),
    }, indent=2) + "\n")
    print(f"saved adapter -> {out} ({wall:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
