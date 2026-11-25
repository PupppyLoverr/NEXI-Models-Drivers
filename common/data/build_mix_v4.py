"""mix_v4 = mix_v3 but reasoning traces are reformatted: reasoning first,
then a clearly delimited final-answer section. v3 taught the model to reason
but the reasoning noise polluted strict-format outputs; v4 teaches
reason-then-clean-answer discipline.

Extraction of the final answer from a trace:
- if the response ends with a code block, that block is the answer
- if it ends with a json object, that is the answer
- otherwise the last non-empty line(s) after the reasoning
"""
import json, random, re
from pathlib import Path

def load_jsonl(p):
    return [json.loads(l) for l in open(p) if l.strip()]

def extract_final(resp: str) -> str:
    code = re.findall(r'```(?:python|json)?\n(.*?)```', resp, re.S)
    if code:
        return '```python\n' + code[-1].strip() + '\n```'
    lines = [l for l in resp.strip().splitlines() if l.strip()]
    return lines[-1].strip() if lines else resp.strip()

def reformat(resp: str) -> str:
    final = extract_final(resp)
    if final in resp and resp.strip().endswith(final.strip().strip('`')):
        return resp
    body = resp.strip()
    if body.endswith(final):
        return resp
    return body + "\n\n### Final answer\n" + final

def main():
    out = Path("common/data/mix_v4")
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    v2 = load_jsonl("common/data/mix_v2/mix.jsonl")
    rows.extend(v2)

    n_traces = 0
    for tp in [Path("common/data/inkling_traces_v2.jsonl"), Path("common/data/inkling_traces.jsonl")]:
        if not tp.exists():
            continue
        for rec in load_jsonl(tp):
            if rec.get("finish") not in (None, "stop"):
                continue
            prompt, resp = rec.get("prompt"), rec.get("response")
            if not (prompt and resp):
                continue
            rows.append({"messages": [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": reformat(resp)},
            ], "source": tp.name})
            n_traces += 1

    random.Random(7).shuffle(rows)
    with open(out / "mix.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps({"messages": r["messages"]}) + "\n")
    json.dump({"rows": len(rows), "traces": n_traces}, open(out / "manifest.json", "w"), indent=2)
    print(f"rows: {len(rows)}, traces: {n_traces}")

if __name__ == "__main__":
    main()
