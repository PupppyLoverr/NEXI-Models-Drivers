"""Only download() performs network I/O. All inference assets are immutable."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import TypedDict, cast


class ModelConfig(TypedDict):
    voice_aliases: dict[str, str]
    speed_priors: dict[str, float]


REPOSITORY = "KittenML/kitten-tts-nano-0.8-int8"
REVISION = "84781d74e29ee25217551556398b42f80593a813"
MODEL_FILE = "kitten_tts_nano_v0_8.onnx"
FILES = {
    MODEL_FILE: (24369971, "f7b0afcbee92870b32b8e0276d855b954dc25470c9f051b376ac7eee537c76fc"),
    "voices.npz": (3278902, "8aa7cee235abb0739cb51e6559685f65a4dacd95568833d05699b1633f519b3f"),
    "config.json": (688, "b66006ccbeccd4de5fc3c9272059c47f5725df7215fd889785c03602652fab64"),
    "README.md": (741, "ff39adbcb653e9beaa612b405c4e301ee62eb4201b32dd77ae36f4078537b8ef"),
}


def default_model_dir() -> Path:
    return Path(__file__).resolve().parent.parent / ".models" / "nano-int8"


def verified(path: Path, size: int, digest: str) -> bool:
    if not path.is_file() or path.stat().st_size != size:
        return False
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest() == digest


def verify_assets(directory: Path) -> ModelConfig:
    for name, (size, digest) in FILES.items():
        if not verified(directory / name, size, digest):
            raise ValueError(
                f"Missing or corrupt asset: {directory / name}. "
                "Run python -m nexi_tts download --model-dir PATH explicitly."
            )
    return cast(ModelConfig, json.loads((directory / "config.json").read_text(encoding="utf-8")))


def download(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, (size, digest) in FILES.items():
        target = directory / name
        if verified(target, size, digest):
            continue
        url = f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}"
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, suffix=".part", delete=False) as out:
                temporary = Path(out.name)
                request = urllib.request.Request(url, headers={"User-Agent": "nexi-tts/0.1"})
                with urllib.request.urlopen(request, timeout=60) as response:
                    total = 0
                    while block := response.read(1024 * 1024):
                        total += len(block)
                        if total > size:
                            raise ValueError(f"Oversize download: {name}")
                        out.write(block)
            if not verified(temporary, size, digest):
                raise ValueError(f"Checksum or size mismatch: {name}")
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    verify_assets(directory)
