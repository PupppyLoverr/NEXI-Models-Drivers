"""Benchmark configurations (bench/configs/*.json).

A configuration is a driver command plus what the agent may use of it. The
model, prompt, step limit and agent loop are the same for all of them.

Fields:
  id, label                  short id (A, B, C, D, E, G) and a description
  command                    argv; "${VAR:-default}" is expanded, relative paths are from the repo root
  env                        extra environment for the driver process
  observation                "tree" | "screenshot" | "tree+marks"
  tools.allow / tools.deny   tool allowlist (null = all) and denylist
  deny_args                  {tool or "*": [argument names]}: refused, and removed from the schema the model sees
  force_args                 {tool: {arg: value}}: merged into every call of that tool
  requires_tools             the attempt fails fast when the driver lacks one
  requires_env               the configuration is skipped (reported as unavailable) when one is unset
"""

from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
REPO = BENCH.parent
_VAR = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


def _expand(s: str) -> str:
    return _VAR.sub(lambda m: os.environ.get(m.group(1)) or (m.group(2) or ""), s)


@dataclass
class Config:
    id: str
    label: str
    command: list[str]
    env: dict = field(default_factory=dict)
    observation: str = "tree"
    allow: list[str] | None = None
    deny: list[str] = field(default_factory=list)
    deny_args: dict = field(default_factory=dict)
    force_args: dict = field(default_factory=dict)
    requires_tools: list[str] = field(default_factory=list)
    requires_env: list[str] = field(default_factory=list)
    use_server_instructions: bool = True
    notes: str = ""

    @classmethod
    def load(cls, path: Path) -> "Config":
        d = json.loads(path.read_text())
        cmd = [_expand(a) for a in d["command"]]
        if cmd and not os.path.isabs(cmd[0]) and "/" in cmd[0]:
            cmd[0] = str(REPO / cmd[0])
        tools = d.get("tools", {})
        return cls(
            id=d["id"], label=d["label"], command=cmd,
            env={k: _expand(v) for k, v in d.get("env", {}).items()},
            observation=d.get("observation", "tree"),
            allow=tools.get("allow"), deny=tools.get("deny", []),
            deny_args=d.get("deny_args", {}), force_args=d.get("force_args", {}),
            requires_tools=d.get("requires_tools", []), requires_env=d.get("requires_env", []),
            use_server_instructions=d.get("use_server_instructions", True), notes=d.get("notes", ""),
        )

    def unavailable(self) -> str | None:
        missing = [v for v in self.requires_env if not os.environ.get(v)]
        if missing:
            return "unset: " + ", ".join(missing)
        if not self.command or not (os.path.exists(self.command[0]) or "/" not in self.command[0]):
            return f"driver not found: {self.command[0] if self.command else '(none)'}"
        return None

    def _denied(self, tool: str) -> set[str]:
        return set(self.deny_args.get("*", [])) | set(self.deny_args.get(tool, []))

    def filter_tools(self, tools: list[dict]) -> list[dict]:
        """The tool list the model sees: allow/deny applied, denied arguments removed from schemas."""
        out = []
        for t in tools:
            if self.allow is not None and t["name"] not in self.allow or t["name"] in self.deny:
                continue
            denied = self._denied(t["name"]) | set(self.force_args.get(t["name"], {}))
            if denied:
                t = copy.deepcopy(t)
                schema = t.get("inputSchema") or {}
                for a in denied:
                    (schema.get("properties") or {}).pop(a, None)
                if "required" in schema:
                    schema["required"] = [r for r in schema["required"] if r not in denied]
            out.append(t)
        return out

    def prepare_call(self, tool: str, args: dict) -> tuple[dict, str | None]:
        """(arguments to send, refusal message or None)."""
        bad = sorted(self._denied(tool) & set(args))
        if bad:
            return args, f"arguments {bad} are not available in configuration {self.id} ({self.observation})"
        if tool == "run_steps" and self.deny_args.get("*"):
            for step in args.get("steps", []):
                inner = step.get("args") or next((v for k, v in step.items() if isinstance(v, dict)), {})
                if set(self.deny_args["*"]) & set(inner):
                    return args, f"run_steps steps may not target elements in configuration {self.id}"
        forced = self.force_args.get(tool)
        return ({**args, **forced} if forced else args), None


def load_all(ids: list[str] | None = None) -> list[Config]:
    configs = {c.id: c for c in (Config.load(p) for p in sorted((BENCH / "configs").glob("*.json")))}
    if ids:
        unknown = [i for i in ids if i not in configs]
        if unknown:
            raise SystemExit(f"unknown configurations: {unknown}; known: {sorted(configs)}")
        return [configs[i] for i in ids]
    return list(configs.values())
