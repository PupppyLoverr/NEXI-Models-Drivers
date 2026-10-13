# NEXI-STT — local CPU dictation backend

A runnable English speech-to-text CLI, pause-delimited PCM dictation interface,
and loopback HTTP API using **upstream
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
connection is used for package installation and **only explicit download steps**
for assets. Afterward all transcribe/serve/dictate/train/export/evaluate commands
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
# Beam-5 decoding (test your data; more search is not always more accurate):
.venv/bin/python -m nexi_stt transcribe fixtures/jfk.wav --model models/base.en --profile balanced
```

Example actual output:

> And so my fellow Americans ask not what your country can do for you ask what you
> can do for your country.

Input is uncompressed **PCM16 WAV**, mono/stereo, 8–48 kHz, >0–120 seconds and
at most 10 MiB. PyAV downmixes/resamples to 16 kHz locally. Empty, truncated,
unsupported and oversized inputs are rejected. Split longer recordings into
utterances, or use the bounded PCM interface below. WAV transcription is batch
inference, not incremental token streaming. JSON includes
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
`--vad-silence-ms 100–3000` adjusts batch VAD segmentation (default 2000).
`--profile fast` uses beam=1 (default); `balanced` uses beam=5. Both stay
deterministic with temperature=0 and previous-text conditioning disabled.

## Pause-delimited dictation from PCM

```bash
# Local raw signed little-endian PCM16, mono, 16 kHz; JSONL final utterance events:
.venv/bin/python -m nexi_stt dictate --pcm recording.pcm --model models/tiny.en --words
# An explicitly initiated host capture process can pipe PCM to stdin:
# capture-program-outputting-pcm | .venv/bin/python -m nexi_stt dictate --model models/tiny.en
```

The Python integration is `nexi_stt.dictation.stream(driver, binary_input)`.
It consumes 32-ms audio frames using stateful bundled Silero VAD, retains 320 ms
of pre-roll, and finalizes after **1200 ms of detected silence** by default.
Use `--pause-ms 200–3000` to trade turnaround for context; shorter pauses can
split a sentence and reduce Whisper accuracy. `--max-utterance-seconds 1–30`
caps memory/continuous speech (default 20). No full recording is retained.
At EOF it flushes the last utterance. Odd-byte PCM tails fail instead of
silently dropping samples. Trailing partial frames are zero-padded, so endpoint
timestamps can round up by <32 ms.

Each `event="final"` includes absolute stream segment/word timestamps,
`stream_start_seconds`, `stream_end_seconds`, and `reason` (`pause`,
`max_duration`, `end_of_stream`). Speech-triggered but empty ASR events are
possible; pure silence produces no events. This is **utterance streaming around
batch Whisper**, not native incremental ASR or partial captions. Continuous
speech is hard-cut at the cap, without overlap; a word at the cut can be lost.
Inference is synchronous and backpressures the source; a native capture host
must manage its own device queue/overrun policy. Microphone acquisition and
permissions are still outside the driver and were not tested here.

## Local HTTP API

```bash
.venv/bin/python -m nexi_stt serve --model models/tiny.en --threads 4 --port 8767
# In another terminal on the SAME machine:
curl http://127.0.0.1:8767/health
curl -H 'Content-Type: audio/wav' -H 'X-STT-Hotwords: Americans country' \
  --data-binary @fixtures/jfk.wav 'http://127.0.0.1:8767/transcribe?words=1&vad=1'
```

`POST /transcribe` accepts raw WAV bytes, not multipart data or a server-side file
path. Optional query parameters are `words=0|1`, `vad=0|1`,
`profile=fast|balanced`, and `vad_silence_ms=100..3000`. Responses use the
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

### Reproducible small evaluation (not a leaderboard)

```bash
# OPTIONAL preparation dependency, not part of runtime:
.venv/bin/python -m pip install -r requirements-evaluation.txt
# Explicit, SHA256-verified 9.2 MB dataset acquisition:
.venv/bin/python -m nexi_stt download --preset sample-librispeech --destination fixtures/eval-source
.venv/bin/python scripts/prepare_eval.py
.venv/bin/python scripts/evaluate.py --model models/tiny.en --data fixtures/evaluation.jsonl \
  --profile fast --output results/librispeech-tiny-fast.json
```

This includes 73 read-speech clips from **one speaker**, plus 10-second digital
silence and seeded synthetic white noise. Run tiny/base and fast/balanced on the
same manifest, serially. Rows with `kind="non_speech"` and empty `text` are scored
as false-positive controls, not WER. Reports include peak process RSS,
median/p95 per-clip inference, total RTF, corpus WER and model/data provenance.
The sample is not a standard full LibriSpeech score, multi-accent dictation
evaluation, or evidence of a category ranking. See [BENCHMARKS.md](BENCHMARKS.md).

For a broader read-speech proxy, prepare the fixed **200-clip, 40-speaker**
test-clean subset (five clips per speaker selected by archive-member-path SHA256, not WER).
No additional dependency beyond the runtime is needed for this preparation:

```bash
mkdir -p fixtures/test-source
# Explicit optional 346,663,984-byte dataset download; inference does not do this:
curl -fL https://www.openslr.org/resources/12/test-clean.tar.gz \
  -o fixtures/test-source/test-clean.tar.gz
.venv/bin/python scripts/prepare_test_clean.py --archive fixtures/test-source/test-clean.tar.gz \
  --sha256 39fde525e59672dc6d1551919b1478f724438a95aa55f874b576be21967e6c23
.venv/bin/python scripts/evaluate.py --model models/tiny.en --data fixtures/test-clean.jsonl \
  --output results/test-clean-tiny-fast.json
.venv/bin/python scripts/evaluate.py --model models/base.en --data fixtures/test-clean.jsonl \
  --output results/test-clean-base-fast.json
```

This is a subset result, **not full test-clean WER or real microphone dictation**.
The archive checksum is mandatory; preparation reads selected flat audio members
without arbitrary archive extraction. Both WAV data and the archive are ignored.

## Reproduce validation

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/ruff check nexi_stt scripts tests
.venv/bin/ruff format --check nexi_stt scripts tests
.venv/bin/mypy nexi_stt
.venv/bin/python -m pytest -q
.venv/bin/python scripts/regression.py --model models/tiny.en --wav fixtures/jfk.wav \
  --output results/tiny-regressions.json
.venv/bin/python scripts/dictation_regression.py --model models/tiny.en --wav fixtures/jfk.wav \
  --reference fixtures/jfk.reference.txt --output results/dictation-regressions.json
.venv/bin/python -m nexi_stt.benchmark --model models/tiny.en --wav fixtures/jfk.wav \
  --reference fixtures/jfk.reference.txt --output results/tiny-jfk-benchmark.json
.venv/bin/python -m nexi_stt.benchmark --model models/base.en --wav fixtures/jfk.wav \
  --reference fixtures/jfk.reference.txt --output results/base-jfk-benchmark.json
```

The 25 offline unit tests need no weights, internet, torch or ASR imports. Actual
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
Optional evaluation uses [LibriSpeech](https://www.openslr.org/12), CC BY 4.0:
Vassil Panayotov, Guoguo Chen, Daniel Povey and Sanjeev Khudanpur, *LibriSpeech:
An ASR corpus based on public domain audio books*, ICASSP 2015. The small
Hugging Face dummy dataset is a repackaged subset, not newly collected data.
Preparation uses Apache-2.0 [Apache Arrow](https://github.com/apache/arrow/blob/main/LICENSE.txt).
