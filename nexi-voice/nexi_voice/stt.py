"""STT engine adapters. Each exposes transcribe_wav_bytes / transcribe_pcm.
"""
from __future__ import annotations

import io
from pathlib import Path


class FasterWhisperEngine:
    """faster-whisper baseline (tiny/base.en int8 on CPU)."""

    def __init__(self, size: str = "tiny.en"):
        from faster_whisper import WhisperModel
        self._m = WhisperModel(size, device="cpu", compute_type="int8")

    def transcribe_wav_bytes(self, data: bytes) -> list[str]:
        import soundfile as sf
        pcm, sr = sf.read(io.BytesIO(data), dtype="float32")
        if pcm.ndim > 1:
            pcm = pcm.mean(axis=1)
        if sr != 16000:  # whisper wants 16 kHz mono
            import numpy as np
            pcm = np.interp(np.arange(0, len(pcm), sr / 16000),
                            np.arange(len(pcm)), pcm).astype("float32")
        return [self.transcribe_pcm(pcm, 16000)]

    def transcribe_pcm(self, pcm, sr: int) -> str:
        segs, _ = self._m.transcribe(pcm, beam_size=1, vad_filter=False)
        return " ".join(s.text.strip() for s in segs)


class RumbleEngine:
    """Rumble-2-Flash (Reson8, 0.5B Qwen3-ASR, transformers-native)."""

    def __init__(self, model_id: str = "Reson8/Rumble-2-Flash"):
        import torch
        from transformers import AutoModelForMultimodalLM, AutoProcessor
        self._proc = AutoProcessor.from_pretrained(model_id)
        self._m = AutoModelForMultimodalLM.from_pretrained(
            model_id, dtype=torch.float32)  # CPU: keep fp32, avoid bf16/fp32 mix

    def transcribe_wav_bytes(self, data: bytes) -> list[str]:
        import soundfile as sf
        pcm, _ = sf.read(io.BytesIO(data), dtype="float32")
        return [self.transcribe_pcm(pcm, 16000)]

    def transcribe_pcm(self, pcm, sr: int) -> str:
        import torch
        inputs = self._proc.apply_transcription_request(
            audio=pcm, language="English")
        with torch.no_grad():
            out = self._m.generate(**inputs, max_new_tokens=512)
        gen = out[:, inputs["input_ids"].shape[-1]:]
        return self._proc.decode(gen, return_format="transcription_only")[0]


class MoonshineEngine:
    """Moonshine tiny/base int8 via sherpa-onnx (ONNX, CPU, chunked-streaming)."""

    def __init__(self, model_dir: str):
        import sherpa_onnx
        d = Path(model_dir)
        self._r = sherpa_onnx.OfflineRecognizer.from_moonshine(
            preprocessor=str(d / "preprocess.onnx"),
            encoder=str(d / "encode.int8.onnx"),
            uncached_decoder=str(d / "uncached_decode.int8.onnx"),
            cached_decoder=str(d / "cached_decode.int8.onnx"),
            tokens=str(d / "tokens.txt"),
            num_threads=8, provider="cpu")

    def transcribe_wav_bytes(self, data: bytes) -> list[str]:
        import soundfile as sf
        pcm, sr = sf.read(io.BytesIO(data), dtype="float32")
        return [self.transcribe_pcm(pcm, sr)]

    def transcribe_pcm(self, pcm, sr: int) -> str:
        if sr != 16000:
            import numpy as np
            pcm = np.interp(np.arange(0, len(pcm), sr / 16000),
                            np.arange(len(pcm)), pcm).astype("float32")
        s = self._r.create_stream()
        s.accept_waveform(16000, pcm)
        self._r.decode_stream(s)
        return s.result.text.strip()


class Asr4AllEngine:
    """FUTO asr4all-s (28M streaming) — loaded via onnxruntime if present."""
    MODEL_URL = ""  # pinned at release

    def __init__(self, model_dir: str = "models/asr4all-s"):
        raise NotImplementedError(
            "asr4all-s ONNX adapter pending — see nexi-voice/BENCHMARKS.md")


ENGINES = {"fw-tiny": lambda: FasterWhisperEngine("tiny.en"),
           "fw-base": lambda: FasterWhisperEngine("base.en"),
           "rumble": RumbleEngine,
           "asr4all": Asr4AllEngine,
           "moon-tiny": lambda: MoonshineEngine(_model_dir("moon-tiny")),
           "moon-base": lambda: MoonshineEngine(_model_dir("moon-base"))}


def _model_dir(name: str) -> str:
    return str(Path.home() / "models" / name)


def load_engine(name: str):
    return ENGINES[name]()
