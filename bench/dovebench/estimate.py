"""Cost and time estimate for a benchmark plan.

Defaults are assumptions until a pilot run calibrates them (`--from-run`):
steps per attempt, observation and output tokens per step, model seconds per
step and VM reset time. Each step resends the whole history; with prompt
caching the prefix and earlier turns are cache reads, and each turn's new
suffix is a cache write. Prices are Anthropic first-party list prices
(per million tokens) as cached on 2026-10-06; check them before a run.
"""

from __future__ import annotations

import json
from pathlib import Path

PRICES = {  # input, output, cache read; cache write = 1.25 x input (5-minute TTL)
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),  # cache-read price assumed at 0.1 x input; not in the cached table
    "claude-fable-5-1": (10.00, 50.00, 0.25),
}
SECONDS_PER_STEP = {"claude-opus-5-5": 9.0, "claude-sonnet-5-5": 6.0, "claude-haiku-5-5": 2.5, "claude-fable-5-1": 15.0}
OUTPUT_PER_STEP = {"claude-opus-5-5": 700, "claude-sonnet-5-5": 600, "claude-haiku-5-5": 400, "claude-fable-5-1": 900}
SUITE_TASKS = {"osworld": 100, "waa": 60, "macarena": 40, "local": 4}
RESET_SECONDS = {"osworld": 75, "waa": 120, "macarena": 90, "local": 2}
STEPS = {"osworld": 15, "waa": 15, "macarena": 15, "local": 4}
# Prefix = tool list + system prompt + server instructions, measured on Linux at 4 chars/token (the real
# tokenizer may count JSON schemas higher; `count_tokens` is free and settles it): dove-driver 0.37 and stock
# cua-driver 0.37 both list 66 tools in 230 KB, ~56.5k tokens; the screenshot-only allowlist is 15 tools,
# ~18k. W5 lazy disclosure would shrink A/G/B, which is where most of the token cost below sits.
PREFIX_TOKENS = {"A": 57_000, "G": 57_000, "B": 57_000, "C": 57_000, "D": 18_500, "E": 57_000}
OBS_PER_STEP = {"A": 1_200, "G": 900, "B": 1_500, "C": 2_500, "D": 1_600, "E": 2_800}


def attempt_cost(model: str, prefix: int, obs: int, out: int, steps: int) -> float:
    pin, pout, pread = PRICES.get(model, PRICES["claude-opus-5-5"])
    pwrite = 1.25 * pin
    read = write = 0
    for i in range(steps):
        history = i * (obs + out)
        if i == 0:
            write += prefix + obs
        else:
            read += prefix + history
            write += obs + out
    return (read * pread + write * pwrite + steps * out * pout) / 1e6


def measure(run_dir: Path) -> dict:
    """Per (suite, config): mean steps, prefix and observation tokens, wall time from a pilot run."""
    out: dict = {}
    for line in (run_dir / "attempts.jsonl").read_text().splitlines():
        a = json.loads(line)
        k = (a["suite"], a["config"])
        m = out.setdefault(k, {"n": 0, "steps": 0, "obs": 0, "wall": 0.0})
        m["n"] += 1
        m["steps"] += a["steps"]
        m["obs"] += a["observation_tokens"]
        m["wall"] += a["wall_time"]
    for m in out.values():
        m["steps"] /= m["n"]
        m["obs_per_step"] = m["obs"] / max(1, m["steps"] * m["n"])
        m["wall"] /= m["n"]
    return out


def plan(suites, configs, models, runs, step_limit, tasks=None, measured=None, parallel="osworld=8,waa=4,macarena=2"):
    par = dict(kv.split("=") for kv in parallel.split(",")) if isinstance(parallel, str) else parallel
    rows = []
    for s in suites:
        n_tasks = SUITE_TASKS.get(s, 0) if tasks is None or len(suites) > 1 else tasks
        for c in configs:
            for m in models:
                mm = (measured or {}).get((s, c), {})
                steps = min(step_limit, round(mm.get("steps") or STEPS.get(s, 15)))
                obs = int(mm.get("obs_per_step") or OBS_PER_STEP.get(c, 1500))
                out = OUTPUT_PER_STEP.get(m, 600)
                attempts = n_tasks * runs
                cost = attempts * attempt_cost(m, PREFIX_TOKENS.get(c, 58_000), obs, out, steps)
                secs = attempts * (RESET_SECONDS.get(s, 90) + steps * (SECONDS_PER_STEP.get(m, 8) + 0.6))
                rows.append({"suite": s, "config": c, "model": m, "attempts": attempts, "steps": steps,
                             "cost_usd": cost, "hours": secs / 3600, "parallel": int(par.get(s, 1))})
    return rows


def render(rows) -> str:
    L = ["| Suite | Config | Model | Attempts | Steps/attempt | Cost (USD) | Machine-hours |",
         "|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['suite']} | {r['config']} | {r['model']} | {r['attempts']} | {r['steps']} | "
                 f"{r['cost_usd']:,.0f} | {r['hours']:.1f} |")
    total = sum(r["cost_usd"] for r in rows)
    by_suite: dict = {}
    for r in rows:
        by_suite.setdefault(r["suite"], [0.0, r["parallel"]])[0] += r["hours"]
    L += ["", f"Total API cost: about ${total:,.0f}.",
          "Wall-clock at the given VM parallelism: "
          + ", ".join(f"{s} {h / p:.0f} h on {p} VM(s)" for s, (h, p) in by_suite.items()) + "."]
    return "\n".join(L)
