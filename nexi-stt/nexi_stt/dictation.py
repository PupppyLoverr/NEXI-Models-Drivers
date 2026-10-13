"""Bounded pause-delimited PCM16 dictation. Output only finalized utterances."""

from __future__ import annotations

import io
import math
import wave
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, BinaryIO

if TYPE_CHECKING:
    from .engine import Driver

RATE = 16000
FRAME_SAMPLES = 512
FRAME_BYTES = FRAME_SAMPLES * 2
FRAME_SECONDS = FRAME_SAMPLES / RATE


class SileroStreamVAD:
    """Use the pinned faster-whisper Silero ONNX weights with continuous recurrent state."""

    def __init__(self) -> None:
        import numpy as np
        from faster_whisper.vad import get_vad_model

        self.np = np
        self.session = get_vad_model().session
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros((1, 1, 128), dtype=np.float32)
        self.context: Any = np.zeros((1, 64), dtype=np.float32)

    def __call__(self, frame: bytes) -> bool:
        signal = self.np.frombuffer(frame, dtype="<i2").astype(self.np.float32).reshape(1, 512)
        signal /= 32768.0
        sample = self.np.concatenate([self.context, signal], axis=1)
        probability, self.h, self.c = self.session.run(
            None, {"input": sample, "h": self.h, "c": self.c}
        )
        self.context = signal[:, -64:]
        return bool(probability.item() >= 0.5)


@dataclass(frozen=True)
class Utterance:
    start_frame: int
    end_frame: int
    pcm: bytes
    reason: str


class Endpoint:
    def __init__(
        self,
        *,
        pause_ms: int = 1200,
        max_utterance_seconds: int = 20,
        speech: Callable[[bytes], bool] | None = None,
    ) -> None:
        if not 200 <= pause_ms <= 3000:
            raise ValueError("Pause must be 200–3000 ms")
        if not 1 <= max_utterance_seconds <= 30:
            raise ValueError("Max utterance must be 1–30 seconds")
        self.pause_frames = math.ceil(pause_ms / 1000 / FRAME_SECONDS)
        self.max_frames = math.floor(max_utterance_seconds / FRAME_SECONDS)
        self.speech = speech if speech is not None else SileroStreamVAD()
        self.pre_roll: deque[bytes] = deque(maxlen=10)
        self.frames: list[bytes] = []
        self.frame_index = 0
        self.start_frame = 0
        self.silent_frames = 0
        self.heard_speech = False

    def feed(self, frame: bytes) -> Utterance | None:
        if len(frame) != FRAME_BYTES:
            raise ValueError("Endpoint requires 512-sample PCM16 frames")
        speaking = self.speech(frame)
        self.frame_index += 1
        if not self.frames:
            if not speaking:
                self.pre_roll.append(frame)
                return None
            self.start_frame = self.frame_index - 1 - len(self.pre_roll)
            self.frames = [*self.pre_roll]
            self.pre_roll.clear()
        self.frames.append(frame)
        self.heard_speech |= speaking
        self.silent_frames = 0 if speaking else self.silent_frames + 1
        if len(self.frames) >= self.max_frames:
            return self.flush("max_duration")
        if self.silent_frames >= self.pause_frames:
            return self.flush("pause")
        return None

    def flush(self, reason: str = "end_of_stream") -> Utterance | None:
        if not self.frames or not self.heard_speech:
            return None
        utterance = Utterance(self.start_frame, self.frame_index, b"".join(self.frames), reason)
        self.frames = []
        self.silent_frames = 0
        self.heard_speech = False
        return utterance


def pcm_to_wav(pcm: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm)
    return output.getvalue()


def stream(
    driver: Driver,
    input: BinaryIO,
    *,
    pause_ms: int = 1200,
    max_utterance_seconds: int = 20,
    profile: str = "fast",
    hotwords: str = "",
    word_timestamps: bool = False,
    endpoint: Endpoint | None = None,
) -> Iterator[dict[str, Any]]:
    endpointer = endpoint or Endpoint(
        pause_ms=pause_ms, max_utterance_seconds=max_utterance_seconds
    )

    def final(utterance: Utterance) -> dict[str, Any]:
        result = driver.transcribe(
            pcm_to_wav(utterance.pcm),
            hotwords=hotwords,
            word_timestamps=word_timestamps,
            vad=False,
            profile=profile,
        )
        start_seconds = utterance.start_frame * FRAME_SECONDS
        for segment in result["segments"]:
            segment["start"] += start_seconds
            segment["end"] += start_seconds
            for word in segment.get("words", []):
                word["start"] += start_seconds
                word["end"] += start_seconds
        result["event"] = "final"
        result["reason"] = utterance.reason
        result["stream_start_seconds"] = start_seconds
        result["stream_end_seconds"] = utterance.end_frame * FRAME_SECONDS
        return result

    pending = bytearray()
    while chunk := input.read(FRAME_BYTES):
        pending.extend(chunk)
        while len(pending) >= FRAME_BYTES:
            frame = bytes(pending[:FRAME_BYTES])
            del pending[:FRAME_BYTES]
            utterance = endpointer.feed(frame)
            if utterance:
                yield final(utterance)
    if len(pending) % 2:
        raise ValueError("Raw PCM16 stream ends with an incomplete sample")
    if pending:
        utterance = endpointer.feed(bytes(pending).ljust(FRAME_BYTES, b"\0"))
        if utterance:
            yield final(utterance)
    utterance = endpointer.flush()
    if utterance:
        yield final(utterance)
