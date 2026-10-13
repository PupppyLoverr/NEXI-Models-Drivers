"""Only download() performs network I/O. All inference assets are immutable."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ModelProfile:
    repository: str
    revision: str
    model_file: str
    directory: str
    files: dict[str, tuple[int, str]]


PROFILES = {
    "nano": ModelProfile(REPOSITORY, REVISION, MODEL_FILE, "nano-int8", FILES),
    "mini": ModelProfile(
        "KittenML/kitten-tts-mini-0.8",
        "c02725660cea441db4c383af69f1f26f5cd00947",
        "kitten_tts_mini_v0_8.onnx",
        "mini",
        {
            "kitten_tts_mini_v0_8.onnx": (
                78268016,
                "0f5bbae4fc4800c98dbc544a87ecfa79510de2fb8222db30d12e5bfe9177df91",
            ),
            "voices.npz": (
                3278902,
                "40ad2638952b77b7b2f30127e2608e169fc69dd256b53bd8aaa3409a33193c42",
            ),
            "config.json": (
                470,
                "6b160bc9b19e24ecb21e84bc14f8a7da21fdf47ec72d42450bc5cf514b61804a",
            ),
            "README.md": (734, "cab0af19aa75f409684d165407c32a0d845cc8fc660606c379f4b0663f87abae"),
        },
    ),
}


def profile_for(profile: str) -> ModelProfile:
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile {profile!r}; choose from {', '.join(PROFILES)}")
    return PROFILES[profile]


def default_model_dir(profile: str = "nano") -> Path:
    return Path(__file__).resolve().parent.parent / ".models" / profile_for(profile).directory


def verified(path: Path, size: int, digest: str) -> bool:
    if not path.is_file() or path.stat().st_size != size:
        return False
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest() == digest


def verify_assets(directory: Path, profile: str = "nano") -> ModelConfig:
    for name, (size, digest) in profile_for(profile).files.items():
        if not verified(directory / name, size, digest):
            raise ValueError(
                f"Missing or corrupt asset: {directory / name}. "
                f"Run python -m nexi_tts download --profile {profile} --model-dir PATH explicitly."
            )
    return cast(ModelConfig, json.loads((directory / "config.json").read_text(encoding="utf-8")))


def download(directory: Path, profile: str = "nano") -> None:
    spec = profile_for(profile)
    directory.mkdir(parents=True, exist_ok=True)
    for name, (size, digest) in spec.files.items():
        target = directory / name
        if verified(target, size, digest):
            continue
        url = f"https://huggingface.co/{spec.repository}/resolve/{spec.revision}/{name}"
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
    verify_assets(directory, profile)
