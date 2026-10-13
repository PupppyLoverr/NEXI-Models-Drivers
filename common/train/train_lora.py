"""NEXI CPU LoRA trainer. Loss on the final assistant turn only; stops cleanly at --max-seconds.
usage: python train_lora.py --base <hf_dir> --data train.jsonl --out <dir> --max-seconds N [--seq 1024]"""
import argparse, json, os, time

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoTokenizer, Trainer, TrainerCallback, TrainingArguments

ap = argparse.ArgumentParser()
ap.add_argument("--base", required=True)
ap.add_argument("--data", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--max-seconds", type=int, required=True)
ap.add_argument("--seq", type=int, default=1024)
ap.add_argument("--dtype", default="bf16", choices=["bf16", "fp32"])
ap.add_argument("--lr", type=float, default=2e-4)
ap.add_argument("--grad-accum", type=int, default=4)
ap.add_argument("--r", type=int, default=16)
ap.add_argument("--gc", type=int, default=1)
ap.add_argument("--save-every", type=int, default=10)
args = ap.parse_args()
T0 = time.time()
torch.set_num_threads(os.cpu_count())
torch.manual_seed(2026)
dtype = {"fp32": torch.float32, "bf16": torch.bfloat16}[args.dtype]

tok = AutoTokenizer.from_pretrained(args.base)


def render(msgs, gen):
    return tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=gen, enable_thinking=False)


probe = render([{"role": "user", "content": "x"}, {"role": "assistant", "content": "ZQZQ"}], False)
END = probe[probe.rindex("ZQZQ") + 4:]
assert END.strip(), f"could not derive end-of-turn marker from template: {probe!r}"


def encode(row):
    msgs = row["messages"]
    prompt = render(msgs[:-1], True)
    p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    ids = tok(prompt + msgs[-1]["content"] + END, add_special_tokens=False)["input_ids"]
    if ids[: len(p_ids)] != p_ids or len(ids) > args.seq or len(ids) <= len(p_ids):
        return None
    return {"input_ids": ids, "labels": [-100] * len(p_ids) + ids[len(p_ids):]}


rows = [json.loads(l) for l in open(args.data)]
data, skipped = [], 0
for r in rows:
    e = encode(r)
    if e is None:
        skipped += 1
    else:
        e["source"] = r["source"]
        data.append(e)
print(f"END={END!r} examples={len(data)} skipped={skipped}", flush=True)


class DS(torch.utils.data.Dataset):
    def __len__(self):
        return len(data)

    def __getitem__(self, i):
        return data[i]


def collate(batch):
    b = batch[0]
    return {"input_ids": torch.tensor([b["input_ids"]]), "labels": torch.tensor([b["labels"]]),
            "attention_mask": torch.ones(1, len(b["input_ids"]), dtype=torch.long)}


try:
    from transformers import AutoModelForCausalLM
    model = AutoModelForCausalLM.from_pretrained(args.base, dtype=dtype, low_cpu_mem_usage=True)
except Exception as e:
    from transformers import AutoModelForImageTextToText
    print("CausalLM load failed, falling back:", repr(e)[:300])
    model = AutoModelForImageTextToText.from_pretrained(args.base, dtype=dtype, low_cpu_mem_usage=True)
model.config.use_cache = False
if args.gc:
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
model = get_peft_model(model, LoraConfig(
    r=args.r, lora_alpha=2 * args.r, lora_dropout=0.05, target_modules="all-linear",
    exclude_modules=r".*(visual|vision|audio|multi_modal_projector|mm_projector).*", task_type="CAUSAL_LM"))
model.print_trainable_parameters()


class Deadline(TrainerCallback):
    def on_step_end(self, a, state, control, **kw):
        if time.time() - T0 > args.max_seconds:
            control.should_training_stop = True
            control.should_save = True


targs = TrainingArguments(
    output_dir=args.out, per_device_train_batch_size=1, gradient_accumulation_steps=args.grad_accum,
    learning_rate=args.lr, lr_scheduler_type="constant_with_warmup", warmup_steps=3,
    max_steps=max(1, len(data) // args.grad_accum), logging_steps=1, save_steps=args.save_every,
    save_total_limit=2, report_to=[], use_cpu=True, dataloader_num_workers=0,
    remove_unused_columns=False, seed=2026, data_seed=2026)
trainer = Trainer(model=model, args=targs, train_dataset=DS(), data_collator=collate, callbacks=[Deadline()])
has_ckpt = any(d.startswith("checkpoint-") for d in os.listdir(args.out)) if os.path.isdir(args.out) else False
trainer.train(resume_from_checkpoint=has_ckpt or None)
model.save_pretrained(os.path.join(args.out, "adapter"))
tok.save_pretrained(os.path.join(args.out, "adapter"))
st = trainer.state
seen = st.global_step * args.grad_accum
summary = {
    "base": args.base, "dtype": args.dtype, "seq": args.seq, "lr": args.lr, "grad_accum": args.grad_accum,
    "lora_r": args.r, "gc": args.gc, "optimizer_steps": st.global_step, "examples_seen": seen,
    "examples_available": len(data), "skipped_too_long": skipped,
    "sources_seen": {s: sum(1 for d in data[:seen] if d["source"] == s) for s in sorted({d["source"] for d in data})},
    "tokens_seen": sum(len(d["input_ids"]) for d in data[:seen]),
    "wall_s": round(time.time() - T0), "log_history": st.log_history,
}
json.dump(summary, open(os.path.join(args.out, "train_summary.json"), "w"), indent=2)
print(json.dumps({k: v for k, v in summary.items() if k != "log_history"}, indent=2))
