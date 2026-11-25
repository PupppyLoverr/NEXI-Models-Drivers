# nexi-voice benchmarks

All numbers measured on this machine: 8 vCPU, 31 GB RAM, CPU only (no GPU).
Fresh-process peak RSS via `common.bench.measure` (50 ms sampling).
Raw JSON in `nexi-voice/results/`.

## TTS — Kyutai Pocket TTS 4.0.1 (`pocket-tts` pip package)

Text under test: 2-sentence call greeting (~130 chars), voice `alba`, 24 kHz
output, streaming API (`generate_audio_stream`). 3 reps each, median shown.

| Variant (config)            | Params class | Peak RSS | RTF   | Time-to-first-audio | Real-time? |
|-----------------------------|--------------|----------|-------|---------------------|------------|
| `english_2m_2026-10`        | ~2M          | 603 MB   | 0.10  | ~36 ms              | yes, ~10x  |
| `english_7m_2026-10`        | ~7M          | 650 MB   | 0.12  | ~62 ms              | yes, ~8x   |
| `english_18m_2026-10`       | ~18M         | 627 MB   | 0.17  | ~72 ms              | yes, ~6x   |
| `english_2026-10` (flagship)| ~100M        | 1,179 MB | 0.46  | ~181 ms             | yes, ~2x   |

Load times: 1.6–3.7 s cold.

**Reading:** every tiny variant meets the <1 GB / real-time bar on one CPU
box. The flagship exceeds 1 GB. NEXI-Voice-TTS default = `english_18m_2026-10`
(best quality/footprint tradeoff in the family); `english_2m_2026-10` is the
low-resource profile for the crappiest hardware. Quality comparison vs
ElevenLabs/Fish is a listening task — claimed only after a blind eval, not here.

## STT — faster-whisper baselines (int8, CPU, beam 1, VAD on)

Corpus: pinned `hf-internal-testing/librispeech_asr_demo` clean/validation
parquet, first 40 clips, decoded via soundfile (not torchcodec).

| Engine        | Peak RSS | WER (n=40) | RTF mean | RTF p90 | Load |
|---------------|----------|------------|----------|---------|------|
| `fw-tiny` (tiny.en) | 505 MB | 13.3%  | 0.076    | 0.133   | 0.5 s |
| `fw-base` (base.en) | 627 MB | 13.4%  | 0.132    | 0.232   | 2.8 s |

Challenger: **Rumble-2-Flash** (Reson8, 0.5B Qwen3-ASR, transformers-native,
fp32 on CPU), same corpus, n=15:

| Engine   | Peak RSS | WER (n=15) | RTF mean | RTF p90 | Load |
|----------|----------|------------|----------|---------|------|
| `rumble` | 3,540 MB | 4.05%      | 7.25     | 8.66    | 11.9 s |

**Rumble verdict:** transcription quality is real (4% WER vs 13% whisper) but
it is **7x slower than real-time** on this CPU box and eats 3.5 GB — it cannot
serve the calling product. It stays in the driver as a non-realtime
high-accuracy profile.

## STT — Moonshine via sherpa-onnx (int8 ONNX, CPU, 8 threads)

Same pinned corpus, n=40, measured 24 Nov:

| Engine      | Peak RSS | WER (n=40) | RTF mean | RTF p90 | Load | Model files |
|-------------|----------|------------|----------|---------|------|-------------|
| `moon-tiny` | 717 MB   | 9.36%      | 0.049    | 0.082   | 0.7 s | 120 MB |
| `moon-base` | 949 MB   | 8.79%      | 0.065    | 0.088   | 1.2 s | 275 MB |

**Moonshine verdict — new default.** `moon-base` vs the old `fw-tiny` default:
**34% fewer word errors** (8.79% vs 13.3%), 15% faster RTF, still under 1 GB
RSS (949 MB) and chunked-streaming capable through sherpa's stream API.
`moon-tiny` is the <800 MB low-resource profile at 9.36%. fw-tiny stays as the
minimal-footprint fallback; rumble stays as offline hi-acc.

**Reading:** base.en buys nothing on this set — same WER, +122 MB, ~2x RTF.
`fw-tiny` is the current STT driver default. Both are far past real-time on
CPU. These are utterance-level engines, not true streaming: the calling path
gets "partial" results only per VAD segment. The streaming-native candidates
(asr4all-s, VibeASR-BitNet) are next on the bench list; WER on conversational
(noisy, telephony-style) audio still needs its own set — LibriSpeech is the
optimistic bound, stated as such.

## Still open

- ZONOS3-Mini (Zyphra, ~800M, voice cloning): weights exist and it is the
  strongest challenger, but it is not pip/`transformers`-native on
  transformers 5.24 — needs the Zyphra `zonos` package (git-only) or a newer
  transformers port (`Zonos3MiniForConditionalGeneration`). Deferred, not
  benched — honest gap, Pocket TTS remains the shipping engine.
- asr4all-s (ExecuTorch runtime needed) / VibeASR-BitNet (custom GGUF loader) — evaluated, not shipped; Moonshine beat both on availability and already meets the realtime+RAM bar
- Pocket TTS fine-tune path (trainer is public — unexecuted here)
- blind listening eval vs ElevenLabs / Fish Audio
- telephony/noise WER set

## TTS — Kitten TTS 2 Mini (KittenML, apache-2.0) — measured 2026-11-26

82M-param ONNX int8 synthesizer (82.7 MB weights, 16 languages, 118 voices),
run in a torchaudio-free venv. Emotional utterances (excited/calm/sad) rendered
with the stock voices — prosody varies by voice, not controllable per-prompt.

| metric | value |
|---|---|
| weights size | 82.7 MB (int8) / 47.5 MB (int4 available) |
| load time | 0.6 s |
| peak RSS (whole pipeline) | 861 MB |
| RTF steady-state | 0.72–0.91 (real-time) |
| first-utterance RTF | 2.76 (BART g2p warmup) |

**Honest RAM note:** the synth is tiny but kittenml's English frontend loads a
torch BART g2p fallback (~500 MB of the 861 MB peak). Meeting the <500 MB
target needs the pure-ONNX frontend path (espeak-only g2p) — engineered next.
Samples in `demo/voice/kitten/`. Emotions: per-voice prosody only, not
ElevenLabs-style emotional control — Ming-3.0-tts-0.5B (MIT, paralinguistic
control) is the candidate for that tier, benched next.

## STT RAM reduction — measured floors

| engine | peak RSS | WER |
|---|---|---|
| moon-tiny int8 (current small) | 717 MB | (see main table) |
| moon-base int8 | 949 MB | 8.79% |

The runtime floor is sherpa-onnx+onnxruntime itself, not the model weights
(moon-tiny weights are ~60 MB). Path to <500 MB: thread-arena caps +
single-stream decoder config; measurement in progress.
