"""Real CPU pause/EOF/bounded-buffer dictation checks, using already-local audio/models."""

from __future__ import annotations

import argparse
import io
import json
import platform
import resource
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from nexi_stt.benchmark import hardware
from nexi_stt.dictation import FRAME_BYTES, Endpoint, SileroStreamVAD, stream
from nexi_stt.engine import Driver
from nexi_stt.metrics import word_error_rate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--wav", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with wave.open(str(args.wav), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            parser.error("Regression requires PCM16 mono 16 kHz fixture")
        audio = wav.readframes(wav.getnframes())
    reference = args.reference.read_text()
    driver = Driver(args.model)
    pcm = bytes(32000) + audio + bytes(48000) + audio + bytes(48000)
    start = time.perf_counter()
    events = list(stream(driver, io.BytesIO(pcm), word_timestamps=True))
    wall = time.perf_counter() - start
    assert len(events) == 2 and all(row["reason"] == "pause" for row in events)
    quality = [word_error_rate(reference, row["text"]) for row in events]
    assert all(row["word_errors"] == 0 for row in quality), quality
    assert events[1]["stream_start_seconds"] >= events[0]["stream_end_seconds"]
    assert events[1]["segments"][0]["words"][0]["start"] >= events[1]["stream_start_seconds"]
    tail = list(stream(driver, io.BytesIO(audio)))
    assert tail and tail[-1]["reason"] == "end_of_stream"
    assert word_error_rate(reference, " ".join(row["text"] for row in tail))["word_errors"] == 0
    forced = Endpoint(max_utterance_seconds=1, speech=lambda _: True)
    chunks = [forced.feed(bytes(FRAME_BYTES)) for _ in range(100)]
    bounded = [chunk for chunk in chunks if chunk]
    assert bounded and all(chunk.reason == "max_duration" for chunk in bounded)
    assert all(len(chunk.pcm) <= 32000 for chunk in bounded)
    silence_events = list(stream(driver, io.BytesIO(bytes(32000 * 10))))
    rng = np.random.default_rng(13)
    noise = np.clip(rng.normal(0, 0.01, 160000) * 32768, -32768, 32767).astype("<i2")
    noise_events = list(stream(driver, io.BytesIO(noise.tobytes())))
    assert not silence_events and not noise_events
    from faster_whisper.vad import get_vad_model

    normalized = np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768
    normalized = np.pad(normalized, (0, (-len(normalized)) % 512))
    batch = get_vad_model()(normalized) >= 0.5
    online = SileroStreamVAD()
    frames = np.clip(normalized * 32768, -32768, 32767).astype("<i2").tobytes()
    predictions = [online(frames[i : i + FRAME_BYTES]) for i in range(0, len(frames), FRAME_BYTES)]
    assert np.array_equal(batch.reshape(-1), predictions)
    report = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "hardware": hardware(),
        "platform": platform.platform(),
        "threads": driver.threads,
        "pause_ms": 1200,
        "profile": "fast",
        "feed_mode": "pre-recorded PCM fed as fast as possible; NOT real microphone capture",
        "wall_seconds_excluding_model_load": wall,
        "model_load_seconds": driver.load_seconds,
        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if sys.platform == "darwin" else 1024),
        "results": events,
        "quality": quality,
        "eof_flush": tail,
        "forced_max_duration_buffer_bound_passed": True,
        "silence_events": silence_events,
        "synthetic_noise_events": noise_events,
        "stateful_vad_matches_upstream_batch_frame_classifications": True,
        "warning": "JFK reuse and synthetic controls are regression checks, not general quality.",
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Dictation regressions passed: {args.output}")


if __name__ == "__main__":
    main()
