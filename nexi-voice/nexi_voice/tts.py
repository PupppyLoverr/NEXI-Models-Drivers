"""TTS engine adapters. Each engine yields float32 PCM chunks via speak_stream.
"""
from __future__ import annotations


class PocketTTS:
    """Kyutai Pocket TTS (pip: pocket-tts>=4). Streaming chunk API."""
    sample_rate = 24000

    def __init__(self, variant: str = "english_18m_2026-10",
                 voice: str | None = None):
        from pocket_tts import TTSModel
        from pocket_tts.default_parameters import (
            get_default_voice_for_language)
        self._model = TTSModel.load_model(language=variant)
        self.sample_rate = self._model.sample_rate
        self._state = self._model.get_state_for_audio_prompt(
            voice or get_default_voice_for_language("en"))

    def speak_stream(self, text: str):
        for chunk in self._model.generate_audio_stream(
                self._state, text_to_generate=text):
            yield chunk


class KokoroTTS:
    """Kokoro-82M (pip: kokoro) — fallback/reference engine."""
    sample_rate = 24000

    def __init__(self):
        from kokoro import KPipeline
        self._pipe = KPipeline(lang_code="a")

    def speak_stream(self, text: str):
        for _gs, _ps, audio in self._pipe(text, voice="af_heart", speed=1.0):
            yield audio


ENGINES = {"pocket": PocketTTS,
           "pocket-2m": lambda: PocketTTS("english_2m_2026-10"),
           "pocket-7m": lambda: PocketTTS("english_7m_2026-10"),
           "pocket-flagship": lambda: PocketTTS("english_2026-10"),
           "kokoro": KokoroTTS}


def load_engine(name: str):
    return ENGINES[name]()
