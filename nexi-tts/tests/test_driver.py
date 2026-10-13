from __future__ import annotations

import io
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

from nexi_tts.driver import SAMPLE_RATE, Synthesizer, pcm16, wav_bytes


class DriverTests(unittest.TestCase):
    def test_wav_format(self) -> None:
        body = wav_bytes(np.zeros(SAMPLE_RATE, dtype=np.float32))
        with wave.open(io.BytesIO(body), "rb") as audio:
            self.assertEqual(audio.getnchannels(), 1)
            self.assertEqual(audio.getsampwidth(), 2)
            self.assertEqual(audio.getframerate(), SAMPLE_RATE)
            self.assertEqual(audio.getnframes(), SAMPLE_RATE)

    def test_pcm_clamps_without_integer_overflow(self) -> None:
        raw = pcm16(np.array([-2, -1, 0, 1, 2], dtype=np.float32))
        self.assertEqual(
            np.frombuffer(raw, dtype="<i2").tolist(), [-32767, -32767, 0, 32767, 32767]
        )

    def test_invalid_audio(self) -> None:
        for array in (
            np.array([], dtype=np.float32),
            np.array([np.nan], dtype=np.float32),
            np.zeros((1, 1), dtype=np.float32),
        ):
            with self.subTest(array=array), self.assertRaises(ValueError):
                pcm16(array)

    def test_invalid_threads_before_assets(self) -> None:
        for threads in (0, 9, True, 1.5):
            with self.subTest(threads=threads), self.assertRaises(ValueError):
                Synthesizer(threads=threads)

    def test_missing_model_is_local_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("urllib.request.urlopen") as network:
            with self.assertRaises(ValueError):
                Synthesizer(Path(directory))
            network.assert_not_called()

    def test_invalid_parameters_before_inference(self) -> None:
        synth = Synthesizer.__new__(Synthesizer)
        synth.voice_aliases = {"Jasper": "voice"}
        for kwargs in (
            {"language": "fr"},
            {"voice": "Unknown"},
            {"speed": float("nan")},
            {"speed": float("inf")},
            {"speed": True},
            {"speed": 0.1},
            {"speed": 3},
            {"speed": 10**400},
            {"speed": "fast"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                list(synth.iter_audio("hello", **kwargs))

    def test_to_file_atomic_on_failure(self) -> None:
        synth = Synthesizer.__new__(Synthesizer)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(synth, "iter_audio", side_effect=ValueError("bad")),
        ):
            output = Path(directory) / "voice.wav"
            output.write_bytes(b"original")
            with self.assertRaises(ValueError):
                synth.to_file("text", output)
            self.assertEqual(output.read_bytes(), b"original")
            self.assertFalse(list(Path(directory).glob("*.part")))
