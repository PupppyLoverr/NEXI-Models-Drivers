from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .assets import digest
from .audio import read_wav
from .engine import Driver
from .metrics import word_error_rate


def worker(args: argparse.Namespace) -> dict[str, Any]:
    start = time.perf_counter()
    audio = read_wav(args.wav)
    driver = Driver(args.model, threads=args.threads)
    results = [
        driver.transcribe(
            audio, word_timestamps=args.words, vad=not args.no_vad, profile=args.profile
        )
        for _ in range(args.repeats)
    ]
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "load_seconds": driver.load_seconds,
        "results": results,
        "worker_seconds": time.perf_counter() - start,
        "peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
    }


def child(args: argparse.Namespace, repeats: int) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "nexi_stt.benchmark",
        "--worker",
        "--model",
        str(args.model),
        "--wav",
        str(args.wav),
        "--threads",
        str(args.threads),
        "--repeats",
        str(repeats),
        "--profile",
        args.profile,
    ]
    if args.words:
        command.append("--words")
    if args.no_vad:
        command.append("--no-vad")
    start = time.perf_counter()
    completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=600)
    result: dict[str, Any] = json.loads(completed.stdout)
    result["subprocess_wall_seconds"] = time.perf_counter() - start
    result["command"] = command
    return result


def hardware() -> dict[str, Any]:
    cpuinfo = Path("/proc/cpuinfo")
    cpu = platform.processor()
    if cpuinfo.is_file():
        cpu = next(
            (
                line.split(":", 1)[1].strip()
                for line in cpuinfo.read_text().splitlines()
                if line.startswith("model name")
            ),
            cpu,
        )
    return {
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "gpu": "none used; forced CPU",
    }


def measure(args: argparse.Namespace) -> dict[str, Any]:
    cold = [child(args, 1) for _ in range(args.runs)]
    warm = child(args, args.runs + 1)
    outputs = [entry["results"][0] for entry in cold] + warm["results"]
    references = args.reference.read_text() if args.reference else None
    for result in outputs:
        if references is not None:
            result["quality"] = word_error_rate(references, result["text"])
    return {
        "schema_version": 1,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "hardware": hardware(),
        "software": {
            name: importlib.metadata.version(name)
            for name in ("faster-whisper", "ctranslate2", "av", "onnxruntime", "numpy")
        },
        "python": platform.python_version(),
        "wav": {
            "name": args.wav.name,
            "bytes": args.wav.stat().st_size,
            "sha256": digest(args.wav),
        },
        "reference": references,
        "model_disk_bytes": sum(p.stat().st_size for p in args.model.rglob("*") if p.is_file()),
        "model_disk_definition": "logical model-directory bytes, including manifest",
        "cold_definition": "fresh interpreter/model each run; OS file cache NOT flushed",
        "warm_definition": "same model/process, after first transcription; first call excluded",
        "rss_definition": "kernel ru_maxrss of whole worker process, not model alone",
        "cold_runs": cold,
        "warm_process": warm,
        "summary": {
            "cold_process_wall_seconds_median": statistics.median(
                run["subprocess_wall_seconds"] for run in cold
            ),
            "cold_transcribe_seconds_median": statistics.median(
                run["results"][0]["transcribe_seconds"] for run in cold
            ),
            "warm_transcribe_seconds_median": statistics.median(
                row["transcribe_seconds"] for row in warm["results"][1:]
            ),
            "peak_rss_bytes": max(run["peak_rss_bytes"] for run in [*cold, warm]),
            "transcripts_identical": len({row["text"] for row in outputs}) == 1,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fresh CPU processes + warm calls; no download")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--wav", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--profile", choices=("fast", "balanced"), default="fast")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--words", action="store_true")
    parser.add_argument("--no-vad", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.runs < 1 or args.repeats < 1:
        parser.error("runs/repeats must be positive")
    output = worker(args) if args.worker else measure(args)
    rendered = json.dumps(output, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
