from __future__ import annotations

import http.client
import json
import threading
import unittest
from http.server import HTTPServer
from unittest.mock import Mock

import numpy as np

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
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                request_args(payload)


class HTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.synth = Mock()
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
            self.assertIsInstance(json.loads(response.read()), dict)
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
