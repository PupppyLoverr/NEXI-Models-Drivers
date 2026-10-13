"""Build the shared NEXI SFT mix + held-out tool/CUA eval sets (seed 2026).
usage: python build_mix.py <nexi-cua dir> <out dir> [n_train=2400]"""
import ast, hashlib, importlib, json, os, random, re, sys, types

from datasets import load_dataset

cua_dir, out, n_train = sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 2400
os.makedirs(out, exist_ok=True)
SEED = 2026
MIX = {"coding": 0.30, "tool": 0.30, "cua": 0.25, "chat": 0.15}
counts = {k: int(n_train * v) for k, v in MIX.items()}
counts["coding"] += n_train - sum(counts.values())

# import nexi_cua.training.synth without the package __init__ (which pulls torch)
pkg = types.ModuleType("nexi_cua"); pkg.__path__ = [os.path.join(cua_dir, "nexi_cua")]; sys.modules["nexi_cua"] = pkg
sub = types.ModuleType("nexi_cua.training"); sub.__path__ = [os.path.join(cua_dir, "nexi_cua", "training")]; sys.modules["nexi_cua.training"] = sub
synth = importlib.import_module("nexi_cua.training.synth")

CUA_SYS = ("You operate a computer through its accessibility tree. Pick the single best next action for the goal. "
           "Reply with only the action number, or NONE if no listed action achieves the goal.")


def cua_row(s):
    o = s.obs
    lines = [f"Goal: {o.goal}"]
    app = getattr(o.application, "name", "")
    if app:
        lines.append(f"App: {app}")
    if o.browser is not None:
        lines.append(f"URL: {o.browser.url} | Title: {o.browser.title}")
    lines.append("Elements:")
    for e in o.elements:
        t = f'[{e.id}] {e.role} "{e.name}"'
        if e.value:
            t += f' value="{e.value}"'
        if not e.enabled:
            t += " (disabled)"
        if e.focused:
            t += " (focused)"
        if e.checked:
            t += " (checked)"
        lines.append(t)
    lines.append("Actions:")
    lines += [f"{i + 1}. {c}" for i, c in enumerate(s.candidates)]
    ans = "NONE" if s.correct_idx is None else str(s.correct_idx + 1)
    return {"source": "cua", "kind": s.kind, "messages": [
        {"role": "system", "content": CUA_SYS}, {"role": "user", "content": "\n".join(lines)},
        {"role": "assistant", "content": ans}]}


ROLE = {"system": "system", "human": "user", "gpt": "assistant"}


TOOL_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.S)


def loads_lenient(s):
    s = s.strip()
    for cand in (s, s.replace("\\n", "\n").strip()):
        try:
            return json.loads(cand)
        except Exception:
            pass
        try:
            return ast.literal_eval(re.sub(r"\b(true|false|null)\b", lambda m: {"true": "True", "false": "False", "null": "None"}[m.group(1)], cand))
        except Exception:
            pass
    return None


def canonical_calls(text):
    """Rewrite every <tool_call> as canonical JSON {"name", "arguments"}; None if any call is malformed."""
    out = []
    for m in TOOL_RE.findall(text):
        j = loads_lenient(m)
        if not isinstance(j, dict):
            return None
        args = j.get("arguments", {})
        if isinstance(args, str):
            args = loads_lenient(args)
        if not isinstance(args, dict):
            return None
        name = j.get("name", args.pop("name", None) if "name" not in j else None)
        if not isinstance(name, str) or not name:
            return None
        out.append("<tool_call>\n" + json.dumps({"name": name, "arguments": args}, ensure_ascii=False) + "\n</tool_call>")
    return "\n".join(out)


def hermes_row(r):
    conv = r["conversations"]
    if any(c["from"] not in ROLE for c in conv) or conv[-1]["from"] != "gpt":
        return None
    msgs = [{"role": ROLE[c["from"]], "content": c["value"].replace("\\n", "\n")} for c in conv]
    if "<tool_call>" in msgs[-1]["content"]:
        canon = canonical_calls(conv[-1]["value"])
        if not canon:
            return None
        msgs[-1]["content"] = canon
    return {"source": "tool", "messages": msgs}


h = load_dataset("NousResearch/hermes-function-calling-v1", "func_calling_singleturn", split="train").shuffle(seed=SEED)
hrows = [x for x in (hermes_row(r) for r in h) if x]
tool_eval, tool_pool = hrows[-150:], hrows[:-150]

code = load_dataset("bigcode/self-oss-instruct-sc2-exec-filter-50k", split="train").shuffle(seed=SEED)
code_rows = [{"source": "coding", "messages": [{"role": "user", "content": r["instruction"]},
                                               {"role": "assistant", "content": r["response"]}]}
             for r in code.select(range(4000)) if len(r["response"]) < 3000][: counts["coding"]]

chat = load_dataset("HuggingFaceTB/smoltalk", "smol-magpie-ultra", split="train").shuffle(seed=SEED).select(range(6000))
chat_rows = [{"source": "chat", "messages": r["messages"]} for r in chat
             if r["messages"][-1]["role"] == "assistant" and r["quality"] in ("good", "excellent")
             and (r["conversation_tokens"] or 0) < 800][: counts["chat"]]

cua_train = [cua_row(s) for s in synth.generate(counts["cua"], seed=SEED)]
cua_eval = [cua_row(s) for s in synth.generate(200, seed=99991)]
train = code_rows + tool_pool[: counts["tool"]] + cua_train + chat_rows
random.Random(SEED).shuffle(train)


def dump(name, rows):
    p = os.path.join(out, name)
    with open(p, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"rows": len(rows), "sha256": hashlib.sha256(open(p, "rb").read()).hexdigest()}


manifest = {"seed": SEED, "mix_target": counts,
            "sources": {"coding": "bigcode/self-oss-instruct-sc2-exec-filter-50k (ODC-By)",
                        "tool": "NousResearch/hermes-function-calling-v1 func_calling_singleturn (Apache-2.0)",
                        "cua": "PupppyLoverr/gabbledobo-71588 nexi-cua synth.generate (seed 2026 train / 99991 eval)",
                        "chat": "HuggingFaceTB/smoltalk smol-magpie-ultra (Apache-2.0)"},
            "train.jsonl": dump("train.jsonl", train), "eval_tool.jsonl": dump("eval_tool.jsonl", tool_eval),
            "eval_cua.jsonl": dump("eval_cua.jsonl", cua_eval),
            "train_by_source": {s: sum(1 for r in train if r["source"] == s) for s in MIX}}
json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=2)
print(json.dumps(manifest, indent=2))
