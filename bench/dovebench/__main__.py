"""dove-bench command line.

    python3 -m dovebench subsets [--check]
    python3 -m dovebench run --suite local --configs A,C,D --runs 3 --model scripted --version smoke
    python3 -m dovebench report --run-dir bench/results/runs/<version> --version <version>
    python3 -m dovebench estimate [--from-run <run-dir>]

`run` is resumable: attempts already in <run-dir>/attempts.jsonl are skipped,
so an interrupted run continues where it stopped. A paid model needs
--allow-paid; the run prints its cost estimate first.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from . import estimate as est
from . import report, subsets
from .agent import run_attempt
from .configs import BENCH, REPO, load_all
from .mcp_client import McpClient

RESULTS = BENCH / "results"


def make_suite(name: str):
    if name == "local":
        from .suites.local import LocalSuite

        return LocalSuite()
    from .suites.desktop_env import make

    return make(name)


def make_model(spec: str, suite):
    if spec == "scripted":
        from .models.scripted import ScriptedModel

        return ScriptedModel(suite)
    if spec.startswith("anthropic:"):
        from .models.anthropic_model import AnthropicModel

        model_id, _, effort = spec.split(":", 1)[1].partition("@")
        return AnthropicModel(model_id, effort=effort or "medium")
    raise SystemExit(f"unknown model {spec!r}: use scripted or anthropic:<model-id>[@effort]")


def harness_commit() -> str:
    try:
        sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "bench"], capture_output=True,
                               text=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


def probe(c) -> str | None:
    """Start the driver once and check the tools the configuration needs. Local drivers only: a VM
    suite's driver is checked per attempt, inside the VM."""
    if not c.requires_tools or c.command[0].startswith("ssh"):
        return None
    try:
        with McpClient(c.command, env=c.env, timeout=30) as client:
            names = {t["name"] for t in client.tools}
    except Exception as e:
        return f"driver did not start: {e}"
    missing = [t for t in c.requires_tools if t not in names]
    return f"driver offers no {', '.join(missing)} tool" if missing else None


def cmd_run(a) -> int:
    suites = a.suite.split(",")
    models = a.model.split(",")
    configs = load_all(a.configs.split(",") if a.configs else None)
    run_dir = Path(a.run_dir or RESULTS / "runs" / a.version)
    run_dir.mkdir(parents=True, exist_ok=True)
    paid = [m for m in models if m != "scripted"]
    if paid:
        n_tasks = sum(len(subsets.load(s)) if s != "local" else 4 for s in suites)
        print(est.render(est.plan(suites, [c.id for c in configs], paid, a.runs, a.step_limit, tasks=n_tasks)))
        if not a.allow_paid:
            print("\nThis run calls a paid API. Re-run with --allow-paid once the estimate above is approved.")
            return 2

    usable, unavailable = [], {}
    for c in configs:
        why = c.unavailable() or probe(c)
        if why:
            print(f"config {c.id}: unavailable ({why}); skipped")
            unavailable[c.id] = {"label": c.label, "why": why}
        else:
            usable.append(c)
    done = set()
    attempts_path = run_dir / "attempts.jsonl"
    if attempts_path.exists():
        for line in attempts_path.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                done.add((d["suite"], d["task_id"], d["config"], d["model_id"], d["run"]))

    meta_path = run_dir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {
        "version": a.version, "harness_commit": harness_commit(), "runs": a.runs, "step_limit": a.step_limit,
        "models": [], "configs": {}, "environments": {}, "notes": a.note or [],
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    meta["stub"] = meta.get("stub", False) or "scripted" in models
    meta.setdefault("unavailable", {}).update(unavailable)

    for suite_name in suites:
        suite = make_suite(suite_name)
        tasks = suite.tasks(a.limit)
        meta["environments"][suite_name] = suite.environment()
        for spec in models:
            model = make_model(spec, suite)
            if model.model_id not in meta["models"]:
                meta["models"].append(model.model_id)
            for c in usable:
                meta["configs"][c.id] = {"label": c.label, "command": c.command, "env": c.env,
                                         "observation": c.observation, "notes": c.notes}
            meta_path.write_text(json.dumps(meta, indent=2) + "\n")
            # Interleave configurations within each run so drift (load, VM host) spreads evenly.
            for run in range(1, a.runs + 1):
                for task in tasks:
                    for c in usable:
                        key = (suite_name, task.id, c.id, model.model_id, run)
                        if key in done:
                            continue
                        rel = f"trajectories/{suite_name}/{c.id}/{model.model_id}/{task.id}.r{run}.jsonl"
                        att = run_attempt(task, c, model, suite, run, a.step_limit, run_dir / rel,
                                          save_screenshots=not a.no_screenshots)
                        rec = {"suite": suite_name, "domain": task.domain, "trajectory": rel, **asdict(att)}
                        with open(attempts_path, "a") as f:
                            f.write(json.dumps(rec) + "\n")
                        status = "pass" if att.success >= 1 else f"FAIL ({att.error or 'checker'})"
                        print(f"[{suite_name}] run {run} {c.id:>2} {task.id:<40} {status:<28} "
                              f"steps={att.steps} rt={att.round_trips} tok={att.tokens:,} "
                              f"wall={att.wall_time:.1f}s drv={att.driver_time:.2f}s", flush=True)
    return cmd_report(argparse.Namespace(run_dir=str(run_dir), version=a.version, out=a.out))


def cmd_report(a) -> int:
    run_dir = Path(a.run_dir)
    meta = json.loads((run_dir / "meta.json").read_text())
    labels = {k: v["label"] for k, v in meta.get("configs", {}).items()}
    jp, mp = report.write(run_dir, Path(a.out or RESULTS), {**meta, "version": a.version or meta["version"]}, labels)
    print(f"wrote {jp.relative_to(REPO) if jp.is_relative_to(REPO) else jp}")
    print(f"wrote {mp.relative_to(REPO) if mp.is_relative_to(REPO) else mp}")
    return 0


def cmd_estimate(a) -> int:
    measured = est.measure(Path(a.from_run)) if a.from_run else None
    print(est.render(est.plan(a.suites.split(","), a.configs.split(","), a.models.split(","), a.runs, a.step_limit,
                              measured=measured, parallel=a.parallel)))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="dovebench")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("subsets")
    s.add_argument("--check", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--suite", default="local", help="local, osworld, waa, macarena (comma-separated)")
    r.add_argument("--configs", default="", help="comma-separated ids (default: all)")
    r.add_argument("--model", default="scripted", help="scripted or anthropic:<model-id>[@effort], comma-separated")
    r.add_argument("--runs", type=int, default=3)
    r.add_argument("--step-limit", type=int, default=30)
    r.add_argument("--limit", type=int, default=None, help="first N tasks of the subset only")
    r.add_argument("--version", required=True)
    r.add_argument("--run-dir", default=None)
    r.add_argument("--out", default=None)
    r.add_argument("--note", action="append")
    r.add_argument("--no-screenshots", action="store_true", help="keep image sizes, not pixels, in trajectories")
    r.add_argument("--allow-paid", action="store_true")
    rp = sub.add_parser("report")
    rp.add_argument("--run-dir", required=True)
    rp.add_argument("--version", default=None)
    rp.add_argument("--out", default=None)
    e = sub.add_parser("estimate")
    e.add_argument("--suites", default="osworld,waa,macarena")
    e.add_argument("--configs", default="A,G,B,C,D")
    e.add_argument("--models", default="claude-opus-5-5,claude-haiku-5-5")
    e.add_argument("--runs", type=int, default=3)
    e.add_argument("--step-limit", type=int, default=30)
    e.add_argument("--parallel", default="osworld=8,waa=4,macarena=2")
    e.add_argument("--from-run", default=None, help="calibrate steps/tokens/time from a pilot run directory")
    a = p.parse_args(argv)
    if a.cmd == "subsets":
        return subsets.write(a.check)
    return {"run": cmd_run, "report": cmd_report, "estimate": cmd_estimate}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
