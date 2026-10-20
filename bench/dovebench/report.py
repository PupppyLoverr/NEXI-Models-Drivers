"""Aggregate attempts into bench/results/<version>.json and .md, with gates.

Gates (ROADMAP "Reporting and gates"), per suite and model:
  - BLOCK if A's success rate is more than 2 points below B's and their CIs do not overlap;
  - BLOCK if A's tokens/task is more than 10% above B's.
Claim rule: "#1" may be written for a suite only where A (or G) beats both C
and D on success with non-overlapping CIs at equal or lower tokens/task, with
a real model (provider usage). Otherwise the report says no claim is made.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

from .stats import bootstrap_ci, overlap, percentile, task_means

METRICS = {
    "success": lambda a: 1.0 if a["success"] else 0.0,
    "tokens": lambda a: a["input_tokens"] + a["output_tokens"],
    "observation_tokens": lambda a: a["observation_tokens"],
    "wall_time": lambda a: a["wall_time"],
    "model_time": lambda a: a["model_time"],
    "driver_time": lambda a: a["driver_time"],
    "round_trips": lambda a: a["round_trips"],
    "steps": lambda a: a["steps"],
    "screenshots": lambda a: a["screenshots"],
}


def _semantic_share(a: dict) -> float | None:
    s, y = a["actions"].get("semantic", 0), a["actions"].get("synthetic", 0)
    return s / (s + y) if s + y else None


def aggregate(attempts: list[dict], latencies: dict | None = None) -> dict:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for a in attempts:
        groups[(a["suite"], a["config"], a["model_id"])].append(a)
    out: dict = {}
    for (suite, cfg, model), atts in sorted(groups.items()):
        by_task: dict[str, list[dict]] = defaultdict(list)
        for a in atts:
            by_task[a["task_id"]].append(a)
        row = {"tasks": len(by_task), "attempts": len(atts),
               "runs": max(len(v) for v in by_task.values()),
               "usage_source": "estimate" if any(a["usage_source"] != "provider" for a in atts) else "provider",
               "driver_version": sorted({a.get("driver_version", "") for a in atts}),
               "errors": sum(1 for a in atts if a.get("error")),
               "driver_errors_per_100_calls": round(100 * sum(a["driver_errors"] for a in atts) /
                                                    max(1, sum(a["round_trips"] for a in atts)), 2)}
        for name, f in METRICS.items():
            m, lo, hi = bootstrap_ci(task_means({t: [f(a) for a in v] for t, v in by_task.items()}))
            row[name] = {"mean": m, "lo": lo, "hi": hi}
        shares = {t: [s for s in (_semantic_share(a) for a in v) if s is not None] for t, v in by_task.items()}
        m, lo, hi = bootstrap_ci(task_means(shares))
        row["semantic_share"] = {"mean": m, "lo": lo, "hi": hi}
        row["actions"] = {k: sum(a["actions"].get(k, 0) for a in atts) for k in ("semantic", "synthetic", "unknown")}
        if latencies:
            lat = latencies.get((suite, cfg, model), {})
            row["tool_latency_ms"] = {t: {"n": len(v), "p50": round(1000 * percentile(v, .5), 1),
                                          "p95": round(1000 * percentile(v, .95), 1)} for t, v in sorted(lat.items())}
        out.setdefault(suite, {}).setdefault(cfg, {})[model] = row
    return out


def gates(agg: dict) -> list[dict]:
    res = []
    for suite, cfgs in agg.items():
        for model in cfgs.get("A", {}):
            a, b = cfgs["A"][model], cfgs.get("B", {}).get(model)
            if not b:
                res.append({"suite": suite, "model": model, "gate": "A vs B", "status": "SKIPPED",
                            "why": "no B results"})
                continue
            drop = (b["success"]["mean"] - a["success"]["mean"]) * 100
            sep = not overlap(_ci(a["success"]), _ci(b["success"]))
            res.append({"suite": suite, "model": model, "gate": "success", "status":
                        "BLOCK" if drop > 2 and sep else "PASS",
                        "why": f"A {a['success']['mean']:.1%} vs B {b['success']['mean']:.1%} "
                               f"({'non-overlapping' if sep else 'overlapping'} CIs)"})
            rise = a["tokens"]["mean"] / b["tokens"]["mean"] - 1 if b["tokens"]["mean"] else 0.0
            res.append({"suite": suite, "model": model, "gate": "tokens/task", "status":
                        "BLOCK" if rise > 0.10 else "PASS",
                        "why": f"A {a['tokens']['mean']:.0f} vs B {b['tokens']['mean']:.0f} ({rise:+.1%})"})
    return res


def _ci(m: dict) -> tuple[float, float, float]:
    return (m["mean"], m["lo"], m["hi"])


def claims(agg: dict) -> list[dict]:
    res = []
    for suite, cfgs in agg.items():
        for cand in ("A", "G"):
            for model, row in cfgs.get(cand, {}).items():
                rivals = {r: cfgs.get(r, {}).get(model) for r in ("C", "D")}
                why = []
                if row["usage_source"] != "provider":
                    why.append("stub model with estimated tokens")
                for r, other in rivals.items():
                    if not other:
                        why.append(f"no {r} results")
                        continue
                    if not row["success"]["lo"] > other["success"]["hi"]:
                        why.append(f"success CI does not clear {r}'s")
                    if row["tokens"]["mean"] > other["tokens"]["mean"]:
                        why.append(f"more tokens/task than {r}")
                res.append({"suite": suite, "config": cand, "model": model, "allowed": not why,
                            "why": "; ".join(why) or "beats C and D on success with non-overlapping CIs "
                                                     "at equal or lower tokens/task"})
    return res


def _fmt(m: dict, kind: str) -> str:
    if m["mean"] != m["mean"]:  # NaN
        return "n/a"
    if kind == "pct":
        return f"{m['mean']:.1%} [{m['lo']:.1%}, {m['hi']:.1%}]"
    if kind == "s":
        return f"{m['mean']:.2f} s [{m['lo']:.2f}, {m['hi']:.2f}]"
    return f"{m['mean']:,.0f} [{m['lo']:,.0f}, {m['hi']:,.0f}]"


def markdown(meta: dict, agg: dict, gate_rows: list[dict], claim_rows: list[dict], labels: dict) -> str:
    L = [f"# dove-driver benchmark: {meta['version']}", ""]
    L += [f"- Harness commit: `{meta['harness_commit']}`; generated {meta['created']}",
          f"- Runs per task: {meta['runs']}; step limit: {meta['step_limit']}; model(s): "
          + ", ".join(f"`{m}`" for m in meta["models"]),
          "- Values are means over tasks with a 95% bootstrap CI (tasks resampled, 10,000 draws)."]
    if meta.get("stub"):
        L += ["", "> **Smoke run with the scripted stub model.** Token counts are estimates of the requests a "
              "model would have sent; success reflects the stub's fixed plan. These numbers test the harness. "
              "They do not rank drivers, and no claim is made from them."]
    if meta.get("notes"):
        L.append("")
        L += [f"- {note}" for note in meta["notes"]]
    for cid, u in sorted(meta.get("unavailable", {}).items()):
        L.append(f"- Configuration **{cid}** ({u['label']}) was not run: {u['why']}.")
    for suite, cfgs in agg.items():
        env = meta.get("environments", {}).get(suite, {})
        L += ["", f"## {suite}", "", "Environment: " + ", ".join(f"{k} `{v}`" for k, v in env.items()), ""]
        L += ["| Config | Model | Tasks×runs | Success | Tokens/task | Obs. tokens/task | Wall time/task | "
              "Model time | Driver time | Round trips | Semantic share | Screenshots | Driver errors/100 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for cfg in sorted(cfgs):
            for model, r in cfgs[cfg].items():
                L.append(f"| {cfg} | `{model}` | {r['tasks']}×{r['runs']} | {_fmt(r['success'], 'pct')} | "
                         f"{_fmt(r['tokens'], 'n')} | {_fmt(r['observation_tokens'], 'n')} | "
                         f"{_fmt(r['wall_time'], 's')} | {_fmt(r['model_time'], 's')} | "
                         f"{_fmt(r['driver_time'], 's')} | {_fmt(r['round_trips'], 'n')} | "
                         f"{_fmt(r['semantic_share'], 'pct')} | {r['screenshots']['mean']:.1f} | "
                         f"{r['driver_errors_per_100_calls']} |")
        L += ["", "Configurations: " + "; ".join(f"**{c}** {labels.get(c, '')}" for c in sorted(cfgs)) + "."]
        lat_rows = [(cfg, model, t, v) for cfg in sorted(cfgs) for model, r in cfgs[cfg].items()
                    for t, v in r.get("tool_latency_ms", {}).items()]
        if lat_rows:
            L += ["", "Tool latency (ms, p50 / p95):", "", "| Config | Tool | Calls | p50 | p95 |", "|---|---|---|---|---|"]
            L += [f"| {c} | `{t}` | {v['n']} | {v['p50']} | {v['p95']} |" for c, _m, t, v in lat_rows]
    L += ["", "## Release gates", "", "| Suite | Model | Gate | Status | Detail |", "|---|---|---|---|---|"]
    L += [f"| {g['suite']} | `{g['model']}` | {g['gate']} | {g['status']} | {g['why']} |" for g in gate_rows] or \
         ["| – | – | – | – | no A results |"]
    L += ["", "## Claims", ""]
    allowed = [c for c in claim_rows if c["allowed"]]
    for c in claim_rows:
        L.append(f"- {c['suite']}, {c['config']} with `{c['model']}`: "
                 + ("**#1 among the configurations measured here**" if c["allowed"] else "no claim")
                 + f" ({c['why']}).")
    if not allowed:
        L += ["", "No \"#1\" claim is made from this run."]
    return "\n".join(L) + "\n"


def load_attempts(run_dir: Path) -> tuple[list[dict], dict]:
    attempts = [json.loads(l) for l in (run_dir / "attempts.jsonl").read_text().splitlines() if l.strip()]
    lat: dict = defaultdict(lambda: defaultdict(list))
    for a in attempts:
        traj = run_dir / a["trajectory"]
        if not traj.exists():
            continue
        for line in traj.read_text().splitlines():
            ev = json.loads(line)
            if ev.get("kind") == "tool" and ev.get("latency"):
                lat[(a["suite"], a["config"], a["model_id"])][ev["name"]].append(ev["latency"])
    return attempts, lat


def write(run_dir: Path, out_dir: Path, meta: dict, labels: dict) -> tuple[Path, Path]:
    attempts, lat = load_attempts(run_dir)
    agg = aggregate(attempts, lat)
    g, c = gates(agg), claims(agg)
    meta = {**meta, "created": meta.get("created") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    out_dir.mkdir(parents=True, exist_ok=True)
    jp, mp = out_dir / f"{meta['version']}.json", out_dir / f"{meta['version']}.md"
    jp.write_text(json.dumps({"meta": meta, "results": agg, "gates": g, "claims": c}, indent=2) + "\n")
    mp.write_text(markdown(meta, agg, g, c, labels))
    return jp, mp
