"""mix_v3 = scaled xlam tool-calling + Inkling reasoning traces + chat/code/cua.

Reasoning traces become chat rows: user prompt -> assistant response WITH
the reasoning intact (reasoning distillation — small model learns the
thinking patterns, not just answers).
"""
import json, random, sys
from pathlib import Path

def load_jsonl(p):
    return [json.loads(l) for l in open(p) if l.strip()]

def main():
    out = Path("common/data/mix_v3")
    out.mkdir(parents=True, exist_ok=True)
    rows = []

    # 1. carry over the proven xlam-heavy v2 mix
    v2 = load_jsonl("common/data/mix_v2/mix.jsonl")
    rows.extend(v2)
    print(f"v2 base rows: {len(v2)}")

    # 2. inkling reasoning traces as chat rows (skip unfinished/truncated)
    tp = Path("common/data/inkling_traces_v2.jsonl")
    n_traces = 0
    if tp.exists():
        for rec in load_jsonl(tp):
            if rec.get("finish") != "stop":
                continue  # truncated mid-answer: don't teach truncation
            rows.append({"messages": [
                {"role": "user", "content": rec["prompt"]},
                {"role": "assistant", "content": rec["response"]},
            ], "source": "inkling_trace_v2"})
            n_traces += 1
    # also the original 12 traces file if it has the same shape
    tp1 = Path("common/data/inkling_traces.jsonl")
    if tp1.exists():
        for rec in load_jsonl(tp1):
            prompt = rec.get("prompt"); resp = rec.get("response")
            if prompt and resp:
                rows.append({"messages": [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": resp},
                ], "source": "inkling_trace_v1"})
                n_traces += 1
    print(f"inkling trace rows: {n_traces}")

    random.Random(7).shuffle(rows)
    with open(out / "mix.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps({"messages": r["messages"]}) + "\n")
    json.dump({"rows": len(rows), "v2_base": len(v2), "traces": n_traces},
              open(out / "manifest.json", "w"), indent=2)
    print(f"total rows: {len(rows)}")

if __name__ == "__main__":
    main()
