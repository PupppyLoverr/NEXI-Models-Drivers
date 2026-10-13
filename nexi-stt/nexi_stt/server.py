from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .audio import MAX_BYTES
from .engine import Driver


def handler_for(driver: Driver) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "NEXI-STT/0.1"

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, format: str, *args: Any) -> None:
            # Never log transcripts, hints, request bodies, or URL query parameters.
            pass

        def respond(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path != "/health":
                self.respond(404, {"error": "Not found"})
                return
            self.respond(200, {"status": "ready", "offline": True, "device": "cpu"})

        def do_POST(self) -> None:
            url = urlsplit(self.path)
            if url.path != "/transcribe":
                self.respond(404, {"error": "Not found"})
                return
            if self.headers.get("Origin"):
                self.respond(403, {"error": "Browser-origin requests are not supported"})
                return
            if self.headers.get_content_type() not in ("audio/wav", "audio/x-wav"):
                self.respond(415, {"error": "Send raw audio/wav, not multipart or a file path"})
                return
            if self.headers.get("Transfer-Encoding"):
                self.respond(400, {"error": "Chunked requests are not supported"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BYTES:
                    self.respond(413, {"error": "Body must be >0 and <=10 MiB"})
                    return
                query = parse_qs(url.query, keep_blank_values=True)
                if set(query) - {"words", "vad"} or any(
                    values not in (["0"], ["1"]) for values in query.values()
                ):
                    raise ValueError("Only words=0|1 and vad=0|1 are supported")
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError("Truncated request body")
                result = driver.transcribe(
                    data,
                    hotwords=self.headers.get("X-STT-Hotwords", ""),
                    word_timestamps=query.get("words", ["0"])[0] == "1",
                    vad=query.get("vad", ["1"])[0] == "1",
                )
                self.respond(200, result)
            except (ValueError, TimeoutError) as exc:
                self.respond(400, {"error": str(exc)})
            except Exception:
                self.respond(500, {"error": "Local transcription failed"})

    return Handler


def serve(driver: Driver, port: int) -> None:
    if not 1 <= port <= 65535:
        raise ValueError("port must be 1–65535")
    # Deliberately single-request, loopback-only: bounded memory and no network exposure.
    with HTTPServer(("127.0.0.1", port), handler_for(driver)) as server:
        print(f"NEXI-STT ready on 127.0.0.1:{port}; Ctrl+C to stop", file=sys.stderr)
        server.serve_forever()
