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
high-accuracy profile; `fw-tiny` remains the real-time default.

**Reading:** base.en buys nothing on this set — same WER, +122 MB, ~2x RTF.
`fw-tiny` is the current STT driver default. Both are far past real-time on
CPU. These are utterance-level engines, not true streaming: the calling path
gets "partial" results only per VAD segment. The streaming-native candidates
(asr4all-s, VibeASR-BitNet) are next on the bench list; WER on conversational
(noisy, telephony-style) audio still needs its own set — LibriSpeech is the
optimistic bound, stated as such.

## Still open

- asr4all-s / VibeASR-BitNet benchmark + adapter
- Pocket TTS fine-tune path (trainer is public — unexecuted here)
- blind listening eval vs ElevenLabs / Fish Audio
- telephony/noise WER set
