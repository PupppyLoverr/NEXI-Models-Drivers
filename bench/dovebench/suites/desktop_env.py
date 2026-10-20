"""OSWorld-Verified, Windows Agent Arena and MacArena through their own DesktopEnv.

All three ship an OSWorld-style `desktop_env.desktop_env.DesktopEnv`: reset()
reverts the VM to its snapshot and runs the task's setup through the in-VM
server, evaluate() runs the task's checker. The harness uses exactly those two
calls (the cua-bench BenchAdapter split) and never the suite's own step() or
agents. Every agent action goes through the driver under test, which runs
inside the VM and is reached over MCP stdio through SSH.

Environment (per suite prefix OSWORLD / WAA / MACARENA):
  DOVE_BENCH_<S>_DIR         checkout of the suite repo at the commit in bench/SOURCES.md
  DOVE_BENCH_<S>_ENV         JSON kwargs for DesktopEnv (provider_name, path_to_vm, os_type, snapshot_name, ...)
  DOVE_BENCH_<S>_SSH         ssh prefix to reach the VM, "{ip}" is replaced by the VM's address,
                             e.g. "ssh -T -o StrictHostKeyChecking=no user@{ip}"
  DOVE_BENCH_<S>_DRIVER_<ID> driver path inside the VM for configuration <ID> (falls back to the local command)

Not run in this repository's CI: these need the suites' VM images, which are
tens of GB. bench/README.md says how to set them up.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import time
from pathlib import Path

from .. import subsets
from .base import Suite, Task

# (env prefix, task file layout, client dir on sys.path, DesktopEnv module, default DesktopEnv kwargs)
LAYOUT = {
    "osworld": ("OSWORLD", "evaluation_examples/examples/{domain}/{id}.json", "", "desktop_env.desktop_env",
                {"os_type": "Ubuntu", "action_space": "pyautogui", "require_a11y_tree": False}),
    "waa": ("WAA", "src/win-arena-container/client/evaluation_examples_windows/examples/{domain}/{id}.json",
            "src/win-arena-container/client", "desktop_env.envs.desktop_env",
            {"action_space": "pyautogui", "require_a11y_tree": False}),
    "macarena": ("MACARENA", "evaluation_examples/{domain}/{id}.json", "", "desktop_env.desktop_env",
                 {"os_type": "macOS", "provider_name": "utm", "action_space": "pyautogui", "require_a11y_tree": False}),
}


class DesktopEnvSuite(Suite):
    def __init__(self, name: str):
        self.name = name
        self.prefix, self.layout, self.client_dir, self.module, self.defaults = LAYOUT[name]
        root = os.environ.get(f"DOVE_BENCH_{self.prefix}_DIR")
        if not root:
            raise SystemExit(f"set DOVE_BENCH_{self.prefix}_DIR to a {name} checkout (see bench/SOURCES.md)")
        self.root = Path(root)
        self.env_kwargs = json.loads(os.environ.get(f"DOVE_BENCH_{self.prefix}_ENV", "{}"))
        self.ssh = os.environ.get(f"DOVE_BENCH_{self.prefix}_SSH", "")
        self._env = None

    def _desktop_env(self):
        if self._env is None:
            import importlib

            sys.path.insert(0, str(self.root / self.client_dir))
            DesktopEnv = importlib.import_module(self.module).DesktopEnv  # the suite's own code
            self._env = DesktopEnv(**{**self.defaults, **self.env_kwargs})
        return self._env

    def tasks(self, limit=None):
        out = []
        for domain, tid in subsets.load(self.name):
            path = self.root / self.layout.format(domain=domain, id=tid)
            spec = json.loads(path.read_text())
            out.append(Task(tid, domain, spec["instruction"], {"config": spec}))
        return out[:limit] if limit else out

    def environment(self):
        kw = {**self.defaults, **self.env_kwargs}
        info = {"suite_dir": str(self.root), "provider": kw.get("provider_name", "docker" if self.name == "waa" else ""),
                "vm": kw.get("path_to_vm") or kw.get("emulator_ip", ""), "snapshot": kw.get("snapshot_name", "init_state")}
        try:
            import subprocess

            info["suite_commit"] = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"],
                                                  capture_output=True, text=True).stdout.strip()
        except Exception:
            pass
        return info

    def reset(self, task, config):
        env = self._desktop_env()
        env.reset(task_config=task.meta["config"])
        time.sleep(10)  # the suites' own runners wait this long after setup

    def driver_command(self, config):
        """Run the driver inside the VM: ssh prefix + the VM-side driver path, its env on the remote side."""
        if not self.ssh:
            return config.command, config.env
        ip = getattr(self._env, "vm_ip", "")
        remote = os.environ.get(f"DOVE_BENCH_{self.prefix}_DRIVER_{config.id}") or config.command[0]
        env = " ".join(f"{k}={shlex.quote(v)}" for k, v in config.env.items())
        line = f"{env} {shlex.quote(remote)} {' '.join(map(shlex.quote, config.command[1:]))}".strip()
        return shlex.split(self.ssh.replace("{ip}", ip)) + [line], {}

    def evaluate(self, task, final_answer):
        env = self._env
        if final_answer.strip().upper().startswith("INFEASIBLE"):
            env.action_history.append("FAIL")  # how OSWorld-style checkers read an infeasible verdict
        return float(env.evaluate())

    def cleanup(self, task):
        pass


def make(name: str) -> DesktopEnvSuite:
    return DesktopEnvSuite(name)
