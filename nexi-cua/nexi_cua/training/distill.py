"""Teacher-distillation scaffold (offline only — the runtime NEVER calls a
teacher; spec §14).

Labels synthetic (goal, state, candidates) with a larger LOCAL open model
running through llama.cpp's server, producing extra training rows for the
heads the generator can't label well (recovery, subtle intent, paraphrase
robustness). Everything runs on-device; no teacher call exists outside this
module.

Usage:
    llama-server -m <teacher.gguf> --port 8099 &
    python -m nexi_cua.training.distill --n 2000 --out weights/distill.jsonl
"""
from __future__ import annotations

import json
import urllib.request
from typing import Optional

from ..actions import candidate_actions
from ..training.synth import generate

PROMPT = """You are a computer-use planner. Given a goal and a UI element list,
choose the single best next action index (or -1 if none fits).

GOAL: {goal}
ELEMENTS:
{elements}
CANDIDATES:
{candidates}

Reply ONLY JSON: {{"pick": <int>, "confidence": <0-1>}}"""


def _server_call(prompt: str, port: int, max_tokens: int = 64) -> str:
    body = {"messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0, "max_tokens": max_tokens}
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read().decode())
    return out["choices"][0]["message"]["content"] or ""


def distill(n: int = 2000, port: int = 8099, out: str = "weights/distill.jsonl",
            seed: int = 77) -> dict:
    import re
    samples = generate(n, seed=seed)
    kept = dropped = 0
    with open(out, "w") as f:
        for s in samples:
            els = "\n".join(f"  {e.id} [{e.role}] {e.name!r} "
                            f"{'disabled' if not e.enabled else ''}"
                            for e in s.obs.elements[:80])
            cands = "\n".join(f"  {i}: {a.textual()}"
                              for i, a in enumerate(s.candidates[:80]))
            try:
                raw = _server_call(
                    PROMPT.format(goal=s.obs.goal, elements=els,
                                  candidates=cands), port)
            except Exception as e:
                raise RuntimeError(f"teacher unreachable on :{port}: {e}")
            m = re.search(r'"pick"\s*:\s*(-?\d+)', raw)
            if not m:
                dropped += 1
                continue
            pick = int(m.group(1))
            gold = s.correct_idx if s.correct_idx is not None else -1
            row = {
                "goal": s.obs.goal,
                "elements": [{"role": e.role, "name": e.name,
                              "enabled": e.enabled}
                             for e in s.obs.elements[:80]],
                "candidates": [a.textual() for a in s.candidates[:80]],
                "teacher_pick": pick, "generator_gold": gold,
                "agree": pick == gold,
            }
            f.write(json.dumps(row) + "\n")
            kept += 1
    return {"rows": kept, "dropped": dropped, "out": out}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--out", default="weights/distill.jsonl")
    a = ap.parse_args()
    print(json.dumps(distill(a.n, a.port, a.out), indent=2))
