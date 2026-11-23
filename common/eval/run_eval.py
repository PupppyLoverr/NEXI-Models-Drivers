"""Run held-out evals against an HF checkpoint (base or merged).

Usage:
    python -m common.eval.run_eval --model <hf_or_dir> --sets tool_call,cua \
        --n 40 --json results.json
"""
import argparse
import json
import re
import time
from pathlib import Path

from .heldout import SETS


def check_row(row: dict, output: str) -> bool:
    c = row["check"]
    if c["type"] == "tool_call":
        m = re.search(r"<tool_call>(.*?)</tool_call>", output, re.S)
        if not m:
            return False
        try:
            call = json.loads(m.group(1))
        except Exception:
            return False
        return call.get("name") == c["name"] and call.get("arguments") == c["arguments"]
    if c["type"] == "exact":
        return output.strip() == c["expected"]
    if c["type"] == "func":
        return bool(row["_check_func"](output))
    if c["type"] == "humaneval":
        return _humaneval_check(row, output)
    return False


def _humaneval_check(row: dict, output: str) -> bool:
    code = re.sub(r"```(?:python)?|```", "", output).strip()
    ns: dict = {}
    try:
        exec(code, ns)
        exec(row["check"]["test"], ns)
        ns["check"](ns[row["check"]["entry_point"]])
        return True
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--sets", default="tool_call,cua,ifeval")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--max-new", type=int, default=128)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForCausalLM.from_pretrained(
        a.model, torch_dtype=torch.float32).eval()

    results = {}
    for name in a.sets.split(","):
        rows = SETS[name](n=a.n) if name != "humaneval" else SETS[name](n=a.n)
        rows = rows[:a.n]
        passed, lat = 0, []
        for row in rows:
            ids = tok.apply_chat_template(row["prompt_messages"],
                                          add_generation_prompt=True,
                                          return_dict=True,
                                          return_tensors="pt")["input_ids"]
            t0 = time.time()
            with torch.no_grad():
                out = model.generate(ids, max_new_tokens=a.max_new,
                                     do_sample=False,
                                     pad_token_id=tok.eos_token_id)
            lat.append(time.time() - t0)
            text = tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True)
            passed += bool(check_row(row, text))
        results[name] = {
            "n": len(rows), "passed": passed,
            "accuracy": round(passed / len(rows), 4) if rows else None,
            "avg_gen_seconds": round(sum(lat) / len(lat), 2) if lat else None,
        }
        print(json.dumps({name: results[name]}))
    if a.json:
        Path(a.json).write_text(json.dumps({"model": a.model,
                                            "results": results}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
