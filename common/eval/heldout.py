"""Held-out eval sets. Each returns a list of {"prompt_messages", "check", "meta"}.

Held-out means: never in the training mix. The synthetic generators here use
different tool names/verbs/structures than common/data so overlap is measurable
as zero, not assumed.
"""
import json
import random


def tool_call_set(n: int = 40, seed: int = 13) -> list[dict]:
    rng = random.Random(seed)
    # Held-out tools: NOT the ones in the training mix.
    cases = [
        ("create_calendar_event", "Put lunch with Sam on Friday on my calendar",
         {"title": "Lunch with Sam", "day": "Friday"}),
        ("translate_text", "Translate 'good morning' into Spanish",
         {"text": "good morning", "target_language": "Spanish"}),
        ("play_music", "Play some jazz",
         {"query": "jazz"}),
        ("read_file", "Show me the contents of report.txt",
         {"path": "report.txt"}),
        ("get_stock_price", "What's NVDA trading at?",
         {"symbol": "NVDA"}),
    ]
    rows = []
    for i in range(n):
        name, q, args = cases[i % len(cases)]
        rows.append({
            "prompt_messages": [
                {"role": "system", "content": "You can call tools. Reply with "
                 "<tool_call>{\"name\": ..., \"arguments\": {...}}</tool_call>."},
                {"role": "user", "content": q},
            ],
            "check": {"type": "tool_call", "name": name, "arguments": args},
        })
    return rows


def cua_action_set(n: int = 40, seed: int = 17) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        right_id = f"target-{i}"
        candidates = [{"id": right_id, "action": "click", "label": "Checkout"}]
        candidates += [{"id": f"decoy-{i}-{j}", "action": "click",
                        "label": rng.choice(["Cancel", "Help", "Menu"])}
                       for j in range(3)]
        rng.shuffle(candidates)
        rows.append({
            "prompt_messages": [
                {"role": "user", "content":
                 f"Goal: proceed to checkout\nCandidates: {json.dumps(candidates)}\n"
                 "Reply with the id of the best next action."},
            ],
            "check": {"type": "exact", "expected": right_id},
        })
    return rows


def ifeval_set(n: int = 30, seed: int = 19) -> list[dict]:
    """Local instruction-following checks (no external dep)."""
    rng = random.Random(seed)
    specs = [
        ("Write a haiku about rain. Use exactly three lines.",
         lambda t: t.count("\n") == 2),
        ("List three colors. Answer with a JSON array only.",
         lambda t: _json_list_len(t) == 3),
        ("Explain gravity in one sentence ending with the word 'pull'.",
         lambda t: t.rstrip().endswith("pull")),
        ("Reply to this with the single word: ACK",
         lambda t: t.strip() == "ACK"),
        ("Give me a two-item grocery list, one item per line, no numbers.",
         lambda t: len([l for l in t.strip().split("\n") if l.strip()]) == 2),
    ]
    rows = []
    for i in range(n):
        prompt, check = specs[i % len(specs)]
        rows.append({
            "prompt_messages": [{"role": "user", "content": prompt}],
            "check": {"type": "func", "spec_index": i % len(specs)},
            "_check_func": check,
        })
    return rows


def _json_list_len(t: str) -> int:
    try:
        v = json.loads(t.strip().strip("`"))
        return len(v) if isinstance(v, list) else -1
    except Exception:
        return -1


def humaneval_subset(n: int = 10) -> list[dict]:
    """HumanEval prompts from evalplus (downloads once, ~100KB)."""
    try:
        from datasets import load_dataset
        ds = load_dataset("evalplus/humanevalplus", split="test")
        rows = []
        for ex in list(ds)[:n]:
            rows.append({
                "prompt_messages": [{"role": "user", "content":
                                     ex["prompt"] + "\n# Return only the completed function."}],
                "check": {"type": "humaneval", "task_id": ex["task_id"],
                          "test": ex["test"], "entry_point": ex["entry_point"]},
            })
        return rows
    except Exception as e:
        print(f"[eval] humaneval unavailable: {e}; returning empty")
        return []


SETS = {"tool_call": tool_call_set, "cua": cua_action_set,
        "ifeval": ifeval_set, "humaneval": humaneval_subset}
