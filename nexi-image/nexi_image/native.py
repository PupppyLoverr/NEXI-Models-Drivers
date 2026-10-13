"""SD1.5 Q4 + LCM + TAESD native CPU profile with disk-backed parameters."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from .assets import digest, download, entries, verify
from .driver import OFFLINE, validate

MANIFEST = Path(__file__).resolve().parents[1] / "native-manifest.json"
REVISION = "d637cfb935feb2254898a8f1524046c958f3df80"


def command(binary: Path, root: Path, output: Path, prompt: str, seed: int,
            width: int, height: int, steps: int, threads: int, params: str) -> list[str]:
    return [str(binary), "-m", str(root / "sd15-q4.gguf"),
            "--taesd", str(root / "taesd.safetensors"),
            "--lora-model-dir", str(root), "-p", prompt + "<lora:lcm:1>",
            "--cfg-scale", "1", "--sampling-method", "lcm", "--scheduler", "lcm",
            "--steps", str(steps), "--seed", str(seed), "--rng", "cpu",
            "--width", str(width), "--height", str(height), "--threads", str(threads),
            "--backend", "cpu", "--params-backend", params, "--diffusion-fa", "-o", str(output)]


def generate(prompt: str, output: str | Path, models: str | Path = "models/native",
             binary: str | Path = Path.home() / "nexi-image-native/stable-diffusion.cpp/build/bin/sd-cli",
             width: int = 256, height: int = 256, steps: int = 4, threads: int = 4,
             seed: int = 42, params: str = "disk", cache_state: str = "unspecified") -> dict:
    validate(prompt, width, height, steps, threads, seed, "float32", 1)
    if params not in ("cpu", "disk"):
        raise ValueError("params must be cpu or disk")
    root, output, binary = Path(models).resolve(), Path(output).resolve(), Path(binary).resolve()
    if output.suffix.lower() != ".png":
        raise ValueError("output must use a .png suffix")
    if not binary.is_file():
        raise ValueError("Native binary is missing; run setup_native.sh")
    started = time.perf_counter()
    model_bytes = verify(root, manifest=MANIFEST)
    output.parent.mkdir(parents=True, exist_ok=True)
    args = command(binary, root, output, prompt, seed, width, height, steps, threads, params)
    with output.with_suffix(".log").open("w") as log:
        process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                                   env={**os.environ, **OFFLINE})
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    if process.returncode != 0:
        raise RuntimeError(f"Native generation failed ({process.returncode}); see {output.with_suffix('.log')}")
    # sd-cli appends a batch index to the requested output name.
    indexed = output.with_name(output.stem + "_1.png")
    if indexed.is_file():
        indexed.replace(output)
    if not output.is_file():
        raise RuntimeError("Native runtime returned success without an output PNG")
    report = {"schema": 1, "model": "stable-diffusion-v1-5 Q4_0", "runtime_revision": REVISION,
              "binary_sha256": digest(binary), "command": args, "cache_state": cache_state,
              "peak_rss_bytes": usage.ru_maxrss * 1024,
              "total_wall_seconds": time.perf_counter() - started,
              "model_disk_bytes": model_bytes, "model_files": entries(manifest=MANIFEST),
              "output_sha256": digest(output), "output_bytes": output.stat().st_size}
    output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    dl = sub.add_parser("download")
    dl.add_argument("--models", default="models/native")
    check = sub.add_parser("verify")
    check.add_argument("--models", default="models/native")
    gen = sub.add_parser("generate")
    gen.add_argument("--prompt", required=True)
    gen.add_argument("--output", default="outputs/native.png")
    gen.add_argument("--models", default="models/native")
    gen.add_argument("--binary", default=str(Path.home() / "nexi-image-native/stable-diffusion.cpp/build/bin/sd-cli"))
    for name, value in (("width", 256), ("height", 256), ("steps", 4), ("threads", 4), ("seed", 42)):
        gen.add_argument(f"--{name}", type=int, default=value)
    gen.add_argument("--params", choices=["cpu", "disk"], default="disk")
    gen.add_argument("--cache-state", default="unspecified")
    args = vars(parser.parse_args())
    cmd = args.pop("command")
    try:
        result = generate(**args) if cmd == "generate" else (
            download(Path(args["models"]), manifest=MANIFEST) if cmd == "download"
            else verify(Path(args["models"]), manifest=MANIFEST))
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
