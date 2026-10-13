# Use cases and integration limits

## Good fits

1. **Offline assistant responses.** Reuse one Python `Synthesizer` or the
   resident loopback server; stream sentence chunks to your playback device.
   Use Nano for the smallest footprint, Mini for quality-first use, and Python
   `first_chunk_chars=80` or HTTP `/stream` to start a long answer earlier.
   Suitable for English answers when network privacy matters. Streaming clients
   must check successful end-of-transfer, not play an incomplete response as final.
2. **Accessible notifications/read-aloud.** Use a preset and moderate speed,
   spell out ambiguous dates, and keep pronunciation-critical names in a
   caller-managed pronunciation/normalization layer. It does not implement
   SSML, a phonetic lexicon API or guaranteed screen-reader semantics. Dollar,
   pound and euro amounts, percentages, ordinals and selected units are expanded.
3. **Small game/device narration.** Pre-generate WAVs on CPU; cache them by
   text/voice/speed/model revision. Fixed voices reduce variability and avoid
   voice-cloning consent/data workflows.
4. **Long-form local rendering.** Use `to_file` or CLI `--text-file`, which
   write bounded chunks rather than retaining the whole audio. Review chunk
   joins and prosody before publishing a narration.

## Example: reuse one loaded model

```python
from nexi_tts.driver import Synthesizer

tts = Synthesizer(threads=2)
for index, text in enumerate(["Your timer is ready.", "The download is complete."]):
    tts.to_file(text, f"notification-{index}.wav", voice="Rosie", speed=1)
```

Keep output directories under the application's control. The local API only
returns audio bytes and cannot request arbitrary output paths. Do not expose
it over a LAN or add a public proxy without authentication and stronger limits.

## Not provided

- ElevenLabs-equivalent expressiveness, emotional direction or studio quality.
- Voice cloning, custom-voice fine-tunes or trained NEXI weights.
- Multilingual speech; unsupported language flags fail explicitly.
- Audio playback, SSML, phoneme-input API, WebSocket transport, within-sentence
  token streaming, interruption/cancellation or concurrent multi-user service.
- iOS/Android packaging, ARM/mobile/Windows/macOS runtime measurements. The
  upstream loader advertises several platforms, but our verified deployment
  is Linux x86-64 only.

For multilingual/custom-voice requirements, first evaluate the separately
licensed alternatives in BENCHMARKS.md. Do not silently switch to a paid cloud
service, a much larger runtime, or unsupported reverse-engineered training.

## Evaluating the "best in category" goal

The target category is **fully local English CPU TTS with under 1 GB measured
process RSS**, not hosted expressive/cloning services. The current comparison
supplies same-text audio and complete-process measurements for Nano and Mini.
It does not establish superiority over Kokoro, Pocket, Piper or Supertonic.
Before advertising a #1 result, freeze a common hardware/corpus/license budget,
run all eligible alternatives, and conduct randomized, blinded listener ratings
for naturalness, intelligibility, pronunciation and chunk joins. Evaluate cold
and resident-model latency separately. A larger parameter count, fewer clipping
samples or a faster RTF is not a substitute for a voice-quality study.
