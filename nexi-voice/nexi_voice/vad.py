"""Energy-based VAD segmentation for the calling path.

Cheap and dependency-free: frames the PCM, marks speech frames by RMS energy
above an adaptive threshold, and emits segments with >= min_silence gaps.
Upgrade path: silero-vad ONNX when quality demands it.
"""
from __future__ import annotations

import io
import wave

import numpy as np

FRAME_MS = 30
MIN_SILENCE_MS = 400
MIN_SPEECH_MS = 200


def _wav_to_pcm(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data), "rb") as w:
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32767
    return pcm, sr


def segment_wav_bytes(data: bytes) -> list[dict]:
    pcm, sr = _wav_to_pcm(data)
    frame = int(sr * FRAME_MS / 1000)
    min_sil = int(MIN_SILENCE_MS / FRAME_MS)
    min_sp = int(MIN_SPEECH_MS / FRAME_MS)
    if len(pcm) < frame:
        return [{"t": 0.0, "pcm": pcm, "sr": sr}]
    rms = np.sqrt(np.convolve(pcm ** 2, np.ones(frame) / frame, mode="same"))
    thr = max(rms.max() * 0.15, 0.005)
    speech = rms[::frame] > thr
    # merge into segments
    segs, start, sil = [], None, 0
    for i, s in enumerate(speech):
        if s and start is None:
            start = i
            sil = 0
        elif s:
            sil = 0
        elif start is not None:
            sil += 1
            if sil >= min_sil:
                if i - sil - start >= min_sp:
                    segs.append((start, i - sil))
                start, sil = None, 0
    if start is not None:
        segs.append((start, len(speech)))
    return [{"t": s * FRAME_MS / 1000,
             "pcm": pcm[s * frame: e * frame], "sr": sr}
            for s, e in segs]
