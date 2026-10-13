# Use cases and explicit non-goals

## Suitable today

- **Private push-to-transcribe backend:** a caller records a short consented WAV,
  submits it to the warm loopback API, and asks the user to review the text.
  Works offline after package/model setup; no cloud API key or usage bill.
- **Batch notes and accessibility prototypes:** CLI WAV -> text/segment JSON,
  optionally word timestamps. Test your actual accents, noise and microphone;
  the public demo is not evidence of accessibility-grade reliability.
- **Developer-name vocabulary bias:** pass short `--hotwords`/`X-STT-Hotwords`
  hints. This is a soft bias; verify spellings and keep sensitive hints local.
- **Pause-delimited dictation integration:** feed explicit raw PCM16 mono 16 kHz
  into `dictate` or `dictation.stream`, receiving final utterances with absolute
  timestamps. Audio buffering is bounded; host capture, permissions and a device
  overrun policy remain the host's responsibility. No live partial text is emitted.
- **Domain adaptation experiments:** collect recordings/transcripts with consent,
  split by speaker into train/held-out sets, train in the torch venv, export int8,
  evaluate base and tuned models using the same WER normalizer. Keep training
  reports/transcripts private; do not claim gains from training-set WER.
- **Embedding in a larger local product:** reuse the `Driver` Python class for
  a warm instance, or call the loopback API from a native application. The
  upstream tiny/base choice can be changed by selecting a different local export.

## Microphone acquisition is outside this driver

No GUI, key logger, keyboard hook, app scraping, clipboard rewriting or implicit
microphone capture is installed. A native host can handle push-to-talk, user
permission, endpointing and insertion. An optional Linux ALSA recording recipe,
**not tested here because no microphone device is available**, is:

```bash
ffmpeg -f alsa -i default -t 20 -ac 1 -ar 16000 -c:a pcm_s16le dictation.wav
.venv/bin/python -m nexi_stt transcribe dictation.wav --model models/tiny.en --format text
# Optional live PCM pipeline, likewise UNTESTED with a real microphone:
ffmpeg -f alsa -i default -ac 1 -ar 16000 -f s16le - | \
  .venv/bin/python -m nexi_stt dictate --model models/tiny.en --words
```

Use explicit user initiation and consent. Device/input names and permissions vary
by OS; FFmpeg is optional for capture and **not needed for this driver's inference**.

## Not a Wispr Flow replacement product

Wispr Flow includes microphone/system-wide integration, account syncing,
personalization and contextual text editing. This delivery only covers local ASR
and file/PCM-stream/HTTP interfaces. It has no app-specific style, LLM post-editing,
cross-device sync, auto-paste, live partial captions, speaker identification,
mobile packaging or desktop accessibility integration. Do not call its warm
file latency “end-to-end keyboard dictation latency.” Whisper is not a native
streaming recognizer; Moonshine/sherpa need separate integration and testing.

## Limits and deployment safeguards

- English-only default checkpoints/decoding. Other languages need other local
  weights plus driver changes and tests; translation is not supported.
- 120-second/10-MiB WAV cap; PCM input has bounded pause/length segmentation and
  timestamp offsets, but hard cuts may lose boundary words. Meeting-quality
  transcription/diarization and cross-utterance context are not implemented.
- VAD reduces but does not eliminate hallucination; it can omit soft utterances.
  Test pauses, breaths, distant/noisy speech and domain terms, not just silence.
- A 0% WER result on 22 well-known words does not establish model accuracy.
  Spoken punctuation and stylistic corrections are not normalized text editing.
- LibriSpeech read-speech subsets and synthetic controls are not a comprehensive
  dictation benchmark. Beam=5 is optional, not an automatic accuracy upgrade.
- Do not use unreviewed transcripts for clinical, legal or other high-stakes
  decisions. Probabilities are not calibrated safety scores.
- The API trusts local clients and has no auth. Keep it loopback-only; do not
  publish it. All local users may be able to access the running process.
- Models and dependencies have licence/notice obligations; data has separate
  privacy and consent requirements. Avoid covert recording/surveillance.
- Measured Xeon performance is not a phone/laptop battery/latency/RAM guarantee.
  Validate your actual machine and CPU int8 support before shipping.
