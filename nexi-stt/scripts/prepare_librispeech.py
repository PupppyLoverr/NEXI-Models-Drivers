"""Prepare the documented five-clip subset from an official local test-clean archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from nexi_stt.assets import digest
from nexi_stt.audio import inspect_wav, read_wav


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; refusing to overwrite audio or references")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        parser.error("FFmpeg is required for this optional corpus preparation helper")
    selection_path = Path(__file__).resolve().parents[1] / "fixtures/librispeech-five.json"
    selection = json.loads(selection_path.read_text())
    checksum = hashlib.md5(usedforsecurity=False)
    with args.archive.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    if checksum.hexdigest() != selection["archive_md5"]:
        parser.error("Archive does not match the official OpenSLR test-clean MD5")
    args.output.mkdir(parents=True)
    with tarfile.open(args.archive, "r:gz") as archive, tempfile.TemporaryDirectory() as temporary:
        for clip in selection["clips"]:
            source = archive.extractfile(clip["source_archive_member"])
            if source is None:
                parser.error(f"Missing corpus audio: {clip['source_archive_member']}")
            flac = Path(temporary) / "input.flac"
            with source, flac.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            wav = args.output / clip["wav"]
            subprocess.run(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-i",
                    str(flac),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    str(wav),
                ],
                check=True,
            )
            clip["wav_sha256"] = digest(wav)
            clip["audio_seconds"] = inspect_wav(read_wav(wav)).seconds
    selection["archive_sha256"] = digest(args.archive)
    (args.output / "manifest.json").write_text(json.dumps(selection, indent=2) + "\n")
    (args.output / "evaluation.jsonl").write_text(
        "".join(
            json.dumps({"wav": clip["wav"], "text": clip["reference"]}) + "\n"
            for clip in selection["clips"]
        )
    )
    print(f"Prepared {len(selection['clips'])} clips, not a full corpus evaluation: {args.output}")


if __name__ == "__main__":
    main()
