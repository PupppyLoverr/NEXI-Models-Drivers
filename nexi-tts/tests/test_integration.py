"""Opt-in real CPU inference checks; never download models, deny Python networking."""

from __future__ import annotations

import hashlib
import json
import os
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

from nexi_tts.benchmark import deny_network, hardware, peak_rss_bytes
from nexi_tts.driver import SAMPLE_RATE, Synthesizer, wav_bytes


@unittest.skipUnless(os.environ.get("NEXI_TTS_INTEGRATION") == "1", "opt-in local models needed")
class RealInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.guard = patch("socket.socket", deny_network)
        cls.connections = patch("socket.create_connection", deny_network)
        cls.guard.start()
        cls.connections.start()
        cls.addClassCleanup(cls.guard.stop)
        cls.addClassCleanup(cls.connections.stop)
        cls.synth = Synthesizer(threads=2)

    def test_all_voices_and_speed_offline(self) -> None:
        output_dir = Path("results/integration")
        output_dir.mkdir(parents=True, exist_ok=True)
        evidence: dict[str, object] = {"hardware": hardware(), "python_network_guard": True}
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
