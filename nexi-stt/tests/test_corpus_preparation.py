from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prepare_librispeech.py"


def test_existing_directory_is_not_overwritten(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--archive", "unused", "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "refusing to overwrite" in result.stderr
    assert marker.read_text() == "keep"


def test_missing_ffmpeg_is_actionable(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--archive", "unused", "--output", str(tmp_path / "out")],
        env={**os.environ, "PATH": ""},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "FFmpeg is required" in result.stderr
    assert not (tmp_path / "out").exists()


def test_invalid_archive_never_creates_output(tmp_path: Path) -> None:
    executable = tmp_path / "ffmpeg"
    executable.write_text("#!/bin/sh\nexit 1\n")
    executable.chmod(0o755)
    archive = tmp_path / "invalid.tar.gz"
    archive.write_bytes(b"not an official corpus")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--archive", str(archive), "--output", str(tmp_path / "out")],
        env={**os.environ, "PATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "official OpenSLR test-clean MD5" in result.stderr
    assert not (tmp_path / "out").exists()
