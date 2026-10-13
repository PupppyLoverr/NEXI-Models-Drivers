# NEXI TTS — tiny local CPU voice driver

Runnable text → WAV with two pinned **upstream Kitten TTS 0.8** profiles:
**Nano int8** (15M parameters, 27,650,302 asset bytes) for the smallest footprint,
and **Mini** (80M, 81,548,122 asset bytes) for quality-first use. No cloud inference,
GPU, spaCy or PyTorch. This is **not a fine-tune**; the upstream ONNX family has no released
training pipeline. See NOTICE for the pinned 0.8 frontend contract.

Original Nano baseline on Linux x86-64 / Xeon 8559C with two ONNX threads: **345 MB peak RSS**
for a 10.15-second utterance, **349 MB** for an 81.2-second utterance;
approximately **0.21–0.23 real-time factor**. These are complete process peaks,
not weight sizes. See [BENCHMARKS.md](BENCHMARKS.md) and the committed JSON.
All eight presets generated real audio with Python networking blocked.

Nano remains the compatible default. Upstream calls Mini its highest-quality
ONNX model; that is a **published claim**, not our listener ranking. Neither a
category-wide #1 result nor ElevenLabs-quality parity has been established.
On a longer, same-text CPU stress test with the current 128-character bound,
Nano peaked at **485 MB** and Mini at **741 MB** complete-process RSS. At an
80-character first chunk, they peaked at **446 MB** and **712 MB**, respectively.
Mini uses about twice as much synthesis time per second of generated audio.
See [BENCHMARKS.md](BENCHMARKS.md) for paired timings and evidence.

## Quick start (Linux, Python 3.10–3.12)

```bash
cd nexi-tts
./setup.sh
.venv/bin/python -m nexi_tts download
.venv/bin/python -m nexi_tts verify
.venv/bin/python -m nexi_tts speak \
  --text "Hello. This voice runs entirely on your device." \
  --voice Jasper --language en --speed 1 --threads 2 --output hello.wav
```

Quality profile (separate, explicit download):

```bash
.venv/bin/python -m nexi_tts download --profile mini
.venv/bin/python -m nexi_tts speak --profile mini \
  --text 'Dr. Smith saved $12.50 on her 21st order.' --voice Bella --output quality.wav
```

In a shell, single-quote text containing dollar signs so the shell does not
expand them: `--text 'Dr. Smith saved $12.50 on her 21st order.'`.
Use `--profile nano` or `--profile mini` on every command. Profiles have separate
verified asset directories. Mini is pinned to revision
`c02725660cea441db4c383af69f1f26f5cd00947`; no automatic fallback/download occurs.

Setup requires network; `download` is the only explicit model-network command.
Assets are pinned to Hugging Face revision
`84781d74e29ee25217551556398b42f80593a813` with SHA-256/size verification.
Inference never downloads missing assets. `--model-dir PATH` is available on
every command; `--text-file PATH` accepts UTF-8 text for `speak`.
The output's parent directory must already exist. `setup.sh` can use
`PYTHON=python3.12` and `VENV_DIR=.venv-runtime`; a clean runtime-only install was
tested separately from the development environment.

Built-in voices: Bella, Jasper, Luna, Bruno, Rosie, Hugo, Kiki, Leo.
Languages: English only (`en` or `en-us`). Output: 24 kHz mono PCM16 WAV.
Speed: 0.5–2.0. Nano multiplies its stored voice-specific speed prior;
Mini has no speed priors in its config and uses a neutral multiplier of 1.0.

## Python API

From this folder:

```python
from nexi_tts.driver import Synthesizer

tts = Synthesizer(threads=2)
tts.to_file("Hello, locally.", "hello.wav", voice="Bella", language="en", speed=1)
audio = tts.synthesize("An in-memory float32 mono waveform.")
for chunk in tts.iter_audio("Sentence chunks are yielded incrementally."):
    pass  # send float32 samples to your own playback device
```

Select the quality profile with `Synthesizer(profile="mini", threads=2)`.
For faster first audio from a long response, use
`tts.iter_audio(text, first_chunk_chars=80)`. Only the first chunk is shortened;
later chunks retain the default 128-character bound. This is **chunk-level streaming**,
not an autoregressive within-sentence stream. Shorter chunks can change prosody.
The default was reduced from 180 after a longer-sentence stress test showed much
higher memory use. `chunk_chars=80..180` in Python / `--chunk-chars` in the CLI
allows an explicit prosody/memory trade-off; larger chunks are not covered by
the default-budget measurements. Peak RSS depends on phonemes, voice and speed,
not just asset size, and no hard OS memory cap is imposed.

## Loopback HTTP API

```bash
.venv/bin/python -m nexi_tts serve --port 8765 --threads 2
# In another shell:
curl http://127.0.0.1:8765/voices
curl -f http://127.0.0.1:8765/synthesize \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello from the local API.","voice":"Bella","language":"en","speed":1}' \
  --output api.wav
```

`GET /health`, `GET /voices`, `POST /synthesize`. Health/voices identify the loaded
profile. Requests are sequential with a resident model. Loopback only; no auth,
CORS or public deployment. HTTP text limit 2,000
characters; CLI/Python limit 20,000. Incremental chunked synthesis is available
in Python and via `POST /stream`, not a continuous within-sentence protocol.

`serve --profile mini` loads Mini once for all requests. `POST /stream` accepts
the same JSON as `/synthesize`, but returns HTTP/1.1 chunked **raw PCM**, not WAV:
signed 16-bit little-endian, mono, 24 kHz. Format/rate/channel headers are sent.
Clients must decode HTTP chunk framing and treat a missing final zero chunk as
an incomplete response. First-chunk validation occurs before the 200 response;
later model failures terminate the connection rather than injecting JSON into
audio. Requests remain sequential; slow clients block the service until the
15-second socket timeout. No browser CORS or playback device is provided.

```bash
curl -f http://127.0.0.1:8765/stream -H 'Content-Type: application/json' \
  -d '{"text":"An answer can start playing before all its audio is generated."}' \
  --output response.pcm
# Optional: if ffplay is already installed, it can play raw samples incrementally:
# curl ... | ffplay -nodisp -autoexit -f s16le -ar 24000 -ac 1 -i pipe:0
```

## Validation / benchmark

```bash
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check nexi_tts tests
.venv/bin/mypy nexi_tts
NEXI_TTS_INTEGRATION=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python \
  -m unittest discover -s tests -p test_integration.py -v
.venv/bin/python -m nexi_tts.benchmark --output-dir results/short
.venv/bin/python -m nexi_tts.benchmark --output-dir results/long --long --processes 1 --warm-runs 1
```

Run the same real-inference suite on Mini with `NEXI_TTS_PROFILE=mini`.
Use `NEXI_TTS_OUTPUT_DIR=results/upgrade/mini/integration` to keep separate evidence.
Benchmark supports `--profile mini`, `--text-file tests/fixtures/everyday.txt`
and `--first-chunk-chars 80` for comparable first-audio measurements.
The opt-in suite runs all eight voices, speed changes, challenge text, real
loopback WAV/PCM HTTP, and a measured <1 GB process-budget assertion. Python
networking is denied in the inference checks; the HTTP check necessarily allows
loopback sockets and separately forbids asset fetches.

Unit tests use only local fixtures/loopback HTTP; real inference benchmarks
run in fresh subprocesses with Python sockets disabled. WAVs and weights are
ignored; small JSON measurements are committed.

## License / limits

Driver and upstream nano-int8 weights: Apache-2.0. See LICENSE and NOTICE.
Phonemizer/eSpeak NG: GPL-3.0 — important for bundled redistribution.
English preset voices only: no voice cloning, emotions, multilingual promise,
or claim of ElevenLabs-equivalent quality. English normalization handles signed
numbers, decimal digits, ordinals, percentages, dollar/pound/euro amounts,
selected units and common titles. Decimal trailing zeros are spoken; versions
and dotted addresses are not partially rewritten. Both raw and expanded text
are capped at 20,000 characters. Currency amounts allow at most two decimal
places. Spell out ambiguous dates, phone numbers, identifiers and unusual units
yourself; this is not a full locale-aware normalization engine.
Linux x86-64 is tested; other OS/CPU combinations are not yet verified.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the pinned frontend, licenses, and
**real, separate Pocket TTS fine-tuning route**; [USE_CASES.md](USE_CASES.md) for
integration patterns. No trained adapter or custom voice is included.
