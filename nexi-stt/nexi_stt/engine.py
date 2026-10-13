from __future__ import annotations

import io
import os
import time
from pathlib import Path
from typing import Any

from .assets import verify_model
from .audio import inspect_wav

PROFILES = {"fast": 1, "balanced": 5}


def offline_environment() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


class Driver:
    def __init__(self, model: Path, *, threads: int = 4) -> None:
        if not 1 <= threads <= 64:
            raise ValueError("threads must be 1–64")
        offline_environment()
        start = time.perf_counter()
        self.metadata = verify_model(model)
        # Import only after validating the local assets and enabling offline mode.
        from faster_whisper import WhisperModel

        self.model = WhisperModel(
            str(model.resolve()),
            device="cpu",
            compute_type="int8",
            cpu_threads=threads,
            num_workers=1,
            local_files_only=True,
        )
        self.threads = threads
        self.load_seconds = time.perf_counter() - start

    def transcribe(
        self,
        audio: bytes,
        *,
        hotwords: str = "",
        word_timestamps: bool = False,
        vad: bool = True,
        profile: str = "fast",
        vad_silence_ms: int = 2000,
    ) -> dict[str, Any]:
        info = inspect_wav(audio)
        if len(hotwords) > 400 or any(ord(char) < 32 for char in hotwords):
            raise ValueError("Vocabulary hints must be <=400 characters without control characters")
        if profile not in PROFILES:
            raise ValueError("Profile must be fast or balanced")
        if not 100 <= vad_silence_ms <= 3000:
            raise ValueError("VAD silence must be 100–3000 ms")
        start = time.perf_counter()
        segments, details = self.model.transcribe(
            io.BytesIO(audio),
            language="en",
            task="transcribe",
            beam_size=PROFILES[profile],
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            word_timestamps=word_timestamps,
            vad_filter=vad,
            vad_parameters={"min_silence_duration_ms": vad_silence_ms},
            hotwords=hotwords or None,
        )
        rendered = []
        for segment in segments:
            row: dict[str, Any] = {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
                "no_speech_probability": segment.no_speech_prob,
            }
            if word_timestamps:
                row["words"] = [
                    {"start": w.start, "end": w.end, "text": w.word, "probability": w.probability}
                    for w in segment.words or []
                ]
            rendered.append(row)
        elapsed = time.perf_counter() - start
        return {
            "schema_version": 1,
            "text": " ".join(row["text"] for row in rendered),
            "segments": rendered,
            "language": details.language,
            "audio_seconds": info.seconds,
            "speech_seconds_after_vad": details.duration_after_vad,
            "transcribe_seconds": elapsed,
            "real_time_factor": elapsed / info.seconds,
            "config": {
                "device": "cpu",
                "compute_type": "int8",
                "threads": self.threads,
                "profile": profile,
                "beam_size": PROFILES[profile],
                "temperature": 0.0,
                "vad": vad,
                "vad_silence_ms": vad_silence_ms,
                "word_timestamps": word_timestamps,
                "hotwords": hotwords,
                "condition_on_previous_text": False,
            },
            "model": {key: value for key, value in self.metadata.items() if key != "files"},
        }
