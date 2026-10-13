"""Extract pinned LibriSpeech dummy sample to PCM16 WAV + deterministic non-speech controls."""

from __future__ import annotations

import io
import json
import wave
from pathlib import Path

import av
import numpy as np
import pyarrow.parquet as pq

from nexi_stt.assets import verify

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "fixtures" / "eval-source"
DESTINATION = ROOT / "fixtures" / "eval"


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm)


def main() -> None:
    from nexi_stt.assets import catalog

    verify(SOURCE, catalog()["sample-librispeech"]["files"])
    DESTINATION.mkdir(parents=True, exist_ok=True)
    table = pq.read_table(SOURCE / "validation.parquet")
    rows = []
    for record in table.to_pylist():
        name = record["id"]
        audio = record["audio"]["bytes"]
        with av.open(io.BytesIO(audio)) as source:
            resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
            pcm = b"".join(
                frame.to_ndarray().tobytes()
                for packet in source.decode(audio=0)
                for frame in resampler.resample(packet)
            )
            pcm += b"".join(frame.to_ndarray().tobytes() for frame in resampler.resample(None))
        write_wav(DESTINATION / f"{name}.wav", pcm)
        rows.append(
            {
                "wav": f"eval/{name}.wav",
                "text": record["text"],
                "speaker_id": record["speaker_id"],
                "kind": "speech",
            }
        )
    write_wav(DESTINATION / "digital-silence.wav", bytes(16000 * 2 * 10))
    rng = np.random.default_rng(13)
    noise = np.clip(rng.normal(0, 0.01, 16000 * 10) * 32768, -32768, 32767)
    write_wav(DESTINATION / "synthetic-white-noise.wav", noise.astype("<i2").tobytes())
    for name in ("digital-silence", "synthetic-white-noise"):
        rows.append({"wav": f"eval/{name}.wav", "text": "", "kind": "non_speech"})
    manifest = ROOT / "fixtures" / "evaluation.jsonl"
    manifest.write_text("".join(json.dumps(row) + "\n" for row in rows))
    print(f"Prepared {len(rows)} clips from one speaker plus two synthetic controls: {manifest}")


if __name__ == "__main__":
    main()
