# NEXI-STT — local CPU dictation backend

A runnable English speech-to-text CLI and loopback HTTP API using **upstream
Whisper tiny.en/base.en through faster-whisper/CTranslate2, CPU int8**. No cloud
service, account, telemetry, automatic model download, or external FFmpeg
executable is needed for inference. This is a driver, **not a new NEXI-trained
speech model**, and **not a complete Wispr Flow-style desktop product**.

On the measured Linux 8-vCPU Xeon 8559C VM, the full tiny.en inference process
peaked at **341,680,128 bytes (~342 MB)** and transcribed an 11-second real English
recording in **0.462 seconds warm**. Base.en peaked at **431,403,008 bytes (~431 MB)**.
These are short-clip measurements, not universal memory or latency guarantees.
See [BENCHMARKS.md](BENCHMARKS.md) for cold starts, exact configuration and evidence.

## Setup and explicit download

Validated: Ubuntu 22.04, Linux x86_64, CPython 3.10.12, no GPU. Other platforms
are untested; suitable wheels and CPU int8 support must be available. An internet
connection is used for package installation and **only the explicit `download`
command** for assets. Afterward all transcribe/serve/train/export/evaluate commands
use local files. Run from this folder:

```bash
cd nexi-stt
bash scripts/setup.sh
# Immutable revisions, expected sizes and SHA256 for EVERY downloaded file:
.venv/bin/python -m nexi_stt download --preset tiny.en --destination models/tiny.en
.venv/bin/python -m nexi_stt download --preset sample-jfk --destination fixtures
# Optional larger English model:
.venv/bin/python -m nexi_stt download --preset base.en --destination models/base.en
```

`requirements.txt` pins all runtime dependencies; `requirements.in` records the
chosen direct versions. The downloaded assets are verified before atomic rename
and their manifests are verified again before loading. No Hugging Face repository
ID, URL, or missing-model fallback is accepted by the inference driver. Download
is idempotent, but requires network if files are missing or corrupt.

## CLI

```bash
# JSON with segment timestamps, configuration and timings:
.venv/bin/python -m nexi_stt transcribe fixtures/jfk.wav --model models/tiny.en
# Plain text or timestamped segments:
.venv/bin/python -m nexi_stt transcribe fixtures/jfk.wav --model models/tiny.en --format text
.venv/bin/python -m nexi_stt transcribe fixtures/jfk.wav --model models/tiny.en --format timestamps
# Approximate word timestamps and SOFT vocabulary hints:
.venv/bin/python -m nexi_stt transcribe fixtures/jfk.wav --model models/tiny.en \
  --threads 4 --words --hotwords 'Americans country' --output transcript.json
```

Example actual output:

> And so my fellow Americans ask not what your country can do for you ask what you
> can do for your country.

Input is uncompressed **PCM16 WAV**, mono/stereo, 8–48 kHz, >0–120 seconds and
at most 10 MiB. PyAV downmixes/resamples to 16 kHz locally. Empty, truncated,
unsupported and oversized inputs are rejected. Split longer recordings into
utterances; this is batch dictation, not incremental streaming. JSON includes
`text`, `segments`, `audio_seconds`, `transcribe_seconds`, `real_time_factor`,
`config`, and model provenance. `--words` adds word timestamps/probabilities;
these are estimates, not calibrated confidence scores or forced alignment.

**Silero VAD is on by default**, using the ONNX asset shipped inside the pinned
faster-whisper package. `--no-vad` disables it. VAD reduces silence hallucinations
but can miss soft speech and does not guarantee hallucination-free transcription.
The real 10-second digital-silence regression returns empty text/segments; a
zero-frame WAV is rejected before inference. Vocabulary hints (`--hotwords`,
<=400 characters, no control characters) bias decoding; they are not hard
constraints, a personal dictionary product, or a substitute for fine-tuning.

## Local HTTP API

```bash
.venv/bin/python -m nexi_stt serve --model models/tiny.en --threads 4 --port 8767
# In another terminal on the SAME machine:
curl http://127.0.0.1:8767/health
curl -H 'Content-Type: audio/wav' -H 'X-STT-Hotwords: Americans country' \
  --data-binary @fixtures/jfk.wav 'http://127.0.0.1:8767/transcribe?words=1&vad=1'
```

`POST /transcribe` accepts raw WAV bytes, not multipart data or a server-side file
path. Optional query parameters are `words=0|1` and `vad=0|1`. Responses use the
CLI's JSON shape. Errors: 400 invalid WAV/parameters, 403 browser Origin, 413
missing/oversized body, 415 unsupported content type, 500 local inference error.
The server binds **only 127.0.0.1**, loads one warm model, processes one request
at a time, has a read timeout, disables request logs/CORS and sends `no-store`.
It has **no authentication** and is for trusted local clients, not multi-user
deployment. Do not reverse-proxy it publicly. Local processes can access it.

## Fine-tune your own model; export for this driver

Whisper's MIT weights and Hugging Face implementation support real supervised
fine-tuning. The included CPU script performs loss/backward/AdamW updates on
local consented recordings; export converts the resulting local checkpoint to
int8 CTranslate2. **Training needs substantially more RAM than inference.**
Only a one-step technical smoke was run here; no useful customized checkpoint
or accuracy improvement is claimed.

```bash
# Explicitly fetch ORIGINAL trainable Whisper weights (different from CT2 weights):
.venv/bin/python -m nexi_stt download --preset training-tiny.en --destination models/training-tiny.en
python3 -m venv .venv-training
.venv-training/bin/python -m pip install -r requirements-build.txt
# Separate official CPU torch index avoids installing CUDA dependencies:
.venv-training/bin/python -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
.venv-training/bin/python -m pip install -r requirements-training.txt
.venv-training/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv-training/bin/python -m pip check
# Technical smoke only: one optimizer step, four accumulated microbatches:
.venv-training/bin/python scripts/train.py --base models/training-tiny.en \
  --data fixtures/smoke-training.jsonl --config training-config.json \
  --steps 1 --output training-output/smoke-hf
.venv-training/bin/python scripts/export.py --checkpoint training-output/smoke-hf \
  --output training-output/smoke-ct2
# Use the LIGHT runtime venv for inference, not the torch training venv:
.venv/bin/python -m nexi_stt transcribe fixtures/jfk.wav \
  --model training-output/smoke-ct2 --words
```

For real adaptation, make separate train/held-out JSONL files. Each line is
`{"wav":"relative-to-jsonl.wav","text":"verbatim transcript"}`. Training clips
must be >0–30 seconds; English transcripts must fit Whisper's target token limit.
Replace the smoke data, choose steps/learning rate in `training-config.json`, and
omit `--steps 1`. Output directories must not already exist. Evaluate the base
and export on identical held-out clips:

```bash
.venv/bin/python scripts/evaluate.py --model models/tiny.en \
  --data heldout.jsonl --output base-evaluation.json
.venv/bin/python scripts/evaluate.py --model training-output/my-ct2 \
  --data heldout.jsonl --output tuned-evaluation.json
```

The evaluator emits corpus word errors/reference count and WER using a documented
English normalization. It saves references/transcripts: treat reports as private
data. This starter trainer cycles rows, uses batch size one + accumulation,
FP32 CPU, seed 13 and non-reentrant gradient checkpointing. It does not implement
an automatic validation loop, training resumption, large dataset tooling or a
production training service. Domain quality requires held-out speakers, accents,
noise, names, punctuation and silence tests. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Reproduce validation

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/ruff check nexi_stt scripts tests
.venv/bin/ruff format --check nexi_stt scripts tests
.venv/bin/mypy nexi_stt
.venv/bin/python -m pytest -q
.venv/bin/python scripts/regression.py --model models/tiny.en --wav fixtures/jfk.wav \
  --output results/tiny-regressions.json
.venv/bin/python -m nexi_stt.benchmark --model models/tiny.en --wav fixtures/jfk.wav \
  --reference fixtures/jfk.reference.txt --output results/tiny-jfk-benchmark.json
.venv/bin/python -m nexi_stt.benchmark --model models/base.en --wav fixtures/jfk.wav \
  --reference fixtures/jfk.reference.txt --output results/base-jfk-benchmark.json
```

The 21 offline unit tests need no weights, internet, torch or ASR imports. Actual
model regressions and measured transcripts are separately recorded under
`results/`. Weights, WAVs, virtualenvs and trained checkpoints are ignored and
not committed. [USE_CASES.md](USE_CASES.md) describes appropriate integrations.

## Licences and sources

Upstream [Whisper weights/code](https://github.com/openai/whisper#license),
[faster-whisper](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/LICENSE) and
[CTranslate2](https://github.com/OpenNMT/CTranslate2/blob/v4.6.0/LICENSE) are MIT;
the model manifest records exact upstream revisions. No upstream branding or
fine-tuning ownership is claimed. The local driver code is MIT (see `LICENSE`).
PyAV is [BSD-3-Clause](https://github.com/PyAV-Org/PyAV/blob/v16.0.1/LICENSE.txt);
its bundled FFmpeg libraries have their own
[LGPL/GPL-dependent licensing obligations](https://ffmpeg.org/legal.html).
Other primary runtime licences: [Silero VAD](https://github.com/snakers4/silero-vad/blob/master/LICENSE)
and [ONNX Runtime](https://github.com/microsoft/onnxruntime/blob/main/LICENSE) MIT,
[NumPy](https://numpy.org/doc/stable/license.html) BSD-3-Clause, and
[Hugging Face tokenizers](https://github.com/huggingface/tokenizers/blob/main/LICENSE)
Apache-2.0. Optional training uses
[PyTorch](https://github.com/pytorch/pytorch/blob/v2.6.0/LICENSE) BSD-style terms
and [Transformers](https://github.com/huggingface/transformers/blob/v4.57.1/LICENSE)
/ [safetensors](https://github.com/huggingface/safetensors/blob/main/LICENSE)
Apache-2.0. Preserve dependency notices and review the exact binary build when distributing
an application. Training data needs its own rights/consent. The demo WAV is a
pinned whisper.cpp repository sample of JFK's inaugural-address excerpt, not
a collected private recording. [BENCHMARKS.md](BENCHMARKS.md) links comparative
research, including Moonshine, sherpa-onnx and Wispr Flow.
