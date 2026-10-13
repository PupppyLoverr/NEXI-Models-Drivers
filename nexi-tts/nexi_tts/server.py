"""Sequential, loopback-only WAV API. No authentication or public deployment."""

from __future__ import annotations

import json
import math
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from .driver import SAMPLE_RATE, Synthesizer, wav_bytes

MAX_BODY_BYTES = 32768
MAX_HTTP_TEXT_CHARS = 2000


def request_args(payload: Any) -> tuple[str, str, str, float]:
    if not isinstance(payload, dict) or set(payload) - {"text", "voice", "language", "speed"}:
        raise ValueError("Expected JSON object with text, voice, language and speed only")
    text = payload.get("text")
    voice = payload.get("voice", "Jasper")
    language = payload.get("language", "en")
    speed = payload.get("speed", 1.0)
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_HTTP_TEXT_CHARS:
        raise ValueError(
            f"text must be a nonempty string of at most {MAX_HTTP_TEXT_CHARS} characters"
        )
    if not isinstance(voice, str) or not isinstance(language, str):
        raise ValueError("voice and language must be strings")
    if isinstance(speed, bool) or not isinstance(speed, int | float) or not math.isfinite(speed):
        raise ValueError("speed must be a finite number")
    return text, voice, language, float(speed)


def handler_for(synth: Synthesizer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(15)

        def respond(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def json_response(self, status: int, payload: dict[str, Any]) -> None:
            self.respond(status, json.dumps(payload).encode(), "application/json")

        def do_GET(self) -> None:
            if self.path == "/health":
                self.json_response(200, {"status": "ok", "local": True})
            elif self.path == "/voices":
                self.json_response(
                    200, {"voices": synth.voices, "languages": ["en"], "sample_rate": SAMPLE_RATE}
                )
            else:
                self.json_response(404, {"error": "Use /health, /voices, or POST /synthesize"})

        def do_POST(self) -> None:
            if self.path != "/synthesize":
                self.json_response(404, {"error": "Unknown endpoint"})
                return
            if self.headers.get_content_type() != "application/json":
                self.json_response(415, {"error": "Content-Type must be application/json"})
                return
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError("Chunked requests are not supported")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_BODY_BYTES:
                    self.json_response(413, {"error": f"Body must be 1-{MAX_BODY_BYTES} bytes"})
                    return
                payload = json.loads(self.rfile.read(size))
                text, voice, language, speed = request_args(payload)
                audio = synth.synthesize(text, voice=voice, language=language, speed=speed)
                self.respond(200, wav_bytes(audio), "audio/wav")
            except (ValueError, UnicodeError) as error:
                self.json_response(400, {"error": str(error)})
            except OSError:
                self.close_connection = True
            except RuntimeError:
                self.json_response(500, {"error": "Local synthesis failed"})

        def log_message(self, format: str, *args: Any) -> None:
            # Avoid putting user text or malformed request URLs in server logs.
            pass

    return Handler


def serve(model_dir: Path, threads: int, port: int) -> None:
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    synth = Synthesizer(model_dir, threads)
    with HTTPServer(("127.0.0.1", port), handler_for(synth)) as server:
        print(
            f"Local TTS ready on 127.0.0.1:{port}; sequential requests, no public authentication",
            file=sys.stderr,
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
