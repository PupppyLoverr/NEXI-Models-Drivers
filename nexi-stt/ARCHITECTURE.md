# Architecture and boundaries

## Inference

```text
explicit download -> immutable HTTPS URL -> bytes+SHA256 verification
                  -> atomic local asset file -> nexi-assets.json

PCM16 WAV bytes -> size/header/duration validation -> local PyAV resample/downmix
               -> bundled Silero ONNX VAD (default on)
               -> Whisper tiny.en/base.en, CT2 CPU int8, greedy decoding
               -> exhaust lazy segment generator -> text/segments/optional words
               -> JSON/text CLI or synchronous loopback HTTP response
```

The original downloadable SYSTRAN CT2 weights occupy ~78 MB/~148 MB including
tokenizer/metadata and use half-precision storage. **Runtime CPU int8 is not a
claim that those downloaded files are already int8.** Custom export writes
int8 storage. The `Driver` holds one model and one worker; CPU thread count is
configurable (default 4). Decode parameters are beam size 1, best-of 1,
temperature 0, English transcription, no previous-text conditioning, optional
hotwords and word timestamps. Accuracy/latency differ from beam-5 published
benchmarks. Segment timings are mapped back through VAD to the original audio.

`assets.py` is the only runtime module that makes outbound requests, and only
when `download` is explicitly invoked. It has no download call at import time.
The driver requires a local manifest plus local `model.bin`, `config.json` and
`tokenizer.json`; all manifested file sizes/hashes are checked. It enables
`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, telemetry disabling and
`local_files_only=True` before loading. There is no remote-code execution
option. `assets.json` ships in the package, including all model/sample checksums.
Checksums establish integrity against that manifest, not trust in an arbitrary
user-supplied export or malicious local replacement of both assets and manifest.

Input limits bound audio decoding/feature memory: 10 MiB, 120 seconds, 1–2
channels, 8–48 kHz, PCM16 only. Validation checks actual frame bytes, rejecting
truncation rather than trusting just the header. Inference processes complete
clips; it does not generate live partial hypotheses, microphone endpoint events,
speaker diarization, contextual LLM rewrites or system-wide text insertion.

## Local API and privacy

The standard-library HTTP server binds only IPv4 loopback. Requests are
sequential, with 15-second socket read timeout and bounded body length. Only
raw WAV upload is accepted; arbitrary server file paths and chunked transfer are
not supported. Browser Origin requests are rejected and no CORS permission is
provided. Responses are `no-store`; request/query/body/transcript logging is
disabled. Audio/transcripts stay in memory unless the caller explicitly writes
CLI output or reports. Package installation and explicit downloads necessarily
use network; inference does not.

This is not a hardened public/multi-tenant API: there is no auth, rate limiting,
job queue or defense against malicious local processes. A slow local request
can block the single server. No swap encryption, disk-erasure or OS-level
privacy promise is made. Do not expose it via a public tunnel/reverse proxy.

## Fine-tuning / export

```text
explicit training-tiny.en download (HF safetensors + processor, immutable hashes)
local PCM16 WAV + exact transcript JSONL
    -> WhisperProcessor, 16 kHz mel features padded to 30 seconds
    -> WhisperForConditionalGeneration FP32 CPU teacher-forced loss
    -> gradient accumulation + non-reentrant checkpointing + clipped AdamW update
    -> local HF safetensors + processor + training report
    -> CT2 TransformersConverter int8 + local fast tokenizer JSON
    -> checksum manifest -> same offline inference Driver
```

The code uses real PyTorch optimization, not an inference-only checkpoint rename
or adapters that cannot be exported. It trains all parameters by default; the
configuration can freeze the encoder. BOS is removed from target labels when
the decoder will add it itself. The trainer uses one clip per microbatch, cycles
the JSONL deterministically, uses no external datasets service, checks finite
loss and refuses to overwrite an existing checkpoint. CPU-only torch lives in a
separate venv; importing a torch-equipped environment can change inference RSS.

Training FP32 parameters, gradients, optimizer state and saved activations need
more memory than int8 inference. The actual tiny one-step smoke peaked at
**1,409,179,648 bytes (~1.41 GB)**, whereas exported inference was ~346 MB. This
is not a training-memory guarantee for larger models, batches or settings.
Checkpointing uses `use_reentrant=False`; the default reentrant path failed
with a reused-backward graph error on this validated torch/Transformers stack.

Only one optimizer step on one public demo was run. Loss 0.5516 establishes
that the optimization path runs, **not that quality improves**. Its subsequent
transcription is on reused training audio, not held-out data. Nothing is
marketed as our useful fine-tuned model. Reports are committed; weights remain
local/ignored. For real adaptation compare held-out corpus WER from
`scripts/evaluate.py`, reviewing accent/name/noise errors and silent inputs.
This is a minimal trainer: no optimizer-state resume, shuffling, automatic eval,
distributed training, data augmentation or hyperparameter selection is included.

## Reproducible measurement

`nexi_stt.benchmark` executes three one-call fresh subprocesses and a fourth
fresh process with one first call + three warm calls. It captures each worker's
kernel peak RSS, exact model directory bytes, software versions, source hash,
transcript, WER and timers. RSS includes Python, native libraries, model,
resampling, VAD, decode buffers and workspaces, sampled after the last inference
before final JSON serialization. It excludes the separate
benchmark parent and cannot be equated to weight size or total machine RAM.
Cold subprocess wall includes interpreter startup, checksum/import/model load,
transcription, JSON serialization and exit. Per-call timing excludes model load
but includes PyAV, VAD, feature extraction and exhausting the output generator.
Warm timings exclude the first call in the same process. The OS page cache was
not flushed; cold does not mean disk-cold. Final tiny/base measurements were
run serially with no concurrent training/model benchmark from this session.

The `strace -f -e trace=network` inference proof observed **zero network syscalls**
through complete real load/transcription. The HTTP API intentionally has
loopback traffic and is outside that proof. Unit tests verify malformed inputs,
missing assets/no auto-download, hashes, manifest paths, download atomicity,
lazy generator consumption, CPU/local-files-only flags, vocabulary limits,
HTTP rejection paths and WER math. Real-model regressions separately verify
silence, empty WAV, hint/word timestamps and HTTP transcription.

## Why Whisper now; streaming alternatives

Whisper has established CPU packages, permissive weights and a mature documented
HF supervised training -> CT2 export path, all validated here. Its downside is
whole-utterance inference and 30-second padded feature windows. Native streaming
Moonshine Voice Tiny Streaming (34M) and sherpa-onnx's 20M Zipformer transducer
are worth evaluating for microphone partial results. Neither is integrated or
locally measured here. Their own WER corpora and runtime paths differ; see the
sourced comparisons in [BENCHMARKS.md](BENCHMARKS.md). Moonshine's native library
is the streaming candidate; its current Transformers model card explicitly
warns that the Transformers path is not fully efficient streaming.
