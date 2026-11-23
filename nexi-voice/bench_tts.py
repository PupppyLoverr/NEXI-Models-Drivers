"""Benchmark Pocket TTS: load time, peak RSS, RTF, time-to-first-audio, chunks.

Run inside a fresh process so RSS numbers are honest:
    python -m common.bench.measure --json results/tts_pocket.json -- \
        .venv/bin/python nexi-voice/bench_tts.py --variant default
"""
import argparse
import json
import time
from pathlib import Path

TEXT = ("Hi, this is NEXI. I'm a fully local voice running on your device, "
        "in real time, while you talk to me on a call.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="english",
                    help="pocket-tts config name, e.g. english_2m_2026-10")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    from pocket_tts import TTSModel  # noqa — import cost is part of load time

    t0 = time.time()
    model = TTSModel.load_model(language=a.variant)
    load_s = time.time() - t0
    sr = model.sample_rate
    from pocket_tts.default_parameters import get_default_voice_for_language
    voice = get_default_voice_for_language("en")
    state = model.get_state_for_audio_prompt(voice)

    results = {"variant": a.variant, "voice": voice,
               "load_seconds": round(load_s, 2),
               "sample_rate": sr, "runs": []}
    for i in range(a.reps):
        t_first, t_end, samples = None, None, 0
        t0 = time.time()
        it = model.generate_audio_stream(state, text_to_generate=TEXT)
        for chunk in it:
            if t_first is None:
                t_first = time.time() - t0
            samples += chunk.numel()
            t_end = time.time() - t0
        audio_s = samples / sr
        results["runs"].append({
            "ttfa_ms": round((t_first or 0) * 1000, 1),
            "wall_s": round(t_end, 2),
            "audio_s": round(audio_s, 2),
            "rtf": round(t_end / audio_s, 3),
        })
    print(json.dumps(results))
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
