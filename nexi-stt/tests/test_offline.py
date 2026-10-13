from __future__ import annotations

import hashlib
import http.client
import io
import json
import socket
import threading
import types
import wave
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest

from nexi_stt import assets
from nexi_stt.audio import MAX_BYTES, inspect_wav, read_wav
from nexi_stt.cli import main
from nexi_stt.dictation import FRAME_BYTES, Endpoint, stream
from nexi_stt.engine import Driver
from nexi_stt.metrics import word_error_rate
from nexi_stt.server import handler_for


def wav_data(*, rate: int = 16000, channels: int = 1, width: int = 2, frames: int = 160) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(b"\0" * frames * channels * width)
    return buffer.getvalue()


def local_model(directory: Path) -> Path:
    spec = {"upstream": "unit-test fixture", "files": []}
    for name in ("config.json", "model.bin", "tokenizer.json"):
        value = name.encode()
        (directory / name).write_bytes(value)
        spec["files"].append(
            {"name": name, "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
        )
    (directory / "nexi-assets.json").write_text(json.dumps(spec))
    return directory


def test_pcm_metadata_and_file(tmp_path: Path) -> None:
    data = wav_data(channels=2)
    info = inspect_wav(data)
    assert (info.sample_rate, info.channels, info.frames, info.seconds) == (16000, 2, 160, 0.01)
    path = tmp_path / "clip.wav"
    path.write_bytes(data)
    assert read_wav(path) == data


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not a WAV",
        wav_data(width=1),
        wav_data(channels=3),
        wav_data(rate=4000),
        wav_data(frames=0),
        wav_data(rate=8000, frames=960001),
        wav_data()[:-10],
        b"\0" * (MAX_BYTES + 1),
    ],
)
def test_reject_bad_wav(data: bytes) -> None:
    with pytest.raises(ValueError):
        inspect_wav(data)


def test_model_missing_does_not_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket.socket, "connect", Mock(side_effect=AssertionError("Network forbidden"))
    )
    with pytest.raises(ValueError, match="no auto-download"):
        Driver(tmp_path / "missing")


def test_manifest_checksum_and_paths(tmp_path: Path) -> None:
    model = local_model(tmp_path)
    assets.verify_model(model)
    (model / "model.bin").write_bytes(b"X" * len(b"model.bin"))
    with pytest.raises(ValueError, match="Checksum"):
        assets.verify_model(model)
    spec = {
        "files": [
            {"name": "../secret"},
            {"name": "model.bin"},
            {"name": "config.json"},
            {"name": "tokenizer.json"},
        ]
    }
    (model / "nexi-assets.json").write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="flat local"):
        assets.verify_model(model)


def test_download_atomic_and_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"trusted fixture"
    item = {
        "name": "model.bin",
        "bytes": len(payload),
        "url": "https://test.invalid/pinned",
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    monkeypatch.setattr(assets, "catalog", lambda: {"test": {"files": [item]}})
    request = Mock(return_value=io.BytesIO(payload))
    monkeypatch.setattr(assets.urllib.request, "urlopen", request)
    assets.download("test", tmp_path)
    assert (tmp_path / "model.bin").read_bytes() == payload
    assets.download("test", tmp_path)
    assert request.call_count == 1
    (tmp_path / "model.bin").unlink()
    request.return_value = io.BytesIO(b"bad")
    with pytest.raises(ValueError, match="checksum/size"):
        assets.download("test", tmp_path)
    assert not (tmp_path / "model.bin").exists()
    assert not list(tmp_path.glob(".download-*"))


def test_catalog_immutable_assets() -> None:
    for spec in assets.catalog().values():
        assert len(spec["revision"]) == 40
        for item in spec["files"]:
            assert spec["revision"] in item["url"]
            assert item["url"].startswith("https://")
            assert len(item["sha256"]) == 64
            assert item["bytes"] > 0


def test_driver_exhausts_generator_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = Mock()
    word = types.SimpleNamespace(start=0.0, end=0.01, word=" hello", probability=0.9)
    segment = types.SimpleNamespace(
        start=0.0, end=0.01, text=" hello ", no_speech_prob=0.1, words=[word]
    )
    fake.transcribe.return_value = (
        iter([segment]),
        types.SimpleNamespace(language="en", duration_after_vad=0.01),
    )
    constructor = Mock(return_value=fake)
    monkeypatch.setitem(
        __import__("sys").modules, "faster_whisper", types.SimpleNamespace(WhisperModel=constructor)
    )
    driver = Driver(local_model(tmp_path), threads=2)
    result = driver.transcribe(wav_data(), hotwords="NEXI", word_timestamps=True)
    assert result["text"] == "hello"
    assert result["segments"][0]["words"][0]["text"] == " hello"
    assert constructor.call_args.kwargs["local_files_only"] is True
    assert constructor.call_args.kwargs["device"] == "cpu"
    assert fake.transcribe.call_args.kwargs["hotwords"] == "NEXI"
    assert fake.transcribe.call_args.kwargs["beam_size"] == 1
    assert fake.transcribe.call_args.kwargs["vad_parameters"] == {"min_silence_duration_ms": 2000}
    assert __import__("os").environ["HF_HUB_OFFLINE"] == "1"
    for hotwords in ("X" * 401, "a\nb"):
        with pytest.raises(ValueError, match="Vocabulary"):
            driver.transcribe(wav_data(), hotwords=hotwords)
    assert driver.transcribe(wav_data(), profile="balanced")["config"]["beam_size"] == 5
    assert fake.transcribe.call_args.kwargs["beam_size"] == 5
    for options in ({"profile": "unsafe"}, {"vad_silence_ms": 99}):
        with pytest.raises(ValueError):
            driver.transcribe(wav_data(), **options)


def test_pause_endpointer_preserves_absolute_times_and_splits() -> None:
    patterns = [False] * 10 + [True] * 5 + [False] * 19 + [False] * 10 + [True] * 5
    endpoint = Endpoint(pause_ms=600, speech=lambda _: patterns.pop(0))
    results = []
    for _ in range(49):
        result = endpoint.feed(b"\0" * FRAME_BYTES)
        if result:
            results.append(result)
    results.append(endpoint.flush())
    assert [(row.start_frame, row.end_frame, row.reason) for row in results] == [
        (0, 34, "pause"),
        (34, 49, "end_of_stream"),
    ]
    assert all(len(row.pcm) == (row.end_frame - row.start_frame) * FRAME_BYTES for row in results)


def test_stream_json_events_adjust_segment_and_word_times() -> None:
    patterns = [False] * 20 + [True] * 5 + [False] * 19 + [False] * 10 + [True] * 5
    endpoint = Endpoint(pause_ms=600, speech=lambda _: patterns.pop(0))
    row = {
        "text": "hello",
        "segments": [{"start": 0.01, "end": 0.5, "words": [{"start": 0.02, "end": 0.3}]}],
    }
    driver = Mock()
    driver.transcribe.side_effect = lambda *args, **kwargs: json.loads(json.dumps(row))

    class ShortReads(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            return super().read(min(size, 311))

    result = list(stream(driver, ShortReads(b"\0" * FRAME_BYTES * 59), endpoint=endpoint))
    assert len(result) == 2
    assert result[0]["event"] == "final" and result[0]["reason"] == "pause"
    assert result[1]["reason"] == "end_of_stream"
    assert result[1]["stream_start_seconds"] == pytest.approx(44 * 0.032)
    assert result[1]["segments"][0]["start"] == pytest.approx(44 * 0.032 + 0.01)
    assert result[1]["segments"][0]["words"][0]["start"] == pytest.approx(44 * 0.032 + 0.02)
    assert all(call.kwargs["vad"] is False for call in driver.transcribe.call_args_list)


def test_stream_bounds_and_incomplete_sample() -> None:
    for options in ({"pause_ms": 100}, {"max_utterance_seconds": 31}):
        with pytest.raises(ValueError):
            Endpoint(**options)
    endpoint = Endpoint(speech=lambda _: False)
    with pytest.raises(ValueError, match="incomplete sample"):
        list(stream(Mock(), io.BytesIO(b"\0" * FRAME_BYTES + b"x"), endpoint=endpoint))
    assert list(stream(Mock(), io.BytesIO(b"\0" * FRAME_BYTES), endpoint=endpoint)) == []


def test_endpoint_max_duration_and_partial_final_frame() -> None:
    endpoint = Endpoint(max_utterance_seconds=1, speech=lambda _: True)
    chunks = [endpoint.feed(bytes(FRAME_BYTES)) for _ in range(100)]
    chunks = [chunk for chunk in chunks if chunk]
    assert len(chunks) == 3
    assert all(chunk.reason == "max_duration" and len(chunk.pcm) <= 32000 for chunk in chunks)
    driver = Mock()
    driver.transcribe.return_value = {"text": "tail", "segments": []}
    events = list(
        stream(driver, io.BytesIO(b"\x01\0" * 55), endpoint=Endpoint(speech=lambda _: True))
    )
    assert events[0]["reason"] == "end_of_stream"
    assert events[0]["stream_start_seconds"] == 0
    assert events[0]["stream_end_seconds"] == 0.032


@pytest.mark.parametrize("threads", [0, -1, 65])
def test_thread_bounds(tmp_path: Path, threads: int) -> None:
    with pytest.raises(ValueError, match="threads"):
        Driver(tmp_path, threads=threads)


def test_cli_invalid_audio_before_model(tmp_path: Path) -> None:
    path = tmp_path / "bad.wav"
    path.write_bytes(b"invalid")
    assert main(["transcribe", str(path), "--model", str(tmp_path / "missing")]) == 2


def test_wer() -> None:
    assert word_error_rate("And so, my fellow Americans!", "and so my fellow americans")["wer"] == 0
    result = word_error_rate("one two three", "one four three five")
    assert result["word_errors"] == 2
    assert result["wer"] == pytest.approx(2 / 3)
    assert word_error_rate("one two three", "one three")["word_errors"] == 1
    with pytest.raises(ValueError):
        word_error_rate("", "anything")


def test_http_contract_and_boundaries() -> None:
    driver = Mock()
    driver.transcribe.return_value = {"text": "hello", "segments": []}
    server = HTTPServer(("127.0.0.1", 0), handler_for(driver))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(
        method: str, path: str, body: bytes = b"", headers: dict[str, str] | None = None
    ) -> tuple[int, dict]:
        connection = http.client.HTTPConnection(*server.server_address, timeout=3)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.getheader("Cache-Control") == "no-store"
        connection.close()
        return response.status, payload

    try:
        assert request("GET", "/health")[0] == 200
        assert request("GET", "/missing")[0] == 404
        assert request("POST", "/transcribe", b"data")[0] == 415
        assert (
            request(
                "POST",
                "/transcribe",
                b"data",
                {"Content-Type": "audio/wav", "Origin": "https://evil.invalid"},
            )[0]
            == 403
        )
        assert request("POST", "/transcribe", b"", {"Content-Type": "audio/wav"})[0] == 413
        for query in (
            "words=yes",
            "words=",
            "vad=",
            "unknown=",
            "vad=1&vad=1",
            "profile=",
            "profile=none",
            "vad_silence_ms=",
            "vad_silence_ms=99",
        ):
            assert (
                request("POST", f"/transcribe?{query}", wav_data(), {"Content-Type": "audio/wav"})[
                    0
                ]
                == 400
            )
        status, payload = request(
            "POST",
            "/transcribe?words=1&vad=0&profile=balanced&vad_silence_ms=500",
            wav_data(),
            {"Content-Type": "audio/wav", "X-STT-Hotwords": "NEXI"},
        )
        assert status == 200 and payload["text"] == "hello"
        assert driver.transcribe.call_args.kwargs == {
            "hotwords": "NEXI",
            "word_timestamps": True,
            "vad": False,
            "profile": "balanced",
            "vad_silence_ms": 500,
        }
        driver.transcribe.side_effect = ValueError("Invalid WAV")
        assert request("POST", "/transcribe", wav_data(), {"Content-Type": "audio/wav"})[0] == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
