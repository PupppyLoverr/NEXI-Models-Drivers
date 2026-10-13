# NEXI TTS — tiny local CPU voice driver

Runnable text → WAV using **upstream Kitten TTS Nano 0.8 int8** (15M parameters,
27,650,302 bytes including voices/config/card). No cloud inference, GPU, spaCy,
or PyTorch. This is **not a fine-tune**; the upstream ONNX family has no released
training pipeline. See NOTICE for the pinned 0.8 frontend contract.

Measured on Linux x86-64 / Xeon 8559C with two ONNX threads: **345 MB peak RSS**
for a 10.15-second utterance, **349 MB** for an 81.2-second utterance;
approximately **0.21–0.23 real-time factor**. These are complete process peaks,
not weight sizes. See [BENCHMARKS.md](BENCHMARKS.md) and the committed JSON.
All eight presets generated real audio with Python networking blocked.

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
Speed: 0.5–2.0, multiplied by the upstream voice-specific speed prior.

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

`GET /health`, `GET /voices`, `POST /synthesize`. Sequential requests, resident
model. Loopback only; no auth, CORS or public deployment. HTTP text limit 2,000
characters; CLI/Python limit 20,000. Incremental chunked synthesis is available
in Python, not a continuous within-sentence streaming protocol.

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

Unit tests use only local fixtures/loopback HTTP; real inference benchmarks
run in fresh subprocesses with Python sockets disabled. WAVs and weights are
ignored; small JSON measurements are committed.

## License / limits

Driver and upstream nano-int8 weights: Apache-2.0. See LICENSE and NOTICE.
Phonemizer/eSpeak NG: GPL-3.0 — important for bundled redistribution.
English preset voices only: no voice cloning, emotions, multilingual promise,
or claim of ElevenLabs-equivalent quality. Numbers are lightly normalized;
spell out currencies, dates, identifiers and unusual units yourself.
Linux x86-64 is tested; other OS/CPU combinations are not yet verified.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the pinned frontend, licenses, and
**real, separate Pocket TTS fine-tuning route**; [USE_CASES.md](USE_CASES.md) for
integration patterns. No trained adapter or custom voice is included.
