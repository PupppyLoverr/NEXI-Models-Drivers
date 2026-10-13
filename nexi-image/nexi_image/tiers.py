"""Three offline native generation/editing profiles, with measured RAM targets."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .assets import digest, download, entries
from .driver import OFFLINE, hardware_info
from .native import REVISION

MANIFESTS = Path(__file__).resolve().parents[1] / "manifests"
BINARY = Path.home() / "nexi-image-native/stable-diffusion.cpp/build/bin/sd-cli"
TIERS = ("small", "medium", "best")


def spec(tier: str) -> tuple[Path, dict]:
    if tier not in TIERS:
        raise ValueError(f"tier must be one of {TIERS}")
    manifest = MANIFESTS / f"{tier}.json"
    return manifest, json.loads(manifest.read_text())


def runtime_version(binary: Path) -> str:
    if not sys.platform.startswith("linux"):
        raise ValueError("The measured tier wrapper currently requires Linux (Windows: use WSL2)")
    if not binary.is_file():
        raise ValueError("Native binary missing; run setup_native.sh")
    version = subprocess.check_output([str(binary), "--version"], text=True).strip()
    if REVISION[:7] not in version:
        raise ValueError(f"Expected native revision {REVISION}; got {version}")
    return version


def prepare(tier: str, models: str | Path = "models/tiers", binary: str | Path = BINARY) -> dict:
    manifest, config = spec(tier)
    root, binary = Path(models).resolve() / tier, Path(binary).resolve()
    runtime_version(binary)
    source_bytes = download(root, manifest=manifest)
    if config["prepare"] == "none":
        return {"download_bytes": source_bytes, "runtime_model_bytes": source_bytes}
    stamp = digest(manifest)
    receipt_path = root / "build.json"
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("manifest_sha256") == stamp and (root / "model.gguf").is_file():
            verify_runtime(tier, Path(models))
            return receipt
    with tempfile.TemporaryDirectory(dir=root, prefix=".build-") as tmp:
        workspace = Path(tmp)
        source = root / "source.safetensors"
        if config["prepare"] == "bk":
            source = workspace / "mapped.safetensors"
            subprocess.run([sys.executable, "-m", "nexi_image.convert_bk", str(root), str(source)],
                           check=True, env={**os.environ, **OFFLINE})
        target = workspace / "model.gguf"
        args = [str(binary), "-M", "convert", "-m", str(source), "--type",
                config["quantization"], "-o", str(target)]
        with (root / "build.log").open("w") as log:
            subprocess.run(args, check=True, stdout=log, stderr=subprocess.STDOUT,
                           env={**os.environ, **OFFLINE})
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError("Conversion returned without model weights")
        receipt = {"schema": 1, "manifest_sha256": stamp, "runtime_revision": REVISION,
                   "binary_sha256": digest(binary), "sources": entries(manifest=manifest),
                   "output": {"path": "model.gguf", "bytes": target.stat().st_size,
                              "sha256": digest(target)}, "download_bytes": source_bytes,
                   "quantization": config["quantization"]}
        target.replace(root / "model.gguf")
        staging = workspace / "build.json"
        staging.write_text(json.dumps(receipt, indent=2) + "\n")
        staging.replace(receipt_path)
    return receipt


def verify_runtime(tier: str, models: Path) -> list[dict]:
    manifest, config = spec(tier)
    root = models.resolve() / tier
    files = [item for item in entries(manifest=manifest) if not item.get("source_only")]
    if config["prepare"] != "none":
        receipt_path = root / "build.json"
        if not receipt_path.is_file():
            raise ValueError("Missing conversion receipt; run download for this tier")
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("manifest_sha256") != digest(manifest) or receipt.get("runtime_revision") != REVISION:
            raise ValueError("Conversion receipt is incompatible with the pinned profile")
        files = [*files, receipt["output"]]
    for item in files:
        path = root / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
            raise ValueError(f"Runtime model missing/corrupt: {path}; run download")
    return files


def command(tier: str, binary: Path, root: Path, target: Path, prompt: str,
            width: int, height: int, steps: int, threads: int, seed: int,
            image: Path | None = None, mask: Path | None = None,
            strength: float | None = None, references: list[Path] | None = None) -> list[str]:
    _, config = spec(tier)
    if config["family"] == "flux2":
        args = ["--diffusion-model", str(root / "model.gguf"), "--llm", str(root / "text.gguf"),
                "--vae", str(root / "vae.safetensors")]
        args += [value for p in ([image] if image else []) + (references or [])
                 for value in ("--ref-image", str(p))]
    else:
        args = ["-m", str(root / "model.gguf")]
        if config["family"] == "sd1":
            args += ["--taesd", str(root / "taesd.safetensors")]
        if image:
            args += ["--init-img", str(image), "--strength", str(strength if strength is not None else .65)]
            if mask:
                args += ["--mask", str(mask)]
    return [str(binary), *args, "-p", prompt, "--cfg-scale", str(config["guidance"]),
            "--sampling-method", config["sampler"], "--scheduler", config["scheduler"],
            "--steps", str(steps), "--seed", str(seed), "--rng", "cpu", "-W", str(width),
            "-H", str(height), "--threads", str(threads), "--backend", "cpu",
            "--params-backend", "disk", "--diffusion-fa", "--vae-tiling", "-o", str(target)]


def rss(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (FileNotFoundError, ProcessLookupError):
        pass
    return 0


def run(args: list[str], log_path: Path) -> dict:
    started = time.perf_counter()
    parent_peak, tree_peak = rss(os.getpid()), rss(os.getpid())
    with log_path.open("w") as log:
        process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                                   env={**os.environ, **OFFLINE})
        try:
            while True:
                parent, child = rss(os.getpid()), rss(process.pid)
                parent_peak = max(parent_peak, parent)
                tree_peak = max(tree_peak, parent + child)
                pid, status, usage = os.wait4(process.pid, os.WNOHANG)
                if pid:
                    process.returncode = os.waitstatus_to_exitcode(status)
                    break
                time.sleep(.05)
        except BaseException:
            process.kill()
            process.wait()
            raise
    if process.returncode:
        raise RuntimeError(f"Native generation failed ({process.returncode}); see {log_path}")
    return {"child_peak_rss_bytes": usage.ru_maxrss * 1024,
            "sampled_parent_peak_rss_bytes": parent_peak, "sampled_tree_peak_rss_bytes": tree_peak,
            "sampling_interval_seconds": .05, "native_wall_seconds": time.perf_counter() - started}


def stage_image(source: Path, target: Path, size: tuple[int, int], mask: bool = False) -> None:
    from PIL import Image, ImageOps
    with Image.open(source) as image:
        if image.width * image.height > 16_777_216:
            raise ValueError("Input images must be at most 16 megapixels")
        image = ImageOps.exif_transpose(image).convert("L" if mask else "RGB")
        image = ImageOps.pad(image, size, method=Image.Resampling.NEAREST if mask
                             else Image.Resampling.LANCZOS, color=0)
        image.save(target)


def composite(target: Path, image: Path, mask: Path) -> None:
    from PIL import Image
    with Image.open(target) as result, Image.open(image) as original, Image.open(mask) as selection:
        Image.composite(result.convert("RGB"), original.convert("RGB"), selection.convert("L")).save(target)


def generate(tier: str, prompt: str, output: str | Path, models: str | Path = "models/tiers",
             binary: str | Path = BINARY, width: int | None = None, height: int | None = None,
             steps: int | None = None, threads: int = 4, seed: int = 42,
             image: str | Path | None = None, mask: str | Path | None = None,
             strength: float | None = None, reference: list[str] | None = None,
             cache_state: str = "unspecified") -> dict:
    started = time.perf_counter()
    manifest, config = spec(tier)
    width = config["width"] if width is None else width
    height = config["width"] if height is None else height
    steps = config["steps"] if steps is None else steps
    if any(type(n) is not int for n in (width, height, steps, threads, seed)):
        raise ValueError("dimensions, steps, threads and seed must be integers")
    if not prompt.strip() or len(prompt) > 4000:
        raise ValueError("prompt must contain 1–4000 characters")
    if any(n < 128 or n > 1024 or n % 64 for n in (width, height)):
        raise ValueError("dimensions must be multiples of 64 from 128 through 1024")
    if not 1 <= threads <= 64 or not 0 <= seed < 2**63 or not 1 <= steps <= 50:
        raise ValueError("Invalid threads, seed or steps")
    if tier != "small" and steps != config["steps"]:
        raise ValueError("Distilled medium/best profiles require exactly four steps")
    if mask and not image:
        raise ValueError("A mask requires an input image")
    if strength is not None and (not image or not math.isfinite(strength) or not 0 < strength <= 1):
        raise ValueError("strength requires an image and must be finite in (0, 1]")
    if tier == "best" and strength is not None:
        raise ValueError("Instruction editing does not use img2img strength")
    if reference and (tier != "best" or len(reference) > 3):
        raise ValueError("Up to three additional reference images are supported by best only")
    root, binary, output = Path(models).resolve() / tier, Path(binary).resolve(), Path(output).resolve()
    if output.suffix.lower() != ".png":
        raise ValueError("output must have a .png suffix")
    sources = [Path(p).resolve() for p in ([str(image)] if image else []) + (reference or [])]
    inputs = [{"path": str(p), "sha256": digest(p)} for p in sources]
    if mask:
        inputs.append({"path": str(Path(mask).resolve()), "sha256": digest(Path(mask))})
    version = runtime_version(binary)
    files = verify_runtime(tier, Path(models))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".tier-") as tmp:
        workspace = Path(tmp)
        staged = []
        for i, source in enumerate(sources):
            path = workspace / f"input-{i}.png"
            stage_image(source, path, (width, height))
            staged.append(path)
        staged_image = staged[0] if image else None
        staged_mask = workspace / "mask.png" if mask else None
        if staged_mask:
            from PIL import Image, ImageOps
            with Image.open(str(image)) as original, Image.open(str(mask)) as selection:
                if ImageOps.exif_transpose(original).size != ImageOps.exif_transpose(selection).size:
                    raise ValueError("Mask and input must have identical EXIF-oriented dimensions")
            stage_image(Path(str(mask)), staged_mask, (width, height), mask=True)
        target = workspace / "image.png"
        args = command(tier, binary, root, target, prompt, width, height, steps, threads, seed,
                       staged_image, staged_mask, strength, staged[1:] if image else staged)
        metrics = run(args, output.with_suffix(".log"))
        indexed = target.with_name("image_1.png")
        if indexed.is_file():
            indexed.replace(target)
        if not target.is_file():
            raise RuntimeError("Native process returned success without an image")
        if staged_image and staged_mask:
            composite(target, staged_image, staged_mask)
        from PIL import Image
        with Image.open(target) as result:
            if result.size != (width, height):
                raise RuntimeError("Native output dimensions differ from requested dimensions")
            pixel_hash = hashlib.sha256(result.convert("RGB").tobytes()).hexdigest()
        target.replace(output)
    import resource
    parent_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    upper_bound = parent_peak + metrics["child_peak_rss_bytes"]
    report = {"schema": 2, "tier": tier, "model": config["model"], "mode": "edit" if sources else "generate",
              "config": {"prompt": prompt, "width": width, "height": height, "steps": steps,
                         "seed": seed, "threads": threads, "strength": strength,
                         "masked": bool(mask), "reference_count": len(sources)},
              "runtime_revision": REVISION, "runtime_version": version, "binary_sha256": digest(binary),
              "manifest_sha256": digest(manifest), "upstream_files": entries(manifest=manifest),
              "runtime_files": files, "model_disk_bytes": sum(f["bytes"] for f in files),
              "inputs": inputs, "output_sha256": digest(output), "output_rgb_sha256": pixel_hash,
              "output_bytes": output.stat().st_size, "output": str(output), "command": args,
              "hardware": hardware_info(), "cache_state": cache_state, **metrics,
              "parent_peak_rss_bytes": parent_peak, "conservative_peak_rss_bound_bytes": upper_bound,
              "ram_target_bytes": config["budget_bytes"],
              "fits_ram_target_conservative": upper_bound <= config["budget_bytes"],
              "rss_scope": "single native child plus calling Python process; excludes OS/page cache/other apps",
              "total_wall_seconds": time.perf_counter() - started}
    output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for action in ("download", "verify", "generate", "edit"):
        child = sub.add_parser(action)
        child.add_argument("--tier", choices=TIERS, required=True)
        child.add_argument("--models", default="models/tiers")
        if action != "verify":
            child.add_argument("--binary", default=str(BINARY))
        if action in ("generate", "edit"):
            child.add_argument("--prompt", required=True)
            child.add_argument("--output", required=True)
            for key, value in (("width", None), ("height", None), ("steps", None), ("threads", 4), ("seed", 42)):
                child.add_argument(f"--{key}", type=int, default=value)
            child.add_argument("--cache-state", default="unspecified")
            if action == "edit":
                child.add_argument("--image", required=True)
                child.add_argument("--mask")
                child.add_argument("--strength", type=float)
                child.add_argument("--reference", action="append")
    args = vars(parser.parse_args())
    action = args.pop("command")
    try:
        result: dict | list[dict]
        if action == "download":
            result = prepare(**args)
        elif action == "verify":
            result = verify_runtime(args["tier"], Path(args["models"]))
        else:
            result = generate(**args)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
