#!/usr/bin/env python3
"""Measure a fresh local inference process with GNU time; no ML dependencies."""

import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any


def asset_bytes(paths: list[Path]) -> int:
    seen = set()
    total = 0
    for path in paths:
        if not path.exists():
            raise ValueError(f"Asset path does not exist: {path}")
        candidates = path.rglob("*") if path.is_dir() else [path]
        for candidate in candidates:
            if not candidate.is_file():
                continue
            stat = candidate.stat()
            identity = (stat.st_dev, stat.st_ino)
            if identity not in seen:
                seen.add(identity)
                total += stat.st_size
    return total


def cpu_name() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        match = re.search(r"^model name\s*:\s*(.+)$", cpuinfo.read_text(), re.M)
        if match:
            return match[1]
    return platform.processor() or "unknown"


def measure(command: list[str], time_binary: str, assets: list[Path], label: str) -> dict[str, Any]:
    size = asset_bytes(assets) if assets else None
    with tempfile.TemporaryDirectory(prefix="nexi-bench-") as temporary:
        rss_log = Path(temporary) / "rss.txt"
        started = time.perf_counter()
        completed = subprocess.run(
            [time_binary, "--format=%M", "--output", str(rss_log), "--", *command],
            check=False,
        )
        elapsed = time.perf_counter() - started
        lines = rss_log.read_text().splitlines()
        if not lines or not lines[-1].isdigit():
            raise ValueError("GNU time did not report maximum RSS; use GNU time, not BSD time")
        rss = int(lines[-1]) * 1024
    return {
        "schema_version": 1,
        "label": label,
        "measured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "passed" if completed.returncode == 0 else "failed",
        "exit_code": completed.returncode,
        "command": command,
        "cwd": os.getcwd(),
        "wall_seconds": elapsed,
        "peak_rss_bytes": rss,
        "asset_files_bytes": size,
        "asset_paths": [str(path) for path in assets],
        "hardware": {
            "cpu": cpu_name(),
            "logical_cpus": os.cpu_count(),
            "platform": platform.platform(),
            "architecture": platform.machine(),
        },
        "thread_environment": {
            name: os.environ[name]
            for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")
            if name in os.environ
        },
        "measurement": "GNU time maximum process RSS; not summed concurrent-worker RAM or VRAM",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--label", default="local-inference")
    parser.add_argument("--asset-path", action="append", default=[], type=Path)
    parser.add_argument("--time-binary", default="/usr/bin/time")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("Provide an inference command after --")
    binary = shutil.which(args.time_binary)
    if binary is None:
        parser.error("GNU time is required (Linux: time package; macOS: gtime)")
    if not args.output.parent.is_dir():
        parser.error("Output parent directory must already exist")
    try:
        result = measure(command, binary, args.asset_path, args.label)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{result['status']}: {result['wall_seconds']:.3f}s, "
          f"{result['peak_rss_bytes'] / 1_000_000:.1f} MB peak RSS → {args.output}")
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
