"""Fresh-process CPU measurement with Python networking disabled in each worker."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import socket
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .assets import FILES, MODEL_FILE, REPOSITORY, REVISION, default_model_dir

TEXT = (
    "Hello. I am your local voice assistant. Everything you hear is generated on this device, "
    "without sending your text to the cloud."
)
LONG_TEXT = " ".join([TEXT] * 8)


def peak_rss_bytes() -> int:
    import resource

    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def deny_network(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("Benchmark worker prohibits Python networking")


def worker(args: argparse.Namespace) -> dict[str, Any]:
    socket.socket = deny_network  # type: ignore[misc,assignment]
    socket.create_connection = deny_network
    start = time.perf_counter()
    from .driver import SAMPLE_RATE, Synthesizer, pcm16

    imported = time.perf_counter()
    synth = Synthesizer(args.model_dir, args.threads)
    loaded = time.perf_counter()
    import wave

    import numpy as np

    measurements: list[dict[str, Any]] = []
    for index in range(args.warm_runs + 1):
        phase = "cold_model_first_request" if index == 0 else "warm_model_request"
        text = LONG_TEXT if args.long else TEXT
        samples = 0
        sum_squares = 0.0
        max_amplitude = 0.0
        clipped = 0
        wav_path = args.output_dir / f"run-{args.run_id}-{index}.wav"
        inference_start = time.perf_counter()
        with wave.open(str(wav_path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(SAMPLE_RATE)
            first_chunk_seconds = 0.0
            for audio in synth.iter_audio(text, voice=args.voice):
                if samples == 0:
                    first_chunk_seconds = time.perf_counter() - inference_start
                samples += len(audio)
                sum_squares += float(np.dot(audio, audio))
                max_amplitude = max(max_amplitude, float(np.max(np.abs(audio))))
                clipped += int(np.count_nonzero(np.abs(audio) > 1))
                out.writeframes(pcm16(audio))
        synthesis_seconds = time.perf_counter() - inference_start
        audio_seconds = samples / SAMPLE_RATE
        measurements.append(
            {
                "phase": phase,
                "text": text,
                "text_chars": len(text),
                "audio_seconds": audio_seconds,
                "synthesis_and_wav_seconds": synthesis_seconds,
                "first_chunk_seconds": first_chunk_seconds,
                "real_time_factor": synthesis_seconds / audio_seconds,
                "process_peak_rss_bytes_so_far": peak_rss_bytes(),
                "waveform_rms": (sum_squares / samples) ** 0.5,
                "waveform_peak": max_amplitude,
                "clipped_samples": clipped,
                "wav_file": wav_path.name,
                "wav_bytes": wav_path.stat().st_size,
                "wav_sha256": hashlib.sha256(wav_path.read_bytes()).hexdigest(),
            }
        )
    return {
        "import_seconds": imported - start,
        "load_verify_and_frontend_seconds": loaded - imported,
        "cold_import_load_to_first_audio_seconds": loaded
        - start
        + measurements[0]["first_chunk_seconds"],
        "process_peak_rss_bytes": peak_rss_bytes(),
        "python_network_guard": True,
        "measurements": measurements,
    }


def hardware() -> dict[str, Any]:
    info: dict[str, Any] = {
        "platform": platform.platform(),
        "python": sys.version,
        "logical_cpus": os.cpu_count(),
        "gpu_used": False,
    }
    if Path("/proc/cpuinfo").exists():
        info["cpu_model"] = next(
            line.split(":", 1)[1].strip()
            for line in Path("/proc/cpuinfo").read_text().splitlines()
            if line.startswith("model name")
        )
        info["mem_total_bytes"] = (
            int(Path("/proc/meminfo").read_text().splitlines()[0].split()[1]) * 1024
        )
    return info


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=default_model_dir())
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    parser.add_argument("--processes", type=int, default=3)
    parser.add_argument("--warm-runs", type=int, default=2)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--voice", default="Jasper")
    parser.add_argument("--long", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--run-id", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.platform not in ("linux", "darwin"):
        parser.error("Peak RSS benchmark requires POSIX resource; Windows is unverified")
    if not 1 <= args.processes <= 10 or not 0 <= args.warm_runs <= 20:
        parser.error("Use 1-10 processes and 0-20 warm runs")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.worker:
        print(json.dumps(worker(args)))
        return
    runs: list[dict[str, Any]] = []
    for index in range(args.processes):
        command = [
            sys.executable,
            "-m",
            "nexi_tts.benchmark",
            "--worker",
            "--run-id",
            str(index),
            "--model-dir",
            str(args.model_dir.resolve()),
            "--output-dir",
            str(args.output_dir.resolve()),
            "--threads",
            str(args.threads),
            "--warm-runs",
            str(args.warm_runs),
            "--voice",
            args.voice,
        ]
        if args.long:
            command.append("--long")
        env = {
            **os.environ,
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": str(args.threads),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
        started = time.perf_counter()
        process = subprocess.run(
            command, env=env, check=True, capture_output=True, text=True, timeout=600
        )
        result = json.loads(process.stdout)
        result["fresh_subprocess_wall_seconds"] = time.perf_counter() - started
        runs.append(result)
    warm = [m for r in runs for m in r["measurements"] if m["phase"] == "warm_model_request"]
    cold = [r["measurements"][0] for r in runs]
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "hardware": hardware(),
        "configuration": {
            "repository": REPOSITORY,
            "revision": REVISION,
            "provider": "CPUExecutionProvider",
            "onnx_intra_threads": args.threads,
            "onnx_inter_threads": 1,
            "execution": "sequential",
            "cpu_memory_arena": False,
            "memory_pattern": False,
            "voice": args.voice,
            "speed": 1.0,
            "language": "en",
            "sample_rate": 24000,
            "chunk_chars": 180,
            "openblas_threads": 1,
            "cold_definition": "new interpreter, new model session; OS file cache NOT flushed",
            "warm_definition": "same process and model session, sequential subsequent requests",
            "memory_definition": "process ru_maxrss, including Python/native runtime/phonemizer, not total machine RAM",
        },
        "packages": {
            p: importlib.metadata.version(p)
            for p in ("numpy", "onnxruntime", "phonemizer", "espeakng-loader", "num2words")
        },
        "disk": {
            "model_onnx_bytes": (args.model_dir / MODEL_FILE).stat().st_size,
            "assets_total_bytes": sum((args.model_dir / f).stat().st_size for f in FILES),
            "files": {f: {"bytes": s, "sha256": h} for f, (s, h) in FILES.items()},
        },
        "summary": {
            "max_process_peak_rss_bytes": max(r["process_peak_rss_bytes"] for r in runs),
            "median_cold_synthesis_seconds": statistics.median(
                m["synthesis_and_wav_seconds"] for m in cold
            ),
            "median_cold_load_seconds": statistics.median(
                r["load_verify_and_frontend_seconds"] for r in runs
            ),
            "median_cold_import_load_first_audio_seconds": statistics.median(
                r["cold_import_load_to_first_audio_seconds"] for r in runs
            ),
            "median_cold_rtf": statistics.median(m["real_time_factor"] for m in cold),
            "median_warm_synthesis_seconds": statistics.median(
                m["synthesis_and_wav_seconds"] for m in warm
            )
            if warm
            else None,
            "median_warm_first_chunk_seconds": statistics.median(
                m["first_chunk_seconds"] for m in warm
            )
            if warm
            else None,
            "median_warm_rtf": statistics.median(m["real_time_factor"] for m in warm)
            if warm
            else None,
        },
        "runs": runs,
    }
    output = args.output_dir / "benchmark.json"
    output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"evidence": str(output), **evidence["summary"]}))


if __name__ == "__main__":
    main()
