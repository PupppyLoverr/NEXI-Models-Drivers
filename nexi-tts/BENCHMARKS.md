# Benchmarks and model selection

## Same-text Nano/Mini CPU comparison — 2026-10-13

The [421-character challenge text](tests/fixtures/everyday.txt) includes a
long first sentence, currency, ordinals, percentages, units and a dotted
version. Both profiles use Jasper, English, speed 1.0, two ONNX intra-op threads
and CPU execution on the Xeon 8559C described below. Each row is **three fresh
processes with two warm requests each**; OS file cache was not flushed.
`180` is the earlier bound; **128 is now the default**. `128/80` lowers just
the first chunk to 80 characters, as the HTTP `/stream` route does.

| Profile / max chunk / first chunk | Verified assets | Max complete-process RSS | Median warm first-audio chunk | Median warm RTF |
|---|---:|---:|---:|---:|
| Nano / 180 / 180 | 27.65 MB | 539.99 MB | 2.440 s | 0.213 |
| Nano / **128 / 128** | 27.65 MB | **485.43 MB** | 1.810 s | 0.210 |
| Nano / **128 / 80** | 27.65 MB | **446.24 MB** | **1.247 s** | 0.212 |
| Mini / 180 / 180 | 81.55 MB | 892.24 MB | 4.597 s | 0.443 |
| Mini / **128 / 128** | 81.55 MB | **741.41 MB** | 3.417 s | 0.435 |
| Mini / **128 / 80** | 81.55 MB | **711.95 MB** | **2.349 s** | 0.452 |

Peak RSS includes Python, eSpeak, ONNX Runtime, benchmark and all warm requests.
It is **not** a hard per-request or per-device bound. Shorter chunks reduce
per-chunk activation size and first-audio time, but change waveform/prosody;
this does not establish that the audio sounds better. Full-response RTF shows
Nano is faster on this CPU. Across these six stress configurations, zero
out-of-range samples were measured; that does not guarantee intelligibility.
The short/long baseline below had gentler sentence structure and much lower
peak RSS despite comparable or greater total text length. This is why the
421-character stress case is reported rather than extrapolating from weights.

Evidence is checked in as `results/upgrade/{nano,mini}/{full-chunks,bounded,bounded-stream}/benchmark.json`
and `results/upgrade/{nano,mini}/{short,long,streaming}/benchmark.json`.
The latter short/long/streaming runs used the **older 180-character** limit;
the JSON records the effective limit for every run. Each file records
hardware, model revision/hashes, durations, WAV hashes, per-request waveform
checks and process peak. Only the small JSON is committed, not generated media.

### Real loopback / voice checks

Six opt-in real-inference tests **passed for both profiles** (all eight voices,
speed changes, phonemization challenges, raw PCM streaming, WAV HTTP responses,
invalid inputs and complete-process budget). The model-only tests deny Python
socket creation; the HTTP test allows loopback sockets, prohibits asset-fetch
calls and measures first response bytes on a warm resident instance. Results:

| Profile | `/synthesize` first/complete body | `/stream` first body / complete body |
|---|---:|---:|
| Nano | 7.062 / 7.063 s | **1.170 / 7.394 s** |
| Mini | 13.563 / 13.564 s | **2.156 / 13.472 s** |

This is **one sequential observation per route**: buffered WAV was requested
first, streaming second on the same server. The benchmark above has repeated
fresh-process timings; the HTTP table only proves actual chunked delivery, not
a networked tail-latency distribution. WAV/PCM16, 24 kHz mono, finite audio,
all voice presets and zero out-of-range samples were checked. See
`results/upgrade/{nano,mini}/integration/{smoke,http}.json`; generated WAVs
are uncommitted. An external automatic transcription of a couple of samples
was inconsistent about repetitions; it is **not** a MOS, blind preference test
or reliable basis for a quality ranking. Listen to both samples rather than
inferring quality from parameter count.

Reproduce from `nexi-tts/` after `./setup.sh` and explicit downloads:

```bash
.venv/bin/python -m nexi_tts download --profile nano
.venv/bin/python -m nexi_tts download --profile mini
for profile in nano mini; do
  for limit in 180 128; do
    .venv/bin/python -m nexi_tts.benchmark --profile "$profile" \
      --text-file tests/fixtures/everyday.txt --chunk-chars "$limit" \
      --output-dir "results/reproduce/$profile-$limit" --processes 3 --warm-runs 2
  done
  .venv/bin/python -m nexi_tts.benchmark --profile "$profile" \
    --text-file tests/fixtures/everyday.txt --chunk-chars 128 --first-chunk-chars 80 \
    --output-dir "results/reproduce/$profile-stream" --processes 3 --warm-runs 2
  NEXI_TTS_INTEGRATION=1 NEXI_TTS_PROFILE="$profile" \
    NEXI_TTS_OUTPUT_DIR="results/reproduce/$profile-integration" OPENBLAS_NUM_THREADS=1 \
    .venv/bin/python -m unittest discover -s tests -p test_integration.py -v
done
```

The fresh-process timer begins **inside the worker before driver import**; it
excludes Python startup and the benchmark-module import. `first_chunk_seconds`
starts at request processing, not from process startup. The reported complete
process peak does include bootstrap allocations. See the JSON for exact cold,
warm, load, asset and hardware fields. **Not tested:** listener naturalness
against competing eligible models, non-x86/mobile deployments, or an OS-level
network isolation sandbox. No claim of category leadership is made.

## Original Nano baseline — 2026-10-13 (180-character chunks)

Hardware: **Intel Xeon Platinum 8559C**, 8 logical CPUs available, ~33.65 GB
machine RAM, no GPU used. Linux 6.8 / glibc 2.35 / Python 3.10.12.
ONNX Runtime 1.22.1 CPUExecutionProvider, two intra-op threads, one inter-op
thread, sequential execution, CPU arena/memory-pattern disabled. OpenBLAS one
thread. Jasper, English, speed 1.0; 24 kHz mono PCM16 output.

| Local workload | Short: 128 characters | Long: 1,031 characters |
|---|---:|---:|
| Fresh processes / warm requests per process | 3 / 2 | 1 / 1 |
| Audio duration | 10.15 s | 81.20 s |
| Maximum process peak RSS | 344,571,904 B (344.57 MB / 328.61 MiB) | 349,118,464 B (349.12 MB / 332.95 MiB) |
| Median cold verify/load/frontend | 0.532 s | 0.515 s |
| Median cold import + load → first chunk | 0.917 s | 0.903 s |
| Median cold synthesis + WAV write | 2.155 s | 18.293 s |
| Median warm synthesis + WAV write | 2.186 s | 17.828 s |
| Median warm first chunk | 0.343 s | 0.570 s |
| Cold / warm real-time factor | 0.212 / 0.215 | 0.225 / 0.220 |
| Out-of-range waveform samples | 0 in all requests | 0 in both requests |
| Per-WAV disk bytes | 487,244 | 3,897,644 |

**Memory:** `resource.getrusage(RUSAGE_SELF).ru_maxrss`, converted from KiB on
Linux. Includes Python, ONNX/native runtime, phonemizer and benchmark overhead;
not total machine RAM, not just tensors, and not a prediction for mobile CPUs.
Peak is over each complete fresh process including subsequent warm requests.
Cold means fresh interpreter/session; **OS file cache was not flushed**.
First-chunk timing starts at Python import, not process-spawn/OS boot. Synthesis
timing includes phonemization, model execution and WAV writes, excluding load.
RTF is synthesis seconds / audio seconds; 0.22 is about 4.5× faster than playback.
Long-text statistics have only one process and are a smoke/resource check,
not a statistically robust latency distribution. CPU scheduling affects results.

The benchmark workers replace Python sockets/create_connection with a failing
guard and set offline flags. Actual local inference succeeded with that guard.
This verifies the Python path does not fetch assets; it is **not** an OS-level
network sandbox/packet capture of every native library.

### Disk

- ONNX: **24,369,971 bytes**.
- Voices: **3,278,902 bytes**; config: **688 bytes**; model card: **741 bytes**.
- Total required immutable assets: **27,650,302 bytes** (~27.65 MB).
- Clean runtime virtualenv: **268,498,433 bytes** apparent directory size
  (`du -sb .venv-runtime`), excluding model assets, pip cache and system Python;
  includes pip/setuptools. Platform wheels and filesystem allocation vary.

### Other real checks

- Runtime-only clean install via `VENV_DIR=.venv-runtime ./setup.sh`, then
  `pip check`, `verify`, actual eight-voice inference and HTTP API synthesis.
- Eight presets and Jasper speeds 0.75/1.0/1.25: ten real WAVs, all finite,
  24 kHz PCM16, zero out-of-range samples. Jasper durations 4.967/3.667/2.917 s
  confirm the speed control changes duration in the expected direction.
- That separate voice-sweep process peaked at **321,380,352 bytes**.
- Real loopback API WAV: Bella, 7.833 s, 376,044 bytes. `/health`, `/voices`,
  `/synthesize`, empty text, NaN speed and unsupported language were checked.
- 28 lightweight unit tests passed; two opt-in real-inference tests passed.
- Short first-inference audio transcription matched the complete requested
  sentence. External audio analysis reported clear intelligibility without
  skipped/repeated words, truncation or distortion. This one-sample check is
  **not** a listener MOS, objective corpus WER, or controlled voice-quality
  comparison. Other voices have waveform/inference checks, not blind ratings.

### Evidence and reproduction

Committed JSON: `results/short/benchmark.json`, `results/long/benchmark.json`,
`results/integration/smoke.json`, `results/api.json`. Each benchmark records
hardware, pins, actual timings/RSS, waveform measures, WAV byte-size and SHA-256.
Generated WAVs are ignored, not committed. No byte-identical re-generation is
promised; individual waveform hashes vary across requests.

```bash
cd nexi-tts
./setup.sh
.venv/bin/python -m nexi_tts download
.venv/bin/python -m nexi_tts.benchmark --output-dir results/short --processes 3 --warm-runs 2 --threads 2
.venv/bin/python -m nexi_tts.benchmark --output-dir results/long --long --processes 1 --warm-runs 1 --threads 2
NEXI_TTS_INTEGRATION=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python \
  -m unittest discover -s tests -p test_integration.py -v
```

Delivered audio samples:
- [First Jasper inference](https://app.devin.ai/attachments/9c49a8e1-dc5f-4589-82a1-56bc2f5213d2/first-inference.wav).
- [Bella preset smoke](https://app.devin.ai/attachments/9bc5f827-f724-493b-ae81-34aed0ed258c/Bella-1.0.wav).

## Sourced comparison — published claims, NOT local measurements

Kitten Nano and Mini were run locally; the other models/services were not.
Parameter count is not process RSS.
Unmeasured memory/disk fields are deliberately not filled with estimates.
Provider/hardware-specific timings are **not an apples-to-apples benchmark**.

| Model/service | Published size/features | Published speed / memory | License / adaptation | Local measurement here |
|---|---|---|---|---|
| **Kitten Nano 0.8 int8** [1] | 15M; upstream advertises ~25 MB model; eight English presets | No published RSS used for selection | Apache-2.0 weights/frontend; no verified public Nano trainer | **349 MB max**, assets 27.65 MB, RTF ~0.21–0.23 |
| **Kitten Mini 0.8** [6] | 80M; upstream advertises ~80 MB and calls it highest-quality ONNX profile; eight English presets | Published quality hierarchy is not a listener study | Apache-2.0 weights/frontend; no verified public ONNX trainer | Measured above; assets **81.55 MB**; not a NEXI fine-tune |
| Kokoro-82M [2] | 82M; multilingual language-code frontend/preset catalog | Not measured; model card quality claims are not a common local test | Apache-2.0 weights; this session did not verify a public trainer | Not run |
| Pocket TTS [3] | 100M base; current release also has larger/deeper variants; streaming, six listed languages, voice cloning | Upstream ~200 ms first chunk, ~6× real time on MacBook Air M4, two cores; local RSS unknown | MIT code, current card CC-BY-4.0 weights, per-voice licenses; released trainer/finetune/distillation code | Not run; no <1 GB promise |
| Supertonic 3 [4] | ~99M across ONNX assets; 31 languages, presets/expression tags | Upstream CPU latency/memory charts; no numeric values inferred from chart images | MIT sample code, **OpenRAIL-M weights**; archive has no ongoing updates/support; no verified released trainer here | Not run |
| ElevenLabs Flash v2.5 [5] | Hosted proprietary service; 32 languages | Provider publishes ~75 ms model latency; excludes network/application overhead; local RAM inapplicable | Proprietary service terms, not downloadable open-source weights | No API called; no quality-parity claim |

**Selection:** Nano provides the smallest verified assets and a measured full
CPU process comfortably below 500 MB for the **original** short/long workloads;
larger sentences exposed higher peaks, so the new default limits chunks to 128.
Mini adds the upstream quality-first option within the tested <1 GB target,
but uses more memory and compute; we did not establish a blinded preference or
category-wide #1 ranking. Pocket is more featureful and genuinely
trainable, but PyTorch/runtime and larger teacher profiles were not verified
against the memory budget. Supertonic's multilingual feature set is attractive,
but archival status and restricted weight license require an explicit product
decision. Kokoro is a credible larger comparison, not a second profile we
pretend to have tested. KittenTTS 2 is a different, substantially larger model
generation; do not substitute its HEAD runtime for Nano's tiny footprint.

## Sources (checked 2026-10-13)

1. [Pinned Kitten Nano card/config/assets](https://huggingface.co/KittenML/kitten-tts-nano-0.8-int8/tree/84781d74e29ee25217551556398b42f80593a813),
   [compatible ONNX frontend](https://github.com/KittenML/KittenTTS/blob/0c61f684b54fe962e4b7c2fa0285ed75f64ad402/kittentts/onnx_model.py).
2. [Official Kokoro-82M model card](https://huggingface.co/hexgrad/Kokoro-82M).
3. [Pinned Pocket repository](https://github.com/kyutai-labs/pocket-tts/tree/b94db177bc0f77517d9b124843e25605d6f9aed8),
   [current official model card](https://huggingface.co/kyutai/pocket-tts),
   [training guide](https://github.com/kyutai-labs/pocket-tts/blob/b94db177bc0f77517d9b124843e25605d6f9aed8/training/README.md).
4. [Archived source and migration warning](https://github.com/supertone-oss-archive/supertonic),
   [pinned Supertonic 3 card](https://huggingface.co/supertone-oss-archive/supertonic-3/blob/aafc6e32416a594460b32413efc49d7fe4ce6d46/README.md).
   Card links to hosted Voice Builder/demos may be historical; the archive
   explicitly excludes those services. No paid service is a dependency here.
5. [ElevenLabs official model documentation](https://elevenlabs.io/docs/overview/models),
   [Flash v2.5 product page](https://elevenlabs.io/flash). Published claims only;
   some documentation endpoints restrict automated fetches.
6. [Pinned Mini card/config/assets](https://huggingface.co/KittenML/kitten-tts-mini-0.8/tree/c02725660cea441db4c383af69f1f26f5cd00947),
   [official ONNX model comparison](https://kittenml-kittentts.mintlify.app/models/overview).
   The quality labels there are upstream claims, not our independent ratings.

## Independent review reproduction

`results/review/{nano,mini}/{smoke,http}.json` preserves independent real CPU
checks for all eight voices, speed controls, normalization and WAV/PCM HTTP.
The six opt-in integration tests passed on each profile, including a complete
process-RSS budget assertion. `results/review/integrated/` records the repeat
after branch consolidation. These are functionality/waveform checks and
single-run timings, not blinded listening scores or a new performance ranking.
See the [review snapshot](../common/bench/reviews/modalities-2026-10-13.md) for
remaining fine-tuning and deployment boundaries.
