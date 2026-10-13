from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 10 * 1024 * 1024
MAX_SECONDS = 120.0


@dataclass(frozen=True)
class AudioInfo:
    seconds: float
    sample_rate: int
    channels: int
    frames: int


def read_wav(path: Path) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    inspect_wav(data)
    return data


def inspect_wav(data: bytes) -> AudioInfo:
    if len(data) > MAX_BYTES:
        raise ValueError("WAV exceeds 10 MiB")
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            rate, channels, frames = wav.getframerate(), wav.getnchannels(), wav.getnframes()
            if wav.getcomptype() != "NONE" or wav.getsampwidth() != 2:
                raise ValueError("Only uncompressed signed PCM16 WAV is supported")
            if channels not in (1, 2) or not 8000 <= rate <= 48000:
                raise ValueError("WAV must have 1–2 channels, 8000–48000 Hz")
            seconds = frames / rate
            if not 0 < seconds <= MAX_SECONDS:
                raise ValueError("WAV duration must be >0 and <=120 seconds; split longer clips")
            if len(wav.readframes(frames)) != frames * channels * 2:
                raise ValueError("Truncated WAV audio")
            return AudioInfo(seconds, rate, channels, frames)
    except (wave.Error, EOFError) as exc:
        raise ValueError("Invalid PCM16 WAV") from exc
