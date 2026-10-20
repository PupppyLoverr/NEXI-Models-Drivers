"""Local smoke suite: GTK3 task windows on the current X display (Xvfb + AT-SPI).

Each attempt starts a fresh app process (the local stand-in for a fresh VM
snapshot) and checks the app's state file. It exists to prove the harness end
to end on Linux, not to rank drivers.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .base import Suite, Task

TASKS = Path(__file__).resolve().parents[2] / "tasks" / "local"


def gtk_python() -> str:
    """A Python that can import PyGObject (the distro's, which may not be the harness's)."""
    want = os.environ.get("DOVE_BENCH_GTK_PYTHON")
    if want:
        return want
    for cand in ("python3", "python3.12", "python3.11", "/usr/bin/python3"):
        exe = shutil.which(cand)
        if exe and subprocess.run([exe, "-c", "import gi"], capture_output=True).returncode == 0:
            return exe
    raise RuntimeError("no Python with PyGObject (install python3-gi) or set DOVE_BENCH_GTK_PYTHON")


class LocalSuite(Suite):
    name = "local"

    def __init__(self):
        self._spec = json.loads((TASKS / "tasks.json").read_text())["tasks"]
        self._proc: subprocess.Popen | None = None
        self._dir: Path | None = None
        self._python = None

    def tasks(self, limit=None):
        out = [Task(t["id"], t["domain"], t["instruction"], t) for t in self._spec]
        return out[:limit] if limit else out

    def environment(self):
        return {"os": platform.platform(), "display": os.environ.get("DISPLAY", ""), "toolkit": "GTK3 via AT-SPI"}

    def reset(self, task, config):
        if not os.environ.get("DISPLAY"):
            raise RuntimeError("no DISPLAY: run bench/scripts/linux-session.sh first")
        self._python = self._python or gtk_python()
        self._dir = Path(tempfile.mkdtemp(prefix=f"dove-bench-{task.id}-"))
        state, oracle = self._dir / "state.json", self._dir / "oracle.json"
        self._proc = subprocess.Popen(
            [self._python, str(TASKS / "app.py"), task.meta["form"], str(state), str(oracle)],
            env={**os.environ, "GTK_MODULES": "gail:atk-bridge", "NO_AT_BRIDGE": "0"},
            stdout=subprocess.DEVNULL, stderr=open(self._dir / "app.log", "w"),
        )
        task.meta["pid"] = self._proc.pid
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if oracle.exists() and state.exists():
                time.sleep(0.3)  # let the accessibility bridge register the window
                return
            if self._proc.poll() is not None:
                raise RuntimeError(f"task app exited: {(self._dir / 'app.log').read_text()[-400:]}")
            time.sleep(0.05)
        raise RuntimeError("task app did not start in 10 s")

    def oracle(self, task):
        try:
            return json.loads((self._dir / "oracle.json").read_text())
        except Exception:
            return {}

    def evaluate(self, task, final_answer):
        time.sleep(0.2)  # the last click's handler may still be writing
        try:
            state = json.loads((self._dir / "state.json").read_text())
        except Exception:
            return False
        return all(state.get(k) == v for k, v in task.meta["check"].items())

    def cleanup(self, task):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._dir:
            shutil.rmtree(self._dir, ignore_errors=True)
        self._proc = self._dir = None
