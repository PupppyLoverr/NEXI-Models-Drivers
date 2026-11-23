"""Build the NEXI training mix: chat + tool-calling + code + CUA-decision rows.

Pulls small, pinned slices of open datasets, normalizes them to chat-template
JSONL {"messages": [...]}, and writes a manifest with counts + sha256 so a mix
build is reproducible.

Usage:
    python -m common.data.build_mix --out common/data/mix_v1 --n-per-source 600
"""
import argparse
import hashlib
import json
import random
from pathlib import Path

SOURCES = {
    # name -> (hf repo, config, split, mapper name). Keep slices small: this
    # pipeline targets CPU LoRA, not pretraining.
    "tool_calling": {
        "repo": "Salesforce/xlam-function-calling-60k",
        "requires_auth": True,
        "fallback": "synthetic_tool_calling",
    },
    "chat": {
        "repo": "HuggingFaceH4/no_robots",
        "config": None,
        "split": "train",
        "mapper": "no_robots",
    },
    "code": {
        "repo": "ise-uiuc/Magicoder-Evol-Instruct-110K",
        "config": None,
        "split": "train",
        "mapper": "magicoder",
    },
    "cua_decision": {
        "repo": None,  # built synthetically: DOM-choice episodes
        "fallback": "synthetic_cua",
    },
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def map_no_robots(row: dict) -> dict | None:
    msgs = row.get("messages")
    if not msgs:
        return None
    return {"messages": [{"role": m["role"], "content": m["content"]} for m in msgs]}


def map_magicoder(row: dict) -> dict | None:
    problem, solution = row.get("instruction"), row.get("response")
    if not problem or not solution:
        return None
    return {"messages": [
        {"role": "user", "content": problem},
        {"role": "assistant", "content": solution},
    ]}


TOOLS = [
    {"name": "get_weather", "parameters": {"city": "string", "units": "string"}},
    {"name": "search_files", "parameters": {"query": "string", "path": "string"}},
    {"name": "send_message", "parameters": {"to": "string", "body": "string"}},
    {"name": "set_reminder", "parameters": {"time": "string", "text": "string"}},
    {"name": "open_app", "parameters": {"name": "string"}},
]

_TOOL_QUERIES = [
    ("get_weather", "What's the weather in {city}?", {"city": "Lisbon", "units": "metric"}),
    ("search_files", "Find my {thing} notes", {"query": "tax notes", "path": "~/Documents"}),
    ("send_message", "Text {person} I'll be late", {"to": "Maya", "body": "I'll be late"}),
    ("set_reminder", "Remind me to {task} at 6pm", {"time": "18:00", "text": "water the plants"}),
    ("open_app", "Open the {app} app", {"name": "calculator"}),
]


def synthetic_tool_calling(n: int, rng: random.Random) -> list[dict]:
    """Small synthetic tool-call set: teaches the <tool_call>{json}</tool_call>
    contract when the gated xlam set is unavailable. Clearly labeled synthetic."""
    rows = []
    for i in range(n):
        name, tmpl, args = rng.choice(_TOOL_QUERIES)
        user = rng.choice([tmpl.format(city="Lisbon", thing="tax", person="Maya",
                                     task="water the plants", app="calculator")])
        call = json.dumps({"name": name, "arguments": args})
        rows.append({"messages": [
            {"role": "system", "content": "You can call tools. Reply with "
             "<tool_call>{\"name\": ..., \"arguments\": {...}}</tool_call>."},
            {"role": "user", "content": user},
            {"role": "assistant", "content": f"<tool_call>{call}</tool_call>"},
        ], "source": "synthetic"})
    return rows


def synthetic_cua(n: int, rng: random.Random) -> list[dict]:
    """CUA-decision rows: given a goal + candidate UI actions, pick the right one.
    Mirrors the S1-style typed decision contract."""
    actions = [
        ("click the Search button", [{"id": "btn-search", "action": "click"}]),
        ("type into the email field", [{"id": "input-email", "action": "type"}]),
        ("scroll down to find the footer", [{"id": "page", "action": "scroll"}]),
        ("click the Submit button", [{"id": "btn-submit", "action": "click"}]),
    ]
    rows = []
    for i in range(n):
        goal, right = rng.choice(actions)
        choices = [right[0]] + [{"id": f"el-{j}", "action": "click"} for j in range(2)]
        rng.shuffle(choices)
        answer = next(c["id"] for c in choices if c["action"] == right[0]["action"]
                      and c["id"] == right[0]["id"])
        prompt = (f"Goal: {goal}\nCandidates: {json.dumps(choices)}\n"
                  "Reply with the id of the best next action.")
        rows.append({"messages": [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": answer},
        ], "source": "synthetic"})
    return rows


def build(out_dir: Path, n_per_source: int, seed: int = 7) -> Path:
    rng = random.Random(seed)
    rows: list[dict] = []
    manifest_sources = {}
    for name, spec in SOURCES.items():
        got: list[dict] = []
        if spec.get("repo"):
            try:
                from datasets import load_dataset  # imported lazily
                ds = load_dataset(spec["repo"], spec.get("config"),
                                  split=spec["split"])
                ds = ds.shuffle(seed=seed).select(range(min(n_per_source, len(ds))))
                mapper = globals()[f"map_{spec['mapper']}"]
                got = [r for r in (mapper(x) for x in ds) if r]
                for r in got:
                    r["source"] = spec["repo"]
            except Exception as e:  # gated repo / no network — use fallback
                print(f"[data] {spec['repo']} unavailable ({type(e).__name__}); "
                      f"using fallback")
        if not got and spec.get("fallback"):
            got = globals()[spec["fallback"]](n_per_source, rng)
        manifest_sources[name] = {"rows": len(got),
                                  "origin": got[0]["source"] if got else "none"}
        rows.extend(got)
    rng.shuffle(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    mix_path = out_dir / "mix.jsonl"
    with mix_path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    manifest = {
        "mix": "mix.jsonl",
        "sha256": sha256_file(mix_path),
        "total_rows": len(rows),
        "seed": seed,
        "sources": manifest_sources,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return mix_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="common/data/mix_v1")
    ap.add_argument("--n-per-source", type=int, default=600)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    build(Path(a.out), a.n_per_source, a.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
