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




class KittenTTS2:
    """Kitten TTS 2 Mini (KittenML, apache-2.0): 82M params, 82.7 MB int8 ONNX,
    16 languages, 118 voices. Run in the voice venv (torchaudio-free).
    NOTE: kittenml's frontend uses a torch BART g2p fallback, so peak RSS is
    ~0.86 GB on CPU even though the synthesizer itself is tiny. RTF measured
    0.72-0.91 steady-state (first utterance slower: BART warmup)."""
    sample_rate = 24000

    def __init__(self, voice: str = "Eleanor"):
        from kittenml import KittenTTS as _K
        self._m = _K("KittenML/kitten-tts-2-mini", backend="onnx")
        self._voice = voice

    def speak_stream(self, text: str):
        yield self._m.generate(text, voice=self._voice)

ENGINES = {"pocket": PocketTTS,
           "pocket-2m": lambda: PocketTTS("english_2m_2026-10"),
           "pocket-7m": lambda: PocketTTS("english_7m_2026-10"),
           "pocket-flagship": lambda: PocketTTS("english_2026-10"),
           "kokoro": KokoroTTS,
           "kitten": KittenTTS2}


def load_engine(name: str):
    return ENGINES[name]()
