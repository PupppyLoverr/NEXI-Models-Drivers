"""nexi-voice loopback HTTP server: streaming /speak and /transcribe.

Designed for the calling use case: PCM/WAV chunks over chunked HTTP, plus a
VAD-driven transcribe endpoint that emits partial transcripts as they land.

    python -m nexi_voice.server --tts-engine pocket --stt-engine fw-tiny \
        --host 127.0.0.1 --port 7860
"""
import argparse
import io
import json
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import stt as stt_mod
from . import tts as tts_mod
from . import vad


def wav_bytes(pcm_f32, sr: int) -> bytes:
    import numpy as np
    if not isinstance(pcm_f32, np.ndarray):
        pcm_f32 = pcm_f32.detach().cpu().numpy()  # torch Tensor from TTS
    pcm_f32 = np.asarray(pcm_f32, dtype="float32").reshape(-1)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((pcm_f32 * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def make_handler(engines):
    class H(BaseHTTPRequestHandler):
        def _json(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self._json(200, {"ok": True,
                                 "tts": engines["tts_name"],
                                 "stt": engines["stt_name"]})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            if self.path == "/speak":
                text = self.rfile.read(
                    int(self.headers["Content-Length"])).decode()
                # Stream: send headers, then chunked WAV segments.
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                sr = engines["tts"].sample_rate
                for chunk in engines["tts"].speak_stream(text):
                    data = wav_bytes(chunk, sr)
                    self.wfile.write(f"{len(data):x}\r\n".encode()
                                     + data + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            elif self.path == "/transcribe":
                audio = self.rfile.read(int(self.headers["Content-Length"]))
                parts = engines["stt"].transcribe_wav_bytes(audio)
                self._json(200, {"partials": parts,
                                 "final": parts[-1] if parts else ""})
            elif self.path == "/transcribe/stream":
                # VAD-segmented partials over chunked JSON-lines.
                audio = self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                for seg in vad.segment_wav_bytes(audio):
                    text = engines["stt"].transcribe_pcm(seg["pcm"], seg["sr"])
                    line = (json.dumps({"t": seg["t"], "text": text}) + "\n").encode()
                    self.wfile.write(f"{len(line):x}\r\n".encode() + line + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            else:
                self._json(404, {"error": "not found"})

        def log_message(self, *a):  # quiet
            pass

    return H


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tts-engine", default="pocket")
    ap.add_argument("--stt-engine", default="moon-base")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7860)
    a = ap.parse_args()
    engines = {
        "tts": tts_mod.load_engine(a.tts_engine),
        "tts_name": a.tts_engine,
        "stt": stt_mod.load_engine(a.stt_engine),
        "stt_name": a.stt_engine,
    }
    print(f"nexi-voice on http://{a.host}:{a.port} "
          f"(tts={a.tts_engine} stt={a.stt_engine})")
    ThreadingHTTPServer((a.host, a.port), make_handler(engines)).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
