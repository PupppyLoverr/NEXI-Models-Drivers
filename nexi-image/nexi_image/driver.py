"""Lightweight parent process; each tensor component lives in a fresh worker."""

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

from .assets import digest, download, entries, verify

OFFLINE = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
           "HF_DATASETS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"}


def validate(prompt: str, width: int, height: int, steps: int, threads: int,
             seed: int, dtype: str, guidance: float) -> None:
    if not prompt.strip() or len(prompt) > 4000:
        raise ValueError("prompt must contain 1–4000 characters")
    if any(n < 128 or n > 512 or n % 64 for n in (width, height)):
        raise ValueError("dimensions must be multiples of 64 between 128 and 512")
    if not 1 <= steps <= 50 or not 1 <= threads <= 64:
        raise ValueError("steps must be 1–50 and threads 1–64")
    if not 0 <= seed < 2**63 or dtype not in ("float32", "bfloat16", "float16"):
        raise ValueError("invalid seed or dtype")
    if not 1 <= guidance <= 20:
        raise ValueError("guidance must be between 1 and 20")


def run_worker(stage: str, config: dict, workspace: Path) -> dict:
    config_path = workspace / "config.json"
    config_path.write_text(json.dumps(config))
    env = {**os.environ, **OFFLINE, "OMP_NUM_THREADS": str(config["threads"]),
           "MKL_NUM_THREADS": str(config["threads"])}
    subprocess.run([sys.executable, "-m", "nexi_image.worker", stage,
                    str(config_path), str(workspace)], check=True, env=env)
    return json.loads((workspace / f"{stage}.json").read_text())


def generate(prompt: str, output: str | Path, models: str | Path = "models",
             width: int = 256, height: int = 256, steps: int = 10,
             seed: int = 42, threads: int = 4, dtype: str = "bfloat16",
             guidance: float = 7.5, negative: str = "blurry, low quality",
             adapter: str | None = None, cache_state: str = "unspecified") -> dict:
    """Generate locally, returning provenance. No network access is performed."""
    validate(prompt, width, height, steps, threads, seed, dtype, guidance)
    root = Path(models).resolve()
    output = Path(output).resolve()
    if output.suffix.lower() != ".png":
        raise ValueError("output must use a .png suffix")
    started = time.perf_counter()
    model_bytes = verify(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    config = dict(prompt=prompt, negative=negative, output=str(output), models=str(root),
                  width=width, height=height, steps=steps, seed=seed, threads=threads,
                  dtype=dtype, guidance=guidance,
                  adapter=str(Path(adapter).resolve()) if adapter else None)
    with tempfile.TemporaryDirectory(prefix="nexi-image-") as tmp:
        workspace = Path(tmp)
        metrics = [run_worker(stage, config, workspace) for stage in ("encode", "denoise", "decode")]
    report = {"schema": 1, "model": "nota-ai/bk-sdm-tiny", "decoder": "madebyollin/taesd",
              "config": config, "cache_state": cache_state,
              "hardware": {"platform": platform.platform(), "machine": platform.machine(),
                           "logical_cpus": os.cpu_count()},
              "model_files": entries(), "model_disk_bytes": model_bytes,
              "total_wall_seconds": time.perf_counter() - started, "stages": metrics,
              "max_worker_peak_rss_bytes": max(m["peak_rss_bytes"] for m in metrics),
              "output_sha256": digest(output), "output_bytes": output.stat().st_size,
              "adapter_sha256": digest(Path(adapter)) if adapter else None}
    output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Local BK-SDM-Tiny text-to-image")
    sub = parser.add_subparsers(dest="command", required=True)
    dl = sub.add_parser("download", help="The only command that accesses the network")
    dl.add_argument("--models", default="models")
    dl.add_argument("--training", action="store_true", help="Also download the original VAE")
    check = sub.add_parser("verify")
    check.add_argument("--models", default="models")
    check.add_argument("--training", action="store_true")
    gen = sub.add_parser("generate")
    gen.add_argument("--prompt", required=True)
    gen.add_argument("--output", default="outputs/image.png")
    gen.add_argument("--models", default="models")
    for name, default in (("width", 256), ("height", 256), ("steps", 10), ("threads", 4), ("seed", 42)):
        gen.add_argument(f"--{name}", type=int, default=default)
    gen.add_argument("--dtype", choices=["float32", "bfloat16", "float16"], default="bfloat16")
    gen.add_argument("--guidance", type=float, default=7.5)
    gen.add_argument("--negative", default="blurry, low quality")
    gen.add_argument("--adapter")
    gen.add_argument("--cache-state", default="unspecified")
    args = vars(parser.parse_args())
    command = args.pop("command")
    try:
        result = generate(**args) if command == "generate" else (
            download(Path(args["models"]), args["training"]) if command == "download"
            else verify(Path(args["models"]), args["training"]))
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
