"""Minimal MCP stdio client (newline-delimited JSON-RPC 2.0).

Every configuration talks to its driver through this one client, so the only
thing that changes between configurations is the command it launches. A
driver inside a VM is reached the same way, e.g. `ssh vm dove-driver mcp`.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    pass


class McpClient:
    def __init__(self, command: list[str], env: dict[str, str] | None = None, stderr_path: Path | None = None,
                 timeout: float = 120.0):
        self.timeout = timeout
        self._stderr = open(stderr_path, "ab") if stderr_path else subprocess.DEVNULL
        self.proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._stderr,
            env={**os.environ, **(env or {})}, bufsize=0,
        )
        self._next_id = 0
        self._lines: queue.Queue[bytes | None] = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.server_info: dict = {}
        self.instructions: str = ""
        self.tools: list[dict] = []
        self.tools_list_bytes = 0

    def _read(self) -> None:
        assert self.proc.stdout
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _send(self, msg: dict) -> None:
        assert self.proc.stdin
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        self.proc.stdin.flush()

    def request(self, method: str, params: dict | None = None) -> tuple[dict, bytes]:
        self._next_id += 1
        rid = self._next_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        deadline = time.monotonic() + self.timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise McpError(f"{method}: no reply in {self.timeout:.0f}s")
            try:
                line = self._lines.get(timeout=left)
            except queue.Empty:
                continue
            if line is None:
                raise McpError(f"{method}: driver exited (code {self.proc.poll()})")
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # a driver that logs to stdout; ignore the line
            if msg.get("id") == rid and ("result" in msg or "error" in msg):
                if "error" in msg:
                    raise McpError(f"{method}: {msg['error'].get('message', msg['error'])}")
                return msg["result"], line
            if "method" in msg and "id" in msg:  # server-to-client request (roots, sampling): decline
                self._send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "not supported"}})

    def initialize(self) -> None:
        result, _ = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "dove-bench", "version": "1"},
        })
        self.server_info = result.get("serverInfo", {})
        self.instructions = result.get("instructions", "") or ""
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools, cursor, size = [], None, 0
        while True:
            res, raw = self.request("tools/list", {"cursor": cursor} if cursor else {})
            size += len(raw)
            tools += res.get("tools", [])
            cursor = res.get("nextCursor")
            if not cursor:
                break
        self.tools, self.tools_list_bytes = tools, size

    def call(self, name: str, arguments: dict) -> tuple[dict, float, int]:
        """(result, latency seconds, raw reply bytes). A tool error is a result with isError, not an exception."""
        t0 = time.perf_counter()
        result, raw = self.request("tools/call", {"name": name, "arguments": arguments})
        return result, time.perf_counter() - t0, len(raw)

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
        if self._stderr is not subprocess.DEVNULL:
            self._stderr.close()

    def __enter__(self) -> "McpClient":
        self.initialize()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
