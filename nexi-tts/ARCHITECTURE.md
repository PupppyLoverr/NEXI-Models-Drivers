# Architecture, provenance and adaptation

## Delivered inference path

```text
explicit download → exact byte-size + SHA-256 checks → local immutable assets
UTF-8 text → bounded English normalization → punctuation-preserving chunks
→ bundled eSpeak NG / phonemizer → Kitten 0.8 symbol IDs + boundary tokens
→ ONNX Runtime CPU + preset style + speed prior → float32 mono waveform
→ upstream 5,000-sample tail trim → PCM16 WAV (24 kHz)
```

The package does not call a hosted TTS API. Only `nexi_tts.assets.download`
accesses the network. Loading, speaking, serving and benchmarking never fetch
missing models. Hash failures are explicit local errors. Asset downloads use
bounded temporary files, verify before atomic replacement, reuse valid files,
and leave an existing file untouched if replacement fails. A local attacker
with write access can still change files between verification and loading;
this is not a sandbox for untrusted model directories.

### Generation and memory

- Sequential ONNX CPU session; default two intra-op threads, one inter-op
  thread; CPU arena and memory-pattern retention disabled.
- Local voice NPZ loaded with `allow_pickle=False`. Model inputs are int64
  `input_ids`, float32 `style`, and float32 `speed`. Style index is the bounded
  text length; speed includes the upstream preset prior when present (Mini's
  pinned config has no speed priors, so its multiplier is 1.0).
- One lock serializes phonemization/model calls per synthesizer instance.
  Reuse one synthesizer instead of constructing one per utterance. eSpeak's
  library configuration is process-wide; multiple independent instances are
  not a promised concurrent inference configuration.
- Input ≤20,000 raw **and expanded** characters; default chunk ≤128 characters; phoneme payload ≤510
  tokens before boundary markers. Sentence/word splits normally preserve
  words; a single word exceeding the chunk bound must be split. `first_chunk_chars`
  optionally lowers only the first chunk's limit, reducing time to first audio
  at a potential prosody cost. Common titles, signed numbers, decimal digits,
  ordinals, percentages, three currencies and selected case-sensitive units
  are normalized. Dates, phone numbers and ambiguous identifiers still need
  caller-side disambiguation; dotted versions/addresses are preserved rather
  than partially expanded. Dollar signs mean USD, pound signs GBP, euro signs EUR.
  Configurable chunks (80–180 characters) trade prosody against memory/latency.
  The previous 180-character default produced substantially higher stress-test
  RSS. This is bounded input handling, not a hard memory quota or a claim that
  all voices/speeds/text on every platform consume the same RAM.
- `iter_audio` and `to_file` retain one audio chunk at a time. `synthesize`
  concatenates the whole waveform and therefore uses memory proportional to
  output duration. HTTP limits text to 2,000 characters and is sequential.
- `to_file` writes a sibling temporary WAV and replaces the destination only
  after complete success. PCM conversion clamps to [-1,1] to prevent integer
  overflow, but does not promise that every arbitrary model output is free of
  saturation; benchmark JSON counts raw out-of-range samples.
- Preset voices, English only, speed 0.5–2.0. NaN/infinity, booleans, unknown
  voices, other languages, empty text and non-finite audio are rejected.
- No autoplay/playback dependency. Python callers may play yielded chunks;
  loopback HTTP clients can consume chunked raw PCM through `/stream`.

### API boundary

`HTTPServer` binds **127.0.0.1 only**. No authentication or public exposure is
provided. Each connection has a 15-second socket timeout. JSON bodies are
limited to 32 KiB; text to 2,000 characters; chunked transfer and unknown fields
are rejected. Responses are WAV bytes, raw PCM chunks, or JSON errors. Request content is not
logged. This is a trusted local-process interface, not a hardened internet
service or a multi-tenant resource scheduler. In-process Python calls are also
a trusted typed API, not a parser for arbitrary hostile Python objects.

`POST /stream` uses the same request fields as `/synthesize`, but lowers the
first chunk bound to 80 characters. It computes and validates that chunk before
success headers, then sends HTTP/1.1 chunked PCM16LE (24 kHz mono). A late model
failure closes the connection **without** a successful terminator; clients must
recognize incomplete transfer. Connections close after each response, so idle
HTTP/1.1 keep-alive clients do not monopolize this sequential server. A slow
consumer can still block it until the socket timeout. Streaming is a local
transport, not authentication, CORS, concurrent scheduling or native playback.

## Model and source pinning

Do **not** install the current KittenTTS HEAD package and assume it matches
these legacy ONNX weights. The current repository documents a different
generation (KittenTTS 2); its package metadata/frontends need not match 0.8.
We port the documented 0.8 ONNX contract, without upstream spaCy/PyTorch:

- [Compatible frontend source](https://github.com/KittenML/KittenTTS/blob/0c61f684b54fe962e4b7c2fa0285ed75f64ad402/kittentts/onnx_model.py),
  commit `0c61f684b54fe962e4b7c2fa0285ed75f64ad402`.
- [Nano model/config/card](https://huggingface.co/KittenML/kitten-tts-nano-0.8-int8/tree/84781d74e29ee25217551556398b42f80593a813),
  revision `84781d74e29ee25217551556398b42f80593a813`.
- [Mini model/config/card](https://huggingface.co/KittenML/kitten-tts-mini-0.8/tree/c02725660cea441db4c383af69f1f26f5cd00947),
  revision `c02725660cea441db4c383af69f1f26f5cd00947`. The ONNX2 input contract
  is shared, but its voice embeddings and model file are separately pinned.
- `--profile nano` (compatible default) and `--profile mini` select separate
  manifests/directories. Every load verifies the selected profile; no fallback,
  runtime model-network request or accidental shared voice archive occurs.
- Exact sizes and SHA-256 values are maintained in `nexi_tts/assets.py` and
  reproduced in the benchmark JSON. Dependencies use exact versions and
  `pip --require-hashes` in `setup.sh`. Wheel/platform choice can vary by OS;
  the measured environment is Python 3.10.12, Linux x86-64.

The frontend deliberately changes chunking, lightweight normalization and
validation. It is an adapter for upstream weights, not a training run or a
claim of bit-identical upstream text normalization. WAV hashes are evidence
of particular generated artifacts, not deterministic golden outputs.

## License inventory

Apache-2.0 covers this driver source, the adapted Kitten frontend and the
upstream model card's declared weights license. It does **not** make the full
dependency bundle Apache-only. Redistribution needs all applicable notices,
source/copyleft obligations and the actual wheel's bundled third-party
licenses. This inventory is not legal advice.

| Direct component | Version / source | License |
|---|---|---|
| Kitten nano-int8 / Mini weights + frontend | revisions above | Apache-2.0 |
| NumPy | 1.26.4 | BSD-3-Clause; wheels include additional numerical-library notices |
| ONNX Runtime | 1.22.1 | MIT; bundled third-party notices also apply |
| phonemizer | 3.3.0 | GPL-3.0-or-later |
| espeakng-loader wrapper | 0.2.4 | MIT in [upstream source](https://github.com/thewh1teagle/espeakng-loader/blob/main/LICENSE) |
| bundled eSpeak NG binary/data | provided by loader wheel | GPL-3.0; see [eSpeak NG COPYING](https://github.com/espeak-ng/espeak-ng/blob/1.52.0/COPYING) |
| num2words | 0.5.14 | LGPL-2.1 (installed COPYING) |

Locked transitive Python dependencies (license metadata checked from the clean
installed environment):

- MIT: attrs, charset-normalizer, coloredlogs, dlinfo, docopt, humanfriendly,
  jsonschema, jsonschema-specifications, language-tags, pyparsing, referencing,
  rpds-py, six, urllib3.
- BSD-family: Babel, colorama, idna, isodate, joblib, mpmath, protobuf, RDFLib,
  SymPy.
- Apache-2.0: csvw, flatbuffers, regex, requests, rfc3986, segments.
- Apache-2.0/BSD alternatives: packaging, python-dateutil, uritemplate.
- MPL-2.0: certifi. PSF-2.0: typing-extensions.
- Development only: Ruff (MIT), mypy/mypy-extensions (MIT), tomli (MIT on
  Python <3.11). Pip/setuptools and the Python runtime have their own licenses.

The installed espeakng-loader wheel does not declare its wrapper license in
package metadata; retain the upstream MIT notice and audit the bundled GPL
binary/data before shipping a binary application. Do not assume suitability
for an Apache-only/closed-source bundled distribution just from the model card.

## Fine-tuning status: NOT delivered for Nano or Mini

There is no verified released Kitten ONNX 0.8 training/fine-tuning pipeline in the
pinned upstream materials. An ONNX inference graph and voice array are not a
trainer. We did not reverse-engineer a speculative trainer, alter embeddings
and call it a fine-tune, or relabel upstream weights. No training data, GPU,
custom speaker weights or trained adapter is included. Mini is an additional
upstream checkpoint, not an in-house fine-tune or measured human-quality uplift.

### Legitimate separate route: Pocket TTS training

Pocket TTS now releases **actual training code**. It is a different model,
**not** an adapter that can load into this Kitten ONNX driver. This guide is
source-verified, **not executed training** on this CPU-only VM:

- [Pinned training guide](https://github.com/kyutai-labs/pocket-tts/blob/b94db177bc0f77517d9b124843e25605d6f9aed8/training/README.md).
- [Same-language fine-tuning config](https://github.com/kyutai-labs/pocket-tts/blob/b94db177bc0f77517d9b124843e25605d6f9aed8/training/configs/finetune.yaml).
- [New-language adaptation config](https://github.com/kyutai-labs/pocket-tts/blob/b94db177bc0f77517d9b124843e25605d6f9aed8/training/configs/finetune_language.yaml).
- [24-layer teacher → 6-layer student distillation](https://github.com/kyutai-labs/pocket-tts/blob/b94db177bc0f77517d9b124843e25605d6f9aed8/training/configs/depth_distill.yaml).

Requirements in the pinned guide: Linux, Python 3.10+, uv, NVIDIA GPU.
Default batch wants ~56 GB VRAM; the documented consumer alternative is
`batch_size: 16`, `grad_accum_steps: 4` at ~16 GB VRAM. Prepared audio takes
~60 GB per 1,000 hours. The **scratch-training demo**, not a universal minimum
for speaker adaptation, uses 200 hours for intelligible speech and suggests
2,000+ hours for production-comparable quality. Fine-tuning still needs
licensed paired audio/transcripts and word alignments; new-language adaptation
also needs a fitted tokenizer. Small-data quality is not established here.

Source-backed commands for an independent GPU workstation (network/downloads,
disk and GPU costs are **not** part of this driver's setup):

```bash
git clone https://github.com/kyutai-labs/pocket-tts.git pocket-tts-training
cd pocket-tts-training
git checkout b94db177bc0f77517d9b124843e25605d6f9aed8
uv sync
# Example licensed-data preparation, about 15 GB for the 200h example:
uv run training/scripts/prepare_data.py --hours 200
cp training/configs/finetune.yaml training/configs/finetune_local.yaml
uv run python - <<'PY'
from pathlib import Path
import yaml
path = Path('training/configs/finetune_local.yaml')
config = yaml.safe_load(path.read_text())
config['data']['train_jsonl'] = 'data/hifitts2_200h/train_aligned.jsonl'
config['data']['valid_jsonl'] = 'data/hifitts2_200h/valid_aligned.jsonl'
config['batch_size'] = 16
config['grad_accum_steps'] = 4
path.write_text(yaml.safe_dump(config))
PY
uv run training/train.py training/configs/finetune_local.yaml
# After a successful run, choose a checkpoint that actually exists:
uv run pocket-tts generate \
  --config pocket_tts/config/english_2026-04_24l.yaml \
  --checkpoint runs/finetune/checkpoint_00020000.pt \
  --voice your_consented_speaker.wav --text "Hello there."
```

For your own voice/domain, substitute your licensed, aligned manifests and
hold out evaluation speakers/text. The reference fine-tune targets the larger
24-layer model, **not automatically the 100M tiny student**. The released
distillation config expects a separately trained teacher checkpoint. Training
and eventual inference memory/quality must be re-measured; this guide makes no
<1 GB guarantee for Pocket TTS.

Pocket's [code license](https://github.com/kyutai-labs/pocket-tts/blob/b94db177bc0f77517d9b124843e25605d6f9aed8/LICENSE)
is MIT; its current [model card](https://huggingface.co/kyutai/pocket-tts)
declares **CC-BY-4.0**, with gated consent/use conditions for cloning weights.
Voice prompts have [separate source licenses](https://huggingface.co/kyutai/tts-voices).
Use consented recordings; do not impersonate people. Dataset, teacher, codec,
tokenizer and derived-model licenses must be checked independently. Pinning the
source does not itself lock uv dependencies or dataset revisions; retain the
resulting lockfile, downloaded dataset manifests/hashes and checkpoints for
your training run. Official model paths in the selected YAML are revision-pinned.
