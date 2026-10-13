"""Real-model silence, empty-WAV, hint and loopback HTTP regressions; no downloads."""

from __future__ import annotations

import argparse
import http.client
import io
import json
import threading
import wave
from http.server import HTTPServer
from pathlib import Path

from nexi_stt.audio import inspect_wav, read_wav
from nexi_stt.engine import Driver
from nexi_stt.server import handler_for


def silence(frames: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0" * frames * 2)
    return output.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--wav", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    driver = Driver(args.model)
    report = {"silence_with_vad": driver.transcribe(silence(16000 * 10))}
    assert report["silence_with_vad"]["text"] == ""
    assert report["silence_with_vad"]["segments"] == []
    try:
        inspect_wav(silence(0))
    except ValueError as error:
        report["empty_wav_rejected"] = str(error)
    else:
        raise AssertionError("Empty WAV must be rejected")
    audio = read_wav(args.wav)
    hints = driver.transcribe(audio, hotwords="Americans country", word_timestamps=True)
    assert hints["segments"] and hints["segments"][0]["words"]
    report["vocabulary_hints"] = hints
    server = HTTPServer(("127.0.0.1", 0), handler_for(driver))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection(*server.server_address, timeout=30)
        connection.request(
            "POST",
            "/transcribe?words=1&profile=balanced&vad_silence_ms=500",
            body=audio,
            headers={"Content-Type": "audio/wav"},
        )
        response = connection.getresponse()
        assert response.status == 200
        result = json.loads(response.read())
        assert result["text"] and result["segments"][0]["words"]
        report["real_http_transcription"] = result
        connection.close()
        connection = http.client.HTTPConnection(*server.server_address, timeout=30)
        connection.request(
            "POST", "/transcribe", body=b"invalid", headers={"Content-Type": "audio/wav"}
        )
        response = connection.getresponse()
        assert response.status == 400
        report["invalid_http_audio_rejected"] = json.loads(response.read())
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Real-model regressions passed: {args.output}")


if __name__ == "__main__":
    main()
