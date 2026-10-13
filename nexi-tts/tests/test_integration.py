"""Opt-in real CPU inference checks; never download models, deny Python networking."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import threading
import time
import unittest
import wave
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch

import numpy as np

from nexi_tts.benchmark import deny_network, hardware, peak_rss_bytes
from nexi_tts.driver import SAMPLE_RATE, Synthesizer, wav_bytes
from nexi_tts.server import handler_for
from nexi_tts.text import normalize


@unittest.skipUnless(os.environ.get("NEXI_TTS_INTEGRATION") == "1", "opt-in local models needed")
class RealInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.original_socket = socket.socket
        cls.original_connect = socket.create_connection
        cls.guard = patch("socket.socket", deny_network)
        cls.connections = patch("socket.create_connection", deny_network)
        cls.guard.start()
        cls.connections.start()
        cls.addClassCleanup(cls.guard.stop)
        cls.addClassCleanup(cls.connections.stop)
        cls.profile = os.environ.get("NEXI_TTS_PROFILE", "nano")
        cls.synth = Synthesizer(threads=2, profile=cls.profile)

    def test_all_voices_and_speed_offline(self) -> None:
        output_dir = Path(os.environ.get("NEXI_TTS_OUTPUT_DIR", "results/integration"))
        output_dir.mkdir(parents=True, exist_ok=True)
        evidence: dict[str, object] = {
            "hardware": hardware(),
            "python_network_guard": True,
            "profile": self.profile,
            "chunk_chars": self.synth.chunk_chars,
        }
        runs: list[dict[str, object]] = []
        durations: dict[float, float] = {}
        for voice, speed in [(name, 1.0) for name in self.synth.voices] + [
            ("Jasper", 0.75),
            ("Jasper", 1.25),
        ]:
            with self.subTest(voice=voice, speed=speed):
                started = time.perf_counter()
                audio = self.synth.synthesize(
                    "The quick brown fox jumps over the lazy dog.", voice=voice, speed=speed
                )
                elapsed = time.perf_counter() - started
                self.assertTrue(np.isfinite(audio).all())
                self.assertGreater(audio.size, SAMPLE_RATE)
                self.assertLessEqual(float(np.max(np.abs(audio))), 1.0)
                path = output_dir / f"{voice}-{speed}.wav"
                raw = wav_bytes(audio)
                path.write_bytes(raw)
                with wave.open(str(path), "rb") as wav:
                    self.assertEqual(wav.getnframes(), audio.size)
                    self.assertEqual(wav.getframerate(), SAMPLE_RATE)
                    self.assertEqual(wav.getsampwidth(), 2)
                runs.append(
                    {
                        "voice": voice,
                        "speed": speed,
                        "audio_seconds": audio.size / SAMPLE_RATE,
                        "synthesis_seconds": elapsed,
                        "waveform_peak": float(np.max(np.abs(audio))),
                        "clipped_samples": int(np.count_nonzero(np.abs(audio) > 1)),
                        "wav_file": path.name,
                        "wav_bytes": len(raw),
                        "wav_sha256": hashlib.sha256(raw).hexdigest(),
                    }
                )
                if voice == "Jasper":
                    durations[speed] = audio.size / SAMPLE_RATE
        evidence["runs"] = runs
        evidence["process_peak_rss_bytes"] = peak_rss_bytes()
        (output_dir / "smoke.json").write_text(json.dumps(evidence, indent=2) + "\n")
        self.assertGreater(durations[0.75], durations[1.0])
        self.assertGreater(durations[1.0], durations[1.25])

    def test_normalized_challenges_and_low_latency_chunks(self) -> None:
        text = (
            "Dr. Smith saved $12.50 on her 21st order, a discount of 12.5%. "
            "The package weighs 2.5kg and contains 1.20 liters of water. "
            "Every sample you hear is generated locally, without a cloud service."
        )
        self.assertIn("twelve dollars and fifty cents", normalize(text))
        self.assertIn("twenty-first", normalize(text))
        chunks = list(self.synth.iter_audio(text, first_chunk_chars=80))
        self.assertGreater(len(chunks), 1)
        for audio in chunks:
            self.assertTrue(np.isfinite(audio).all())
            self.assertGreater(audio.size, 0)
            self.assertLessEqual(float(np.max(np.abs(audio))), 1.0)

    def test_model_is_cpu_only(self) -> None:
        self.assertEqual(self.synth.session.get_providers(), ["CPUExecutionProvider"])

    def test_real_loopback_stream_and_wav(self) -> None:
        output_dir = Path(os.environ.get("NEXI_TTS_OUTPUT_DIR", "results/integration"))
        output_dir.mkdir(parents=True, exist_ok=True)
        text = Path("tests/fixtures/everyday.txt").read_text(encoding="utf-8")
        results: list[dict[str, object]] = []
        # Loopback HTTP needs sockets; asset fetches remain prohibited in this check.
        with (
            patch("socket.socket", self.original_socket),
            patch("socket.create_connection", type(self).original_connect),
            patch("urllib.request.urlopen", side_effect=RuntimeError("Asset fetch forbidden")),
        ):
            server = HTTPServer(("127.0.0.1", 0), handler_for(self.synth))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for route in ("/synthesize", "/stream"):
                    client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=30)
                    try:
                        started = time.perf_counter()
                        client.request(
                            "POST",
                            route,
                            body=json.dumps({"text": text}),
                            headers={"Content-Type": "application/json"},
                        )
                        response = client.getresponse()
                        self.assertEqual(response.status, 200)
                        first = response.read(2)
                        first_byte_seconds = time.perf_counter() - started
                        body = first + response.read()
                        complete_seconds = time.perf_counter() - started
                        if route == "/stream":
                            self.assertEqual(response.getheader("X-Audio-Format"), "pcm_s16le")
                            self.assertEqual(len(body) % 2, 0)
                            audio = np.frombuffer(body, dtype="<i2").astype(np.float32) / 32767
                            self.assertGreater(audio.size, SAMPLE_RATE)
                            raw = wav_bytes(audio)
                            name = "http-stream.wav"
                        else:
                            self.assertEqual(response.getheader("Content-Type"), "audio/wav")
                            self.assertTrue(body.startswith(b"RIFF"))
                            raw = body
                            name = "http-full.wav"
                        (output_dir / name).write_bytes(raw)
                        results.append(
                            {
                                "route": route,
                                "time_to_first_body_bytes_seconds": first_byte_seconds,
                                "complete_seconds": complete_seconds,
                                "response_bytes": len(body),
                                "wav_file": name,
                                "wav_sha256": hashlib.sha256(raw).hexdigest(),
                            }
                        )
                    finally:
                        client.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
        (output_dir / "http.json").write_text(
            json.dumps(
                {
                    "profile": self.profile,
                    "chunk_chars": self.synth.chunk_chars,
                    "hardware": hardware(),
                    "text": text,
                    "asset_fetch_guard": True,
                    "python_socket_guard": False,
                    "note": "Loopback sockets allowed; resident model, sequential requests, one sample each",
                    "runs": results,
                },
                indent=2,
            )
            + "\n"
        )

    def test_z_measured_process_budget(self) -> None:
        self.assertLess(peak_rss_bytes(), 1_000_000_000)

    def test_invalid_requests_with_real_instance(self) -> None:
        for text, kwargs in [
            ("", {}),
            (" \n\t", {}),
            ("hello", {"language": "fr"}),
            ("hello", {"speed": float("nan")}),
            ("hello", {"speed": float("inf")}),
        ]:
            with self.subTest(text=text, kwargs=kwargs), self.assertRaises(ValueError):
                self.synth.synthesize(text, **kwargs)


if __name__ == "__main__":
    unittest.main()
