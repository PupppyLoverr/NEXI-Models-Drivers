"""Measure a subprocess: wall time, peak RSS of the whole process tree.

Usage: python -m common.bench.measure --json out.json -- <command> [args...]
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import psutil


def tree_rss_mb(proc: psutil.Process) -> float:
    total = 0
    try:
        procs = [proc] + proc.children(recursive=True)
    except psutil.Error:
        return 0.0
    for p in procs:
        try:
            total += p.memory_info().rss
        except psutil.Error:
            pass
    return total / (1024 * 1024)


def measure(argv: list[str], json_out: str | None = None, sample_ms: int = 50) -> dict:
    t0 = time.monotonic()
    proc = subprocess.Popen(argv)
    p = psutil.Process(proc.pid)
    peak = 0.0
    while proc.poll() is None:
        peak = max(peak, tree_rss_mb(p))
        time.sleep(sample_ms / 1000)
    peak = max(peak, tree_rss_mb(p))
    wall = time.monotonic() - t0
    result = {
        "command": argv,
        "wall_seconds": round(wall, 3),
        "peak_rss_mb": round(peak, 1),
        "exit_code": proc.returncode,
    }
    if json_out:
        Path(json_out).write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    args = sys.argv[1:]
    json_out = None
    if args[:2] == ["--json", args[1] if len(args) > 1 else ""]:
        json_out = args[1]
        args = args[2:]
    if args and args[0] == "--":
        args = args[1:]
    if not args:
        print(__doc__)
        return 2
    result = measure(args, json_out)
    print(json.dumps(result))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
