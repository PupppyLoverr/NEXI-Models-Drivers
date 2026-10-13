from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Any


def catalog() -> dict[str, Any]:
    return dict(json.loads(Path(__file__).with_name("assets.json").read_text()))


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def verify(directory: Path, files: list[dict[str, Any]]) -> None:
    for item in files:
        path = directory / item["name"]
        if not path.is_file() or path.stat().st_size != item["bytes"]:
            raise ValueError(f"Missing/wrong-size asset: {path}; run explicit download")
        if digest(path) != item["sha256"]:
            raise ValueError(f"Checksum mismatch: {path}")


def download(preset: str, destination: Path) -> None:
    """The only driver operation that accesses the network."""
    spec = catalog()[preset]
    destination.mkdir(parents=True, exist_ok=True)
    for item in spec["files"]:
        path = destination / item["name"]
        if path.is_file() and path.stat().st_size == item["bytes"]:
            if digest(path) == item["sha256"]:
                continue
        fd, temporary = tempfile.mkstemp(prefix=".download-", dir=destination)
        try:
            sha = hashlib.sha256()
            size = 0
            request = urllib.request.Request(item["url"], headers={"User-Agent": "nexi-stt/0.1"})
            with (
                os.fdopen(fd, "wb") as output,
                urllib.request.urlopen(request, timeout=60) as response,
            ):
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > item["bytes"]:
                        raise ValueError(f"Oversized download: {item['name']}")
                    sha.update(chunk)
                    output.write(chunk)
            if size != item["bytes"] or sha.hexdigest() != item["sha256"]:
                raise ValueError(f"Download checksum/size mismatch: {item['name']}")
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    (destination / "nexi-assets.json").write_text(json.dumps(spec, indent=2) + "\n")


def verify_model(directory: Path) -> dict[str, Any]:
    directory = directory.resolve()
    if not directory.is_dir():
        raise ValueError(f"Local model directory not found: {directory}; no auto-download")
    manifest = directory / "nexi-assets.json"
    if not manifest.is_file():
        raise ValueError("Model requires nexi-assets.json; download or export it explicitly")
    spec: dict[str, Any] = json.loads(manifest.read_text())
    names = {item["name"] for item in spec["files"]}
    if not {"model.bin", "config.json", "tokenizer.json"}.issubset(names):
        raise ValueError("Model manifest is incomplete")
    for name in names:
        if not isinstance(name, str) or Path(name).name != name or name in (".", ".."):
            raise ValueError("Model manifest must use flat local filenames")
    verify(directory, spec["files"])
    return spec
