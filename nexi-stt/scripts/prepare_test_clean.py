"""Prepare a fixed hash-selected, five-clips-per-speaker LibriSpeech test-clean subset."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import tarfile
from collections import defaultdict
from pathlib import Path, PurePosixPath

import av

from nexi_stt.assets import digest
from nexi_stt.dictation import pcm_to_wav


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--destination", type=Path, default=Path("fixtures/test-clean"))
    parser.add_argument("--manifest", type=Path, default=Path("fixtures/test-clean.jsonl"))
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{64}", args.sha256) or digest(args.archive) != args.sha256:
        parser.error("Archive SHA256 mismatch")
    groups = defaultdict(list)
    transcripts = {}
    with tarfile.open(args.archive, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if not member.isfile() or not member.name.startswith("LibriSpeech/test-clean/"):
                continue
            if member.size > 2 * 1024 * 1024:
                raise ValueError("Unexpectedly large corpus member")
            if re.fullmatch(r"\d+-\d+-\d+\.flac", path.name):
                groups[path.name.split("-")[0]].append(member)
            if path.name.endswith(".trans.txt"):
                handle = archive.extractfile(member)
                if handle is None:
                    raise ValueError("Missing transcript member")
                with handle:
                    for line in handle.read().decode().splitlines():
                        name, _, text = line.partition(" ")
                        transcripts[name] = text
        if len(groups) != 40:
            raise ValueError("Expected 40 speakers in LibriSpeech test-clean")
        selected = [
            member
            for members in groups.values()
            for member in sorted(
                members,
                key=lambda item: hashlib.sha256(item.name.encode()).hexdigest(),
            )[:5]
        ]
        args.destination.mkdir(parents=True, exist_ok=True)
        rows = []
        for member in sorted(selected, key=lambda item: item.offset_data):
            name = PurePosixPath(member.name).stem
            handle = archive.extractfile(member)
            if handle is None:
                raise ValueError("Missing audio member")
            with handle, av.open(io.BytesIO(handle.read())) as source:
                resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
                pcm = b"".join(
                    frame.to_ndarray().tobytes()
                    for packet in source.decode(audio=0)
                    for frame in resampler.resample(packet)
                )
                pcm += b"".join(frame.to_ndarray().tobytes() for frame in resampler.resample(None))
            target = args.destination / f"{name}.wav"
            target.write_bytes(pcm_to_wav(pcm))
            try:
                wav_path = target.resolve().relative_to(args.manifest.parent.resolve())
            except ValueError:
                wav_path = target.resolve()
            rows.append(
                {
                    "wav": str(wav_path),
                    "text": transcripts[name],
                    "speaker_id": int(name.split("-")[0]),
                    "kind": "speech",
                }
            )
    args.manifest.write_text(
        "".join(json.dumps(row) + "\n" for row in sorted(rows, key=lambda r: r["wav"]))
    )
    print(f"Prepared {len(rows)} clips across {len(groups)} speakers: {args.manifest}")


if __name__ == "__main__":
    main()
