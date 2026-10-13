"""Explicit downloads, immutable revisions and SHA-256 verification."""

import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

MANIFEST = Path(__file__).resolve().parents[1] / "manifest.json"


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def entries(training: bool = False, manifest: Path = MANIFEST) -> list[dict]:
    return [item for item in json.loads(manifest.read_text())["files"]
            if training or not item["training_only"]]


def verify(root: Path, training: bool = False, hashes: bool = True,
           manifest: Path = MANIFEST) -> int:
    total = 0
    for item in entries(training, manifest):
        path = root / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"]:
            raise ValueError(f"Missing/wrong size: {path}; run the explicit download command")
        if hashes and digest(path) != item["sha256"]:
            raise ValueError(f"SHA-256 mismatch: {path}")
        total += item["bytes"]
    return total


def download(root: Path, training: bool = False, manifest: Path = MANIFEST) -> int:
    root.mkdir(parents=True, exist_ok=True)
    for item in entries(training, manifest):
        path = root / item["path"]
        if path.is_file() and digest(path) == item["sha256"]:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".partial")
        try:
            with urlopen(item["url"], timeout=120) as src, temporary.open("wb") as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
            if temporary.stat().st_size != item["bytes"] or digest(temporary) != item["sha256"]:
                raise ValueError(f"Download integrity failure: {path}")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return verify(root, training, manifest=manifest)
