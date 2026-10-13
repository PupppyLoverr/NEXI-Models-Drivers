"""Local-only CPU ONNX adapter, derived from KittenML's Apache-2.0 v0.8 frontend."""

from __future__ import annotations

import io
import math
import os
import tempfile
import threading
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .assets import default_model_dir, profile_for, verify_assets
from .text import CHUNK_CHARS, chunk_text, normalize, tokenize

SAMPLE_RATE = 24000
Audio = NDArray[np.float32]


def pcm16(audio: Audio) -> bytes:
    if audio.ndim != 1 or not audio.size or not np.isfinite(audio).all():
        raise ValueError("Expected nonempty finite mono audio")
    return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def wav_bytes(audio: Audio) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes(pcm16(audio))
    return out.getvalue()


class Synthesizer:
    def __init__(
        self,
        model_dir: Path | str | None = None,
        threads: int = 2,
        *,
        profile: str = "nano",
        chunk_chars: int = CHUNK_CHARS,
    ) -> None:
        if isinstance(threads, bool) or not isinstance(threads, int) or not 1 <= threads <= 8:
            raise ValueError("threads must be between one and eight")
        if (
            isinstance(chunk_chars, bool)
            or not isinstance(chunk_chars, int)
            or not 80 <= chunk_chars <= 180
        ):
            raise ValueError("chunk_chars must be an integer between 80 and 180")
        self.chunk_chars = chunk_chars
        spec = profile_for(profile)
        self.profile = profile
        self.model_dir = Path(model_dir) if model_dir is not None else default_model_dir(profile)
        config = verify_assets(self.model_dir, profile)
        import espeakng_loader
        import onnxruntime as ort
        from phonemizer.backend import EspeakBackend
        from phonemizer.backend.espeak.wrapper import EspeakWrapper

        os.environ["ESPEAK_DATA_PATH"] = espeakng_loader.get_data_path()
        EspeakWrapper.set_library(espeakng_loader.get_library_path())
        self.phonemizer = EspeakBackend(
            language="en-us", preserve_punctuation=True, with_stress=True
        )
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        self.session = ort.InferenceSession(
            str(self.model_dir / spec.model_file), options, providers=["CPUExecutionProvider"]
        )
        with np.load(self.model_dir / "voices.npz", allow_pickle=False) as bundle:
            self._voices = {name: bundle[name].astype(np.float32) for name in bundle.files}
        self.voice_aliases = dict(config["voice_aliases"])
        self.speed_priors = dict(config["speed_priors"])
        self.threads = threads
        self._lock = threading.Lock()

    @property
    def voices(self) -> list[str]:
        return list(self.voice_aliases)

    def iter_audio(
        self,
        text: str,
        voice: str = "Jasper",
        language: str = "en",
        speed: float = 1.0,
        *,
        first_chunk_chars: int | None = None,
    ) -> Iterator[Audio]:
        if language not in ("en", "en-us"):
            raise ValueError("This Kitten 0.8 model supports only English (en or en-us)")
        if voice not in self.voice_aliases:
            raise ValueError(f"Unknown voice {voice!r}; choose from {', '.join(self.voices)}")
        if (
            isinstance(speed, bool)
            or not isinstance(speed, int | float)
            or not 0.5 <= speed <= 2.0
            or not math.isfinite(speed)
        ):
            raise ValueError("speed must be finite and between 0.5 and 2.0")
        cleaned = normalize(text)
        voice_id = self.voice_aliases[voice]
        for chunk in chunk_text(cleaned, self.chunk_chars, first_chunk_chars=first_chunk_chars):
            with self._lock:
                phonemes = self.phonemizer.phonemize([chunk], njobs=1)[0]
                tokens = tokenize(phonemes)
                reference = min(len(chunk), self._voices[voice_id].shape[0] - 1)
                inputs: dict[str, Any] = {
                    "input_ids": np.array([tokens], dtype=np.int64),
                    "style": self._voices[voice_id][reference : reference + 1],
                    "speed": np.array(
                        [speed * self.speed_priors.get(voice_id, 1.0)], dtype=np.float32
                    ),
                }
                audio = np.asarray(self.session.run(None, inputs)[0], dtype=np.float32).reshape(-1)
            # Kitten's official 0.8 adapter removes 5000 trailing samples per chunk.
            if len(audio) <= 5000 or not np.isfinite(audio).all():
                raise RuntimeError("Model produced empty or non-finite audio")
            yield audio[:-5000]

    def synthesize(
        self, text: str, voice: str = "Jasper", language: str = "en", speed: float = 1.0
    ) -> Audio:
        return np.concatenate(list(self.iter_audio(text, voice, language, speed))).astype(
            np.float32
        )

    def to_file(
        self,
        text: str,
        output: Path | str,
        voice: str = "Jasper",
        language: str = "en",
        speed: float = 1.0,
    ) -> int:
        destination = Path(output)
        samples = 0
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, suffix=".part", delete=False
            ) as out:
                temporary = Path(out.name)
                with wave.open(out, "wb") as stream:
                    stream.setnchannels(1)
                    stream.setsampwidth(2)
                    stream.setframerate(SAMPLE_RATE)
                    for audio in self.iter_audio(text, voice, language, speed):
                        samples += len(audio)
                        stream.writeframes(pcm16(audio))
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return samples
