#!/usr/bin/env python3
"""R0.2: dove-driver and a stock cua-driver run side by side with separate state.

    python3 ci/dove/side_by_side.py --dove <dove-driver> --stock <cua-driver> [--work DIR]

Every phase runs both drivers' real CLIs under a fresh, isolated home
(HOME, USERPROFILE, LOCALAPPDATA, APPDATA and the XDG directories all point
into --work), so nothing touches the caller's own state.

  dove-only   dove-driver alone: its --version, MCP serverInfo, default daemon
              endpoint and state paths say dove-driver, and it creates nothing
              named cua-driver.
  stock-only  the same for stock cua-driver, which must create nothing named
              dove-driver.
  together    both daemons on their default endpoints at once: different
              endpoints and pids, each MCP proxy reaches its own daemon, and
              stopping one leaves the other running.
  alias       DOVE_DRIVER_HOME moves dove-driver's home (patch 0001's
              DOVE_DRIVER_* -> CUA_DRIVER_* aliases).

On Windows the daemon endpoints are named pipes, which are per logon session
rather than per home. The script refuses to start if either default pipe is
already in use, and never stops a daemon it did not start.

Python standard library only. Exit status 0 when every check passes.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
TIMEOUT = 30

failures: list[str] = []


def check(ok: bool, message: str) -> bool:
    print(("  ok   " if ok else "  FAIL ") + message, flush=True)
    if not ok:
        failures.append(message)
    return ok


def isolated_env(home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CUA_DRIVER", "DOVE_DRIVER"))
    }
    dirs = {
        "HOME": home,
        "USERPROFILE": home,
        "LOCALAPPDATA": home / "AppData" / "Local",
        "APPDATA": home / "AppData" / "Roaming",
        "XDG_CONFIG_HOME": home / ".config",
        "XDG_CACHE_HOME": home / ".cache",
        "XDG_DATA_HOME": home / ".local" / "share",
        "XDG_STATE_HOME": home / ".local" / "state",
    }
    for name, path in dirs.items():
        path.mkdir(parents=True, exist_ok=True)
        env[name] = str(path)
    # Stock cua-driver sends telemetry by default; never from CI.
    env.update(
        {
            "CUA_DRIVER_RS_TELEMETRY_ENABLED": "false",
            "CUA_TELEMETRY": "0",
            "DO_NOT_TRACK": "1",
        }
    )
    env.update(extra or {})
    return env


def run(binary: str, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [binary, *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        stdin=subprocess.DEVNULL,
    )


def expected_socket(name: str, home: Path) -> str:
    if WINDOWS:
        return rf"\\.\pipe\{name}"
    if MACOS:
        return str(home / "Library" / "Caches" / name / f"{name}.sock")
    return str(home / ".cache" / name / f"{name}.sock")


def parse_status(text: str) -> dict[str, str]:
    fields = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition(":")
        if sep and key in ("socket", "pid", "permission mode"):
            fields[key] = value.strip()
    return fields


class Daemon:
    """A `serve` process this script started, on its default endpoint."""

    def __init__(self, name: str, binary: str, env: dict[str, str], log_dir: Path):
        self.name, self.binary, self.env = name, binary, env
        self.log = open(log_dir / f"{name}-serve.log", "w")
        self.proc = subprocess.Popen(
            [binary, "serve", "--no-permissions-gate"],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )
        self.status: dict[str, str] = {}

    def wait_ready(self) -> bool:
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                return False
            result = run(self.binary, ["status"], self.env)
            if result.returncode == 0 and "pid:" in result.stdout:
                self.status = parse_status(result.stdout)
                return True
            time.sleep(0.5)
        return False

    def running(self) -> bool:
        result = run(self.binary, ["status"], self.env)
        return result.returncode == 0 and parse_status(result.stdout).get("pid") == self.status.get("pid")

    def stop(self) -> None:
        if self.proc.poll() is None:
            run(self.binary, ["stop"], self.env)
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.log.close()


def mcp_server_name(binary: str, socket: str, env: dict[str, str]) -> str | None:
    """Initialize an MCP stdio proxy against `socket` and return serverInfo.name."""
    proc = subprocess.Popen(
        [binary, "mcp", "--socket", socket],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "dove-ci-side-by-side", "version": "1"},
            },
        }
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                return None
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == 1:
                return message.get("result", {}).get("serverInfo", {}).get("name")
        return None
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def paths_containing(root: Path, needle: str) -> list[str]:
    hits = []
    for path in root.rglob("*"):
        if needle in path.name.lower():
            hits.append(str(path.relative_to(root)))
    return sorted(hits)


def endpoint_free(binary: str, env: dict[str, str]) -> bool:
    return run(binary, ["status"], env).returncode != 0


def solo_phase(label: str, name: str, other: str, binary: str, work: Path) -> None:
    print(f"[{label}] {name} alone", flush=True)
    home = work / label
    env = isolated_env(home)

    version = run(binary, ["--version"], env)
    check(
        version.returncode == 0 and version.stdout.split()[:1] == [name],
        f"{name} --version names {name}: {version.stdout.strip()!r}",
    )

    if not check(endpoint_free(binary, env), f"default {name} endpoint is free before the test"):
        return
    daemon = Daemon(name, binary, env, work)
    try:
        if not check(daemon.wait_ready(), f"{name} serve answers status on its default endpoint"):
            return
        socket = daemon.status.get("socket", "")
        check(
            socket == expected_socket(name, home),
            f"{name} default endpoint is {expected_socket(name, home)} (got {socket})",
        )
        check(
            mcp_server_name(binary, socket, env) == name,
            f"{name} MCP serverInfo.name is {name}",
        )
    finally:
        daemon.stop()

    check(
        endpoint_free(binary, env),
        f"{name} stop shut its daemon down",
    )
    own = paths_containing(home, name)
    check(bool(own), f"{name} kept its state under its own name ({', '.join(own[:4]) or 'nothing found'})")
    leaked = paths_containing(home, other)
    check(not leaked, f"{name} created nothing named {other} ({', '.join(leaked[:6]) or 'none'})")


def together_phase(dove: str, stock: str, work: Path) -> None:
    print("[together] dove-driver and cua-driver side by side", flush=True)
    home = work / "together"
    env = isolated_env(home)
    if not (
        check(endpoint_free(dove, env), "default dove-driver endpoint is free before the test")
        and check(endpoint_free(stock, env), "default cua-driver endpoint is free before the test")
    ):
        return

    daemons = {
        "dove-driver": Daemon("dove-driver-together", dove, env, work),
        "cua-driver": Daemon("cua-driver-together", stock, env, work),
    }
    try:
        ready = all(
            check(d.wait_ready(), f"{name} daemon ready while the other runs")
            for name, d in daemons.items()
        )
        if not ready:
            return
        d, s = daemons["dove-driver"], daemons["cua-driver"]
        check(
            d.status.get("socket") != s.status.get("socket"),
            f"different endpoints: {d.status.get('socket')} vs {s.status.get('socket')}",
        )
        check(
            d.status.get("pid") != s.status.get("pid"),
            f"different daemon pids: {d.status.get('pid')} vs {s.status.get('pid')}",
        )
        check(
            mcp_server_name(dove, d.status["socket"], env) == "dove-driver",
            "dove-driver MCP proxy reaches the dove-driver daemon",
        )
        check(
            mcp_server_name(stock, s.status["socket"], env) == "cua-driver",
            "cua-driver MCP proxy reaches the cua-driver daemon",
        )
        d.stop()
        check(endpoint_free(dove, env), "dove-driver stopped")
        check(s.running(), "cua-driver daemon still running after dove-driver stopped")
    finally:
        for daemon in daemons.values():
            daemon.stop()
    check(endpoint_free(stock, env), "cua-driver stopped")
    for name in ("dove-driver", "cua-driver"):
        check(bool(paths_containing(home, name)), f"{name} state present in the shared home")


def alias_phase(dove: str, work: Path) -> None:
    print("[alias] DOVE_DRIVER_HOME", flush=True)
    home = work / "alias"
    custom = work / "alias-dove-home"
    result = run(dove, ["skills", "path"], isolated_env(home, {"DOVE_DRIVER_HOME": str(custom)}))
    reported = result.stdout.strip().splitlines()[-1:] or [""]
    check(
        result.returncode == 0 and Path(reported[0]).is_relative_to(custom),
        f"dove-driver skills path follows DOVE_DRIVER_HOME ({reported[0]!r} under {custom})",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dove", required=True, help="path to the dove-driver binary")
    parser.add_argument("--stock", required=True, help="path to a stock cua-driver binary")
    parser.add_argument("--work", help="scratch directory (default: a new temporary one)")
    args = parser.parse_args()

    for binary in (args.dove, args.stock):
        if shutil.which(binary) is None and not Path(binary).is_file():
            print(f"binary not found: {binary}", file=sys.stderr)
            return 2
    work = Path(args.work or tempfile.mkdtemp(prefix="dove-side-by-side-")).resolve()
    work.mkdir(parents=True, exist_ok=True)
    print(f"work directory: {work}")
    # Unix sockets: sun_path holds 108 bytes on Linux, 104 on macOS.
    longest = expected_socket("dove-driver", work / "stock-only")
    if not WINDOWS and len(longest.encode()) >= (104 if MACOS else 108):
        print(f"--work is too deep for a Unix socket path ({longest}); use a shorter one", file=sys.stderr)
        return 2

    solo_phase("dove-only", "dove-driver", "cua-driver", args.dove, work)
    solo_phase("stock-only", "cua-driver", "dove-driver", args.stock, work)
    together_phase(args.dove, args.stock, work)
    alias_phase(args.dove, work)

    if failures:
        print(f"\n{len(failures)} check(s) failed:")
        for message in failures:
            print(f"  - {message}")
        return 1
    print("\nside-by-side: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
