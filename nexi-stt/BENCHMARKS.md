# Benchmarks, evidence and fair comparisons

## Locally measured — 2026-10-13

**Hardware:** Linux x86_64 VM, Intel Xeon Platinum 8559C, 8 logical CPUs; no GPU
used. **Software:** CPython 3.10.12, faster-whisper 1.2.1, CTranslate2 4.6.0,
PyAV 16.0.1, ONNX Runtime 1.23.2, NumPy 2.2.6. **Decode:** CPU int8, 4 threads,
1 worker, English, beam=1, temperature=0, previous-text conditioning off,
VAD on, segment timestamps on, word timestamps off for the timed benchmark.

Audio is the real **11.0-second JFK speech excerpt**, pinned at
[`whisper.cpp` a8d002cfd879315632a579e73f0148d06959de36](https://github.com/ggml-org/whisper.cpp/blob/a8d002cfd879315632a579e73f0148d06959de36/samples/jfk.wav),
352,078 bytes, SHA256
`59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e`.
Reference is 22 words, supplied in `fixtures/jfk.reference.txt`:

> And so my fellow Americans ask not what your country can do for you ask what
> you can do for your country

**Do not interpret zero errors on these 22 well-known words as a general quality
score, or compare it to Open ASR/LibriSpeech WER.** The JFK table does not evaluate
accents, noisy-room dictation, long recording, laptop power or mobile devices.
Additional read-speech subset results are below, separately from this smoke test.

| Local checkpoint/runtime | Exact model-directory bytes | Max whole-process peak RSS bytes | Median cold process wall | Median cold transcribe | Median warm transcribe | Warm RTF | Smoke word errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| Upstream tiny.en (38M), CT2 CPU int8 | 78,091,923 | 341,680,128 (~342 MB) | 1.429 s | 0.583 s | 0.462 s | 0.0420 | 0/22 |
| Upstream base.en (74M), CT2 CPU int8 | 147,770,840 | 431,403,008 (~431 MB) | 2.002 s | 0.934 s | 0.801 s | 0.0728 | 0/22 |
| One-step tiny training/export smoke, CT2 int8 storage/runtime | 45,204,032 | 345,706,496 (~346 MB) | 1.281 s | 0.599 s | 0.552 s | 0.0502 | 0/22, **reused training clip** |

MB above is decimal 1,000,000 bytes, not MiB. The upstream model directories
store FP16 weights but execute with CPU int8; exported int8 storage is smaller.
Disk bytes include model config, tokenizer and checksum manifest. They **exclude
Python dependencies**, the input WAV, optional training source weights and other
models. `results/setup-disk-bytes.json` records separate measured setup/checkpoint
directory bytes; the `.venv` measurement includes installed developer tools and
is not a minimal runtime package-size claim.

### Measurement method

The benchmark starts **three independent fresh inference subprocesses** (one
call each), then a fourth process with one first call followed by **three warm
calls**. The table's RSS is the **maximum kernel `ru_maxrss` of any of those four
workers**, including warm-buffer reuse, not just a model-weight estimate. RSS
includes Python/native runtime imports, hash checking/model load, audio decode,
VAD, ASR and assembled result dictionaries. RSS is sampled after the last
inference, before final JSON serialization. It excludes the separate benchmark
parent. This is one process's memory, not summed concurrent model memory or a
claim about the entire desktop product.

- **Cold process wall:** subprocess start through JSON output and process exit,
  including interpreter startup, import/checksum/model load, decode/transcription.
- **Cold transcribe:** the first call after loading, including local audio
  resampling, VAD, feature processing, decoding and exhausting lazy segments.
- **Warm transcribe:** same loaded model/process, excluding its first call.
- **RTF:** transcription seconds / 11 audio seconds. It does not include capture,
  endpoint wait, keyboard insertion or model initialization.
- **Cold is process-cold, not disk-cold:** the OS file cache was not flushed.
- **Serial runs:** no other training or ASR benchmark from this session ran
  concurrently with these final timed runs. General shared-VM host contention
  cannot be ruled out. Three samples are not a statistical latency guarantee.
- **WER:** NFKC + casefold; English letters/digits/apostrophes, punctuation removed;
  Levenshtein word edits / reference words. Punctuation correctness is not measured.

Each measured JSON includes timestamps, hardware/software, exact worker commands,
all individual measurements, transcript/segment output and WER; summary values
are derived from the individual rows. Reproduce serially with the commands in
[README.md](README.md), not with backgrounded concurrent tiny/base workers.

### Evidence inventory (committed JSON, no weights/audio)

| File under `results/` | Evidence |
|---|---|
| `tiny-jfk-benchmark.json` | Upstream tiny cold/warm process RSS, disk, latency, WER |
| `base-jfk-benchmark.json` | Same protocol for upstream base |
| `tiny-jfk-transcript.json` | Actual tiny JSON including word timestamps |
| `training-smoke.json` | Real FP32 CPU optimization loss, config, RSS and checkpoint hash |
| `export-smoke-transcript.json` | Real inference through the exported checkpoint |
| `export-smoke-benchmark.json` | Exported checkpoint cold/warm measurements |
| `tiny-regressions.json` | Real silence, vocabulary hints, word timestamps and HTTP output |
| `offline-network-proof.json` / `offline-proof-transcript.json` | Exact traced command, no outbound network calls, actual output |
| `evaluation-script-smoke.json` | Runnable JSONL evaluator proof; reused smoke clip, not held-out quality |
| `setup-disk-bytes.json` | Separately measured venv/source/export directory bytes |
| `process-exit-rss-proof.json` | Additional serial tiny/base fresh CLI runs measured by GNU time through process exit, including final JSON serialization |
| `tiny-process-transcript.json` / `base-process-transcript.json` | Actual transcripts from the GNU time runs |

An independent `/usr/bin/time -v` check through process exit (including JSON
serialization) measured **320,765,952 bytes** for tiny and **405,053,440 bytes**
for base in separate fresh CLI runs. They are additional single-cold-call
measurements, not replacements for the repeated cold/warm table above:

```bash
/usr/bin/time -v .venv/bin/python -m nexi_stt transcribe fixtures/jfk.wav \
  --model models/tiny.en --output transcript.json
```

`strace -f -e trace=network` followed the actual CLI inference and all threads;
**zero network syscalls were observed**. The raw trace contains only successful
thread/process exits and remains local/ignored; its SHA256 is in the proof JSON.
This evidence concerns one real file transcription. The API intentionally opens
a local loopback socket. Offline flags and local-file validation are also tested.

**Silence regression:** 10 seconds of all-zero 16 kHz PCM16, VAD on -> `text=""`,
`segments=[]`, `speech_seconds_after_vad=0`, ~0.043-second transcription in the
recorded final regression. This is digital silence, not a realistic noise
corpus. Zero-frame WAV and invalid HTTP audio are rejected. VAD reduces
hallucination risk but does not prove all pauses/noise are handled correctly.

**Training smoke:** one optimizer step, four accumulated microbatches of one
WAV/reference row, tiny.en full-parameter FP32 CPU, 4 torch threads, gradient
checkpointing on, learning rate 1e-5, AdamW, seed 13. Loss was 0.5515764;
model load + training + save was 6.549 seconds (imports excluded from that
timer); whole-process peak RSS **1,409,179,648 bytes (~1.41 GB)**. Torch
2.6.0+cpu/Transformers 4.57.1 were installed only in the separate training venv.
Checkpoint SHA256 is in `training-smoke.json`. The int8 export was loaded and
transcribed successfully in the runtime venv. **Training loss, successful export
and reused-clip WER are not proof of useful fine-tuning or generalization.**

## Expanded read-speech and endpoint evidence — 2026-10-13

Same Xeon 8559C, Linux CPU int8, 4 threads, English, temperature=0, VAD enabled,
previous-text conditioning disabled; serial fresh evaluator processes. The
first clip in each process is a cold call; later clips reuse the loaded model.
Per-clip timings exclude model initialization. RSS is whole-process `ru_maxrss`
after the last transcription, before final JSON serialization. OS caches were
not flushed. This is not a latency guarantee or a benchmark of different runtimes.

### One-speaker development sample and decode ablation

All 73 clips (speaker **1272**, 1,150 reference words) from
[hf-internal-testing/librispeech_asr_dummy](https://huggingface.co/datasets/hf-internal-testing/librispeech_asr_dummy/tree/5be91486e11a2d616f4ec5db8d3fd248585ac07a),
plus 10 seconds of digital silence and 10 seconds of seeded synthetic white noise
(NumPy seed 13, normalized Gaussian standard deviation 0.01, PCM16 clipping).
Total audio including controls: **501.034875 seconds**. Punctuation is stripped
by the existing normalizer. Median/p95 timings below cover all 75 clips.

| Model / profile | Word errors | Corpus WER | Median clip inference | p95 clip inference | Peak process RSS | Total RTF | Non-speech false positives |
|---|---:|---:|---:|---:|---:|---:|---:|
| tiny.en / fast (beam 1) | 128/1150 | 11.1304% | 0.259 s | 0.397 s | 359,976,960 B | 0.04026 | 0/2 |
| tiny.en / balanced (beam 5) | 127/1150 | 11.0435% | 0.273 s | 0.432 s | 362,590,208 B | 0.04327 | 0/2 |
| base.en / fast (beam 1) | 114/1150 | 9.9130% | 0.388 s | 0.467 s | 443,973,632 B | 0.05886 | 0/2 |
| base.en / balanced (beam 5) | 115/1150 | 10.0000% | 0.405 s | 0.692 s | 459,055,104 B | 0.06350 | 0/2 |

**Fast remains the default:** beam 5 barely changed tiny WER and slightly worsened
base WER on this sample. Choose model/profile on your held-out application data,
not the name of the profile. This is a development proxy from one speaker, **not
standard LibriSpeech WER or evidence that NEXI ranks above another ASR system**.

Parquet: 9,192,059 bytes, SHA256
`4e69a06fa5edc90921e5e7e39a7084881f8b3ed9c805c574f4f39c6fde27c603`.
Model directory bytes/revisions are unchanged from the earlier table. Evidence:
`results/librispeech-{tiny,base}-{fast,balanced}.json`; exact references, hypotheses,
per-clip errors/timings and manifest SHA256 are included. No fine-tuning was
performed on this evaluation data. Upstream pretraining overlap is not ruled out.

### Forty-speaker test-clean subset

**200 clips, 40 speakers, 4,499 reference words, 1,679.6801875 seconds of audio**.
`prepare_test_clean.py` picks five clips per speaker by the SHA256 ordering of
the canonical archive-member path, independent of text length or measured WER.
Both checkpoints transcribe exactly the same committed manifest, without hints
or fine-tuning on the sample. VAD is on, fast decoding is beam 1, no word
timestamps. Process-cold model loading is excluded from per-clip times; the
first call is included, with subsequent clips using the same loaded model.

| Model / profile | Word errors | Subset WER | Median clip inference | p95 clip inference | Whole-process peak RSS | Total RTF | Model disk |
|---|---:|---:|---:|---:|---:|---:|---:|
| tiny.en / fast | 240/4499 | 5.3345% | 0.296 s | 0.468 s | 384,679,936 B | 0.03788 | 78,091,923 B |
| base.en / fast | 178/4499 | 3.9564% | 0.426 s | 0.543 s | 482,963,456 B | 0.05269 | 147,770,840 B |

Base/fast is the more accurate **tested choice on this subset**, with higher
latency/RSS. Both remain below 500 decimal MB here. This does not establish
native-streaming latency, real room-noise robustness, phone performance,
punctuation accuracy or a category ranking. It is **not the official full
test-clean WER** and was not compared against a competitor runtime on these clips.

Archive: [OpenSLR test-clean.tar.gz](https://www.openslr.org/resources/12/test-clean.tar.gz),
346,663,984 bytes. Published [MD5](https://www.openslr.org/resources/12/md5sum.txt)
`32fa31d27d2e1cad72775fee3f4849a9` matched; measured/pinned SHA256:
`39fde525e59672dc6d1551919b1478f724438a95aa55f874b576be21967e6c23`.
Preparation rejects a different hash. Evidence:
`results/test-clean-{tiny,base}-fast.json`, including manifest hash, per-WAV hash,
reference/hypothesis, errors, latency, hardware, model revision and disk bytes.

### PCM utterance regression

`scripts/dictation_regression.py` feeds a local JFK PCM recording twice with
explicit silent gaps, verifies two pause-finalized events with zero errors on
this reused sample, absolute word timestamp offsets, EOF flush, bounded
length segmentation, zero events for digital silence/synthetic noise, and
stateful Silero classifications identical to upstream batch classifications.
Evidence: `results/dictation-regressions.json`.

Fresh regression process peak RSS was **351,166,464 bytes**, independently matched
by GNU time through process exit (`results/dictation-process-exit-proof.json`).
Its two ASR calls took 0.328 s and 0.300 s; these exclude capture and endpoint wait.
`results/dictation-offline-proof.json` records a separate all-thread network trace
of real load/PCM regressions: **zero network syscalls**. Trace-run timings are not
used as latency measurements. Existing CLI/API/export inference also passed
again (`tiny-improved-regressions.json`, `export-improved-driver-smoke.json`).

The **1200-ms pause default** preserves more context: an exploratory 600-ms
setting split this recording into short phrases and introduced a word error.
The test feeds prerecorded PCM as fast as possible; **no real microphone,
capture latency, live partial text or end-to-end keyboard dictation was measured**.
Finalized utterances do not make Whisper a native streaming ASR model.

Data attribution: [LibriSpeech / OpenSLR 12](https://www.openslr.org/12), CC BY 4.0;
Panayotov, Chen, Povey and Khudanpur, ICASSP 2015; source audiobooks from LibriVox.

## Published alternatives — NOT locally measured here

These rows are a candidate comparison, not a ranking against our 22-word test.
Published RAM, speed and WER come from different CPUs, corpora, precisions and
decode settings. “Not reported here” is intentionally not an estimate.

| Candidate | Architecture / parameters | Published CPU RAM/latency | Published quality | Local/offline and fine-tuning path | Licence / source |
|---|---|---|---|---|---|
| Whisper tiny.en / base.en | Encoder-decoder, 38M / 74M | **Our measurements above**, not a published cross-device result | No comparable held-out score measured here | Offline batch; HF supervised training -> CT2 export **validated** | MIT; [Whisper model table](https://github.com/openai/whisper#available-models-and-languages), pinned manifests |
| Whisper small via faster-whisper | Encoder-decoder, 244M | Published int8 **1477 MB**, **1m42s** for 13-minute audio, beam 5, 8 threads, i7-12700K | No WER for this CPU row | Offline batch; same family supports supervised adaptation, small not trained/tested here | MIT; [faster-whisper reference benchmark](https://github.com/SYSTRAN/faster-whisper/tree/v1.2.1#small-model-on-cpu) |
| sherpa-onnx streaming Zipformer 20M English | Streaming transducer, ~20M | Not measured; no comparable process-RSS/latency number quoted | No comparable score quoted | Native streaming/offline ONNX; genuine icefall LibriSpeech training recipe, not integrated/trained here | Apache-2.0 model; [ONNX card](https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17), [training checkpoint](https://huggingface.co/desh2608/icefall-asr-librispeech-pruned-transducer-stateless7-streaming-small), [recipe PR](https://github.com/k2-fsa/icefall/pull/903) |
| Moonshine Voice Tiny Streaming | Sliding-window encoder + autoregressive decoder, **34M** | Native CPU streaming advertised; no comparable RSS/latency measured/quoted | **12.00%** published English Open ASR average, floating-point reference | Local native streaming library; model weights/architecture published. No fine-tune/export path validated here | MIT; [official models](https://moonshine-voice.readthedocs.io/en/latest/models/available-models/), [model card](https://huggingface.co/UsefulSensors/moonshine-streaming-tiny) |
| Moonshine Voice Small / Medium Streaming | **123M / 245M** | No comparable RSS/latency measured/quoted | **7.84% / 6.65%**, same published English Open ASR average | Same native streaming candidate family, not integrated here | MIT; same official models/card, [announcement](https://huggingface.co/blog/UsefulSensors/announcing-moonshine-voice) |
| Wispr Flow | Proprietary end-user dictation product, backend model size not disclosed in cited source | No comparable local ASR process benchmark | No comparable benchmark quoted | Official privacy page says **transcription always happens in the cloud**; storage/model-improvement controls are separate. User cannot export these weights or fine-tune this product through this driver | Proprietary service; [official privacy/processing description](https://wisprflow.ai/privacy) |

The faster-whisper published table specifies faster-whisper **v1.1.0** as its
benchmark implementation even though it is reproduced in the v1.2.1 README.
Its small model RAM already exceeds our <=1 GB inference target on that test;
we did not extrapolate it to this Xeon/short-clip beam-1 setup. Whisper.cpp has
different memory/runtime characteristics; its numbers are not presented as
faster-whisper measurements.

Moonshine's official model card explicitly says the current **Transformers path
does not yet implement fully efficient streaming**; evaluate its **native
Moonshine Voice library** for partial-result use, not a generic Transformers
batch pipeline. The official model catalogue describes English WER as an
average across eight Open ASR datasets on floating-point reference models and
notes that quantization can worsen the scores. No Moonshine speed-only mobile
claim is used as quality evidence or as a measured speed comparison here.

**Decision:** select tiny.en as the measured default under 500 MB process RSS,
offer base.en as a measured alternative, and ship the completed fine-tune/export
path. Moonshine Tiny Streaming is a strong future live-microphone candidate,
and sherpa's small transducer is another genuine streaming option. Both need
local benchmark, silence/hallucination, domain accuracy and training/export
validation before a runtime pivot. Wispr Flow is product inspiration, not a
direct local-model competitor or an implemented system-wide integration.

## Additional five-speaker sanity check (parent integration)

A deterministic subset of **LibriSpeech test-clean**, not training data: the
first utterance alphabetically from each of the first five alphabetically
ordered speakers. It contains 50.175 seconds and 125 reference words. Data and
reference provenance are in `fixtures/librispeech-five.json`; audio is not
committed. LibriSpeech is [CC BY 4.0](https://www.openslr.org/12/), attributed to
Vassil Panayotov, Guoguo Chen, Daniel Povey and Sanjeev Khudanpur.

Same Xeon CPU, four threads, CPU int8 and VAD defaults. One fresh process per
model, warmed model reused across its five different clips; word timestamps
off. Whole-process GNU time RSS includes loading, all five transcriptions and
result serialization. OS page cache was not flushed. These are single runs,
not statistical latency percentiles or benchmark-wide LibriSpeech WER.

The optional preparation helper was executed against the verified archive and
reproduced all five recorded WAV SHA-256 values exactly. Corpus evaluation was
then rerun through the public `scripts/evaluate.py` interface. Parent silence,
empty-audio, vocabulary/timestamp and real HTTP regressions also passed; see
`results/parent-regressions.json`.

| Model | Subset word errors / words | Subset WER | Full process wall | Process peak RSS | Model directory bytes |
|---|---:|---:|---:|---:|---:|
| tiny.en | 8 / 125 | 6.4% | 1.960 s | 348,520,448 | 78,091,923 |
| base.en | 6 / 125 | 4.8% | 3.073 s | 436,277,248 | 147,770,840 |

Exact unrounded measurements: `results/tiny-corpus-process.json` and
`results/base-corpus-process.json`. Transcripts, references, edit counts and
all per-clip timings: `results/tiny-corpus.json` and `results/base-corpus.json`.
Different decode settings (including word timestamp alignment) can change
the transcript and WER. This tiny clean read-speech subset does **not**
establish accuracy on spontaneous dictation, noise, accents or languages.

Reproduce from `nexi-stt/` with FFmpeg installed. The optional public archive
is about 346 MB; preparation verifies its official MD5 before reading members.
The helper records the actual WAV hashes because FFmpeg versions can change
container metadata without changing decoded speech.

```bash
curl -fL https://openslr.elda.org/resources/12/test-clean.tar.gz -o test-clean.tar.gz
.venv/bin/python scripts/prepare_librispeech.py --archive test-clean.tar.gz --output fixtures/librispeech-five
python3 ../common/bench/process.py --label tiny-corpus-evaluator \
  --asset-path models/tiny.en --output results/reproduced-tiny-process.json -- \
  .venv/bin/python scripts/evaluate.py --model models/tiny.en \
  --data fixtures/librispeech-five/evaluation.jsonl --output results/reproduced-tiny-corpus.json
# Repeat with base.en and distinct output paths.
```

## Immutable asset provenance

- [SYSTRAN tiny.en revision](https://huggingface.co/Systran/faster-whisper-tiny.en/tree/0d3d19a32d3338f10357c0889762bd8d64bbdeba)
- [SYSTRAN base.en revision](https://huggingface.co/Systran/faster-whisper-base.en/tree/3d3d5dee26484f91867d81cb899cfcf72b96be6c)
- [OpenAI trainable tiny.en revision](https://huggingface.co/openai/whisper-tiny.en/tree/87c7102498dcde7456f24cfd30239ca606ed9063)
- Every model/tokenizer/config/WAV byte count, URL and SHA256 is recorded in
  `nexi_stt/assets.json`. Full checksum manifests are also saved beside each
  downloaded or exported model. No model binaries are committed.

Sources accessed 2026-10-13. The source papers/cards/runtime versions may differ
from one another; retain those distinctions when reporting comparisons.
