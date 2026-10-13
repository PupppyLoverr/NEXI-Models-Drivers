from __future__ import annotations

import http.client
import json
import threading
import unittest
from http.server import HTTPServer
from unittest.mock import Mock

import numpy as np

from nexi_tts.driver import pcm16
from nexi_tts.server import handler_for, request_args


class RequestTests(unittest.TestCase):
    def test_defaults(self) -> None:
        self.assertEqual(request_args({"text": "Hello"}), ("Hello", "Jasper", "en", 1.0))

    def test_invalid_payload(self) -> None:
        for payload in (
            None,
            [],
            "text",
            {},
            {"text": 1},
            {"text": ""},
            {"text": "x" * 2001},
            {"text": "hi", "output": "bad.wav"},
            {"text": "hi", "voice": 2},
            {"text": "hi", "language": 2},
            {"text": "hi", "speed": True},
            {"text": "hi", "speed": "1"},
            {"text": "hi", "speed": float("nan")},
            {"text": "hi", "speed": 10**400},
            {"text": "hi", "speed": 0.1},
            {"text": "hi", "speed": 3.0},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                request_args(payload)


class HTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.synth = Mock()
        self.synth.profile = "mini"
        self.synth.voices = ["Jasper"]
        self.synth.synthesize.return_value = np.zeros(2400, dtype=np.float32)
        self.server = HTTPServer(("127.0.0.1", 0), handler_for(self.synth))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)

    def tearDown(self) -> None:
        self.client.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_health_and_voices(self) -> None:
        for endpoint in ("/health", "/voices"):
            self.client.request("GET", endpoint)
            response = self.client.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["profile"], "mini")
        self.synth.synthesize.assert_not_called()

    def test_wav_response(self) -> None:
        self.client.request(
            "POST",
            "/synthesize",
            body='{"text":"Hello"}',
            headers={"Content-Type": "application/json"},
        )
        response = self.client.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "audio/wav")
        self.assertTrue(response.read().startswith(b"RIFF"))
        self.synth.synthesize.assert_called_once_with(
            "Hello", voice="Jasper", language="en", speed=1.0
        )

    def test_invalid_json(self) -> None:
        self.client.request(
            "POST", "/synthesize", body="not json", headers={"Content-Type": "application/json"}
        )
        response = self.client.getresponse()
        self.assertEqual(response.status, 400)
        response.read()
        self.synth.synthesize.assert_not_called()

    def test_stream_returns_pcm_before_synthesis_completes(self) -> None:
        release = threading.Event()
        audio = np.full(2400, 0.25, dtype=np.float32)

        def chunks():
            yield audio
            if not release.wait(5):
                raise RuntimeError("Client did not receive first chunk")
            yield audio

        self.synth.iter_audio.return_value = chunks()
        try:
            self.client.request(
                "POST",
                "/stream",
                body='{"text":"Hello"}',
                headers={"Content-Type": "application/json"},
            )
            response = self.client.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Transfer-Encoding"), "chunked")
            self.assertEqual(response.getheader("X-Audio-Format"), "pcm_s16le")
            self.assertEqual(response.getheader("X-Audio-Sample-Rate"), "24000")
            self.assertEqual(response.read(4800), pcm16(audio))
            release.set()
            self.assertEqual(response.read(), pcm16(audio))
        finally:
            release.set()
        self.synth.iter_audio.assert_called_once_with(
            "Hello", voice="Jasper", language="en", speed=1.0, first_chunk_chars=80
        )
        self.synth.synthesize.assert_not_called()

    def test_stream_validation_precedes_success_headers(self) -> None:
        self.synth.iter_audio.side_effect = ValueError("Unknown voice")
        self.client.request(
            "POST",
            "/stream",
            body='{"text":"Hello","voice":"unknown"}',
            headers={"Content-Type": "application/json"},
        )
        response = self.client.getresponse()
        self.assertEqual(response.status, 400)
        self.assertIn("Unknown voice", response.read().decode())

    def test_midstream_failure_is_detectably_incomplete(self) -> None:
        def chunks():
            yield np.zeros(2400, dtype=np.float32)
            raise RuntimeError("Model failed")

        self.synth.iter_audio.return_value = chunks()
        self.client.request(
            "POST",
            "/stream",
            body='{"text":"Hello"}',
            headers={"Content-Type": "application/json"},
        )
        response = self.client.getresponse()
        self.assertEqual(response.status, 200)
        with self.assertRaises(http.client.IncompleteRead):
            response.read()

    def test_size_limit(self) -> None:
        self.client.request(
            "POST", "/synthesize", body="x" * 32769, headers={"Content-Type": "application/json"}
        )
        response = self.client.getresponse()
        self.assertEqual(response.status, 413)
        response.read()
        self.synth.synthesize.assert_not_called()

    def test_wrong_media_type(self) -> None:
        self.client.request("POST", "/synthesize", body="text")
        response = self.client.getresponse()
        self.assertEqual(response.status, 415)
        response.read()

    def test_unknown_route(self) -> None:
        self.client.request("GET", "/missing")
        response = self.client.getresponse()
        self.assertEqual(response.status, 404)
        response.read()
