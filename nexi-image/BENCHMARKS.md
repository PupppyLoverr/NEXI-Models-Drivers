# Benchmarks: measured locally versus published upstream

## Three native tiers

The new generation/editing profiles are documented in [TIERS.md](TIERS.md).
Their native quantization/disk-backed measurements supersede the original
Diffusers path's RAM-target failure **for those tested native profiles only**.
The original measurements below remain valid for the original Python/default
SD1.5 paths, not a statement that every new variant fails the target.

Same host as below: Xeon Platinum 8559C, four threads, CPU only, ~32 GB RAM,
native `d637cfb`, disk-backed params, flash attention and VAE tiling. Runs were
serial, each a fresh native process with warm model files after checksum
verification. "Bound" is the parent's peak RSS plus the native child's `wait4`
peak (a conservative upper bound, not simultaneous PSS); OS, page cache and
other apps are excluded. Model bytes are runtime files only.

| Tier / run | Size | Wall incl. verify | Child peak | Bound | Target | Model bytes |
|---|---:|---:|---:|---:|---:|---:|
| small generate | 256², 10 steps | 69.65s | 566,984,704 | 591,007,744 | 1,000,000,000 | 586,432,556 |
| small masked img2img, strength 0.8 | 256² | 62.63s | 567,513,088 | 592,928,768 | 1,000,000,000 | 586,432,556 |
| medium generate | 512², 4 steps | 151.50s | 3,253,653,504 | 3,280,564,224 | 4,000,000,000 | 4,180,187,168 |
| medium masked regenerate, strength 1 | 512² | 202.54s | 3,257,712,640 | 3,288,256,512 | 4,000,000,000 | 4,180,187,168 |
| best generate | 512², 4 steps | 349.58s | 4,808,568,832 | 4,835,377,152 | 6,000,000,000 | 7,047,429,844 |
| best instruction edit, one reference | 512² | 553.64s | 5,110,194,176 | 5,138,604,032 | 6,000,000,000 | 7,047,429,844 |
| best instruction edit plus mask | 512² | 578.04s | 5,106,216,960 | 5,137,698,816 | 6,000,000,000 | 7,047,429,844 |

All seven runs were within their workload targets under these boundaries. A repeat
generation for each tier (seed 42, same prompt/config) produced identical RGB
pixel hashes; small/medium PNG files were byte-identical too. Repeat peaks were
within 0.1% of the first run. Masked lower-tier edits changed zero pixels where
the mask was black (small: 0/28,287; medium and best: 0/113,919) after compositing.

Qualitative observations, one prompt each, not a benchmark score:

- small: generated a red bowl-like vessel rather than a clear mug. Masked
  editing with strength 0.8 did **not** turn it blue and introduced a grainy
  patch. Treat small editing as weak.
- medium: generated a recognisable red mug with handle and a "NEXI" label, plus
  garbled small print. Masked strength-one regeneration produced a pale blue mug
  but a visible rectangular seam and duplicated table/background structure. Use
  tight, object-shaped masks; a hard box mask is a poor default.
- best: generated a clean red mug with a legible "NEXI" plate. The unmasked
  instruction edit changed it to blue while keeping shape, plate, table and
  lighting closely aligned. This is the only tier that showed convincing editing.
  The optional rectangular mask preserved all black-mask pixels exactly; a
  fragment of the original red handle remained outside the mask, demonstrating
  why selections must cover the whole object.

Not measured: cold cache, other resolutions, multiple references, mobile/GPU,
a prompt suite, or any comparison with OpenAI/Nano Banana outputs. Reproduce
with `.venv/bin/python -m nexi_image.benchmark_tiers` after provisioning.

Portable measured reports, conversion receipts and hash/pixel assertions are
committed under [evidence/tiers/](evidence/tiers/), including
[checks.json](evidence/tiers/checks.json). Input paths are reduced to basenames;
their SHA-256 hashes are unchanged. Generated PNGs are not committed and remain
in `outputs/`; the before/after best-tier example is delivered separately.

## Original baseline result and interpretation

**The original baseline did not meet the strict 1 GB total-RAM goal.** The smallest observed BK worker
peak was **1,082,589,184 bytes (1.008 GiB)** with sequential CFG on the cup
prompt. The apple reached 1,085,317,120 bytes and its repeat reached
1,142,714,368 bytes. A live Python parent, OS and filesystem cache are
additional. Inference weight files fit below 1 GB, but installed dependencies
and working memory do not. No sub-1-GB VRAM statistic is used as system RAM.

Real pretrained model output was generated on CPU. BK produced a recognisable
red apple. Its lighthouse prompt produced a watercolor ocean/cliff/sunset scene
but no obvious lighthouse. These are limited qualitative observations, not a
FID/CLIP benchmark or a claim of cloud-tool-equivalent quality. Native standard
SD1.5 generated a recognisable apple at ten steps; four-step LCM produced severe
stripe/grid artifacts and is not recommended as the default.

## Hardware and measurement boundaries

- Date: 2026-10-13. Linux 6.8.0-1061-aws, x86_64, Python 3.11.
- Intel Xeon Platinum 8559C, eight exposed vCPUs, four inference threads, no GPU.
  The VM class has ~32 GB RAM; it is not a phone or a low-memory target device.
- Torch 2.8.0+cpu, Diffusers 0.35.1, Transformers 4.56.2. Native source
  `d637cfb935feb2254898a8f1524046c958f3df80`, CPU Release build/CMake 3.31.6.
- Each BK component starts a **fresh process**; RSS is Linux
  `resource.getrusage(RUSAGE_SELF).ru_maxrss * 1024`, including imports, load,
  actual denoising/decoding and temporary allocations. Reported maximum is the
  largest worker, **not simultaneous parent+child RSS**, process-tree memory,
  free-RAM requirement, proportional set size, or device-total RAM.
- Native RSS is `wait4` child `ru_maxrss * 1024`, or separately GNU `/usr/bin/time
  -v` on the actual executable. These measure full inference, not model load
  alone. GNU time's KiB are explicitly converted to bytes in the table.
- Driver latency includes integrity verification and all fresh workers;
  component timings include their framework imports. Direct native executable
  timing excludes the Python wrapper's checksum pass.
- **All runs have warm/partially warm OS page cache.** Explicit downloads and
  full SHA-256 verification read the model files. No OS cache-dropping/root
  operation was performed. “Fresh process” does not mean cold disk. No true
  cold-cache or statistical p50/p95 local result is claimed.
- Some repeat/smoke runs overlapped other inference; they are marked below.
  RSS and latency vary with allocator state and host contention. Do not treat
  one smaller peak as a memory upper bound or a guaranteed minimum requirement.

## Local measured results

256×256, batch one, seed 42, four CPU threads throughout. Primary BK uses
DDIM/TAESD, guidance 7.5. The first implementation batched CFG; the final default
uses two sequential CFG branches. For historical evidence lacking a
`batched_guidance` config key, the implementation was implicitly batched.

| Profile / actual run | Steps / dtype | Full wall seconds | Peak process RSS bytes | Inference model disk bytes | Evidence / qualifications |
|---|---|---:|---:|---:|---|
| BK apple, final sequential CFG | 10 / FP16 | 58.94 | 1,085,317,120 | 904,340,286 | `evidence/bk-apple-sequential.json`; GNU time 59.02s, 1,059,880 KiB; no concurrent inference |
| BK apple, sequential repeat | 10 / FP16 | 69.82 | 1,142,714,368 | 904,340,286 | `evidence/bk-apple-sequential-repeat.json`; same PNG hash; no concurrent inference |
| BK cup, controlled prompt change | 10 / FP16 | 57.96 | 1,082,589,184 | 904,340,286 | `evidence/bk-blue-mug.json`; same seed/dtype/sampler/CFG/steps as sequential apple |
| BK apple, batched CFG | 10 / FP16 | 41.15 | 1,145,073,664 | 904,340,286 | `evidence/bk-apple-fp16.json`; older batched path; fresh workers |
| BK lighthouse, batched CFG | 10 / BF16 | 37.71 | 1,616,777,216 | 904,340,286 | `evidence/bk-lighthouse.json`; higher RAM, missing requested object |
| BK apple, batched repeat | 10 / FP16 | 83.25 | 1,144,979,456 | 904,340,286 | `evidence/bk-apple-repeat.json`; concurrent native inference, **not a speed benchmark** |
| Native SD1.5 Q4/FA/disk, standard Euler ancestral | 10 / quantized U-Net | 152.02 | 1,455,247,360 | 1,891,605,632 | Direct GNU time, `evidence/native-standard-direct-gnu-time.txt`; excludes wrapper verification; recognisable apple |
| Native standard, final driver | 10 / quantized U-Net | 129.97 | 1,454,817,280 | 1,891,605,632 | `evidence/native-standard.json`; includes wrapper verification; fresh process, no concurrent inference |
| Native SD1.5 Q4/FA/disk + LCM | 4 / quantized U-Net | 45.32 | 1,563,303,936 | 1,891,605,632 | Direct GNU time, `evidence/native-apple-gnu-time.txt`; severe grid artifacts |
| Native lighthouse LCM, wrapper | 4 / quantized U-Net | 81.86 | 1,562,857,472 | 1,891,605,632 | `evidence/native-lighthouse-contended.json`; concurrent inference; severe stripes; **not a speed benchmark** |

The native package includes the optional LCM adapter even for standard runs.
The Q4 GGUF alone is 1,747,190,784 bytes; CLIP/VAE tensors in that file are FP16,
not Q4. Full TAESD adds 9,793,292 bytes; LCM adds 134,621,556 bytes. The native
build and executable are additional. The Python `.venv` directory measured
1,205,520,090 apparent bytes on this host (including pinned native CMake);
disk totals above count **model assets only**, not application/dependency/cache
storage. Optional original VAE training assets bring BK to 1,071,676,179 bytes.

### Adaptation execution, not quality proof

One real rank-two LoRA optimizer update at 128px, batch one, FP32, one local
synthetic image/caption: 27.09s including precomputation, 2,263,867,392 bytes
trainer peak RSS, loss 0.52126145, 215,808 trainable parameters, 883,048-byte
adapter. Precompute workers' peaks are recorded separately. A subsequent
four-step generation successfully loaded it: 62.01s/1,138,540,544-byte worker
peak under concurrency (`evidence/adapter-inference-smoke.json`). This does
**not** demonstrate learned style, usefulness or generalization. No trained
adapter or copyrighted dataset is shipped.

## Determinism and prompt evidence

- Final sequential apple and fresh-process repeat: both PNG SHA-256
  `d014c639468f8cb5063252db5e503402b3d180b05ab0f0d061116c5fdd2573e9`.
- Historical batched apple and repeat: both
  `bf77152ae0e3b5165523a071a54b1ee15794c0a667df1725a94b3ac5fd9fac34`.
- BF16 lighthouse:
  `f092682222e6cb73d9a04b78caeefafecdf10ff8ddef5ca7a83cef496742d5d7`.

- Controlled prompt change: the final FP16/sequential/seed42/ten-step apple
  configuration generated a blue-striped cup when only the prompt changed to
  “A photo of a blue ceramic coffee mug on a wooden table, still life, studio
  lighting”. PNG SHA-256
  `0772a71566ded0b1dee87a7561343227778e70fc298a9fae0bc9524cc4bce9c2`.
  The cup lacked an obvious mug handle and was not uniformly blue. This proves
  prompt responsiveness on these two examples, not exact fidelity.

The initial lighthouse/apple comparison also changed dtype. There is no
controlled **quantitative** prompt-adherence score or broad quality study.
Seed reproducibility is established only for the tested pinned host/config.
Actual PNGs are delivered separately, not committed. Their hashes and exact
prompts/configs are in the JSON. Native standard output is a different model and
its seed is not expected to match BK.
The two native standard runs produced identical RGB pixels (checked with PIL
`ImageChops.difference`), while PNG file hashes differ because sd-cli embeds
generation metadata including changed model/output paths. Native output-file
hash identity is not promised when that embedded provenance changes.

## Published reports: not our measurements

Sources accessed 2026-10-13. Hardware, dataset, scheduler and quality conditions
differ. “Unknown” means the cited source did not provide a comparable number;
we do not infer RAM from parameter count, download size or GPU VRAM.

| Model / source | Published footprint | Published RAM | Published speed or quality / conditions |
|---|---|---|---|
| [BK-SDM-Tiny][bk] | 0.33B U-Net / 0.50B complete original SDM parameters; download bytes not reported in card | **Unknown** | FID 17.12, IS 30.09, CLIP 0.2653; 30K MS-COCO, 512px, 25 PNDM steps, then downsampled to 256px for scoring. Original VAE, not our TAESD/10-step preview |
| [Segmind Tiny-SD][tiny] | No comparable complete pipeline byte total in cited card | **Unknown** | Authors report distilled models “up to 80% faster” than base SD1.5 on A100 80 GB, with benchmark plots/code. Training 512px/125K steps. Not a mobile CPU/RSS result or a verified 80% reduction for this driver |
| [Stable Diffusion 1.5][sd15] | No comparable complete quantized package total in cited card | **Unknown** | Fine-tuned 595K steps at 512px; general latent text-to-image baseline. No comparable CPU latency quoted |
| [SDXL base 1.0][sdxl] | Larger dual-text-encoder base/refiner architecture; no complete comparable package number quoted | **Unknown** | Card reports user preference advantage over SD1.5/2.1; base can run alone and refiner improves quality. Not a tiny/mobile-RAM profile |
| [Native SD1.x Q4_0 documentation][quant] | Runtime-dependent; no exact complete package bytes supplied | Approx. ~2.0G at 512px, ~1.5G with flash attention, **upstream estimate** | Hardware/steps/latency not supplied with memory table; not the same as our 256px disk-backed configuration |
| [Arm TinySD INT8 on vivo X300][arm] | **968.8 MB** model package; 323.4M reported parameters | **4166.75 MB peak**, 3608.25 MB mean | 159.41s (159413.99ms p50), 512px, 25 steps, 1500 MS-COCO samples, batch one, 5 runs/3 warmups, ExecuTorch 1.1 CPU/XNNPACK/KleidiAI on vivo X300, eight-core arm64, 16 GB system RAM |

Arm reports FID 58.48 and CLIP 26.65 under its own evaluation. Do not compare
those numbers directly with BK's different dataset/scoring protocol. Arm's
sub-1-GB package still needs **over 4 GB measured peak RAM**. Its optimized-model
metadata says licence not specified; the original Tiny-SD's OpenRAIL-M
restrictions still require review. We do not ship the Arm package.

## Reproduction

Run setup/download once using [README.md](README.md), then:

```bash
/usr/bin/time -v -o outputs/apple.time \
  .venv/bin/python -m nexi_image.driver generate \
    --prompt 'A photo of a red apple on a wooden table, still life, studio lighting' \
    --output outputs/apple.png --seed 42 --steps 10 --dtype float16 \
    --cache-state 'fresh workers; warm page cache after SHA verification'
# Repeat unchanged except output filename, compare:
.venv/bin/python -m nexi_image.driver generate \
  --prompt 'A photo of a red apple on a wooden table, still life, studio lighting' \
  --output outputs/apple-repeat.png --seed 42 --steps 10 --dtype float16
sha256sum outputs/apple.png outputs/apple-repeat.png

# Historical batched CFG configuration:
.venv/bin/python -m nexi_image.driver generate \
  --prompt 'A photo of a red apple on a wooden table, still life, studio lighting' \
  --output outputs/apple-batched.png --batched-guidance --dtype float16

# BF16 lighthouse configuration:
.venv/bin/python -m nexi_image.driver generate \
  --prompt 'A watercolor lighthouse on a rocky cliff at sunset, orange sky, blue ocean, beautiful painting' \
  --output outputs/lighthouse.png --dtype bfloat16 --batched-guidance

# Native standard, after setup_native.sh / native download:
.venv/bin/python -m nexi_image.native generate \
  --prompt 'A photo of a red apple on a wooden table, still life, studio lighting' \
  --output outputs/native.png --steps 10 --params disk
# Four-step LCM experiment (poor quality): add --profile lcm --steps 4.
```

Original smoke data was `outputs/train.jsonl`, containing a relative path to the
BF16 lighthouse PNG and caption “A watercolor ocean sunset beside a rocky cliff”.
With that image restored, use:

```bash
.venv/bin/python -m nexi_image.train_lora \
  --dataset outputs/train.jsonl --output adapters/smoke.safetensors \
  --resolution 128 --steps 1 --rank 2
```

Recorded evidence is immutable historical output, including original local
paths and concurrency labels; it is not regenerated by unit tests. Model hashes
are in `manifest.json`/`native-manifest.json`. No outputs/weights are in Git.

[bk]: https://huggingface.co/nota-ai/bk-sdm-tiny/blob/0364108e53b7f7f4d2585e817a0b7a83dc261cfa/README.md
[tiny]: https://huggingface.co/segmind/tiny-sd
[sd15]: https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5
[sdxl]: https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0
[quant]: https://github.com/leejet/stable-diffusion.cpp/blob/d637cfb935feb2254898a8f1524046c958f3df80/docs/quantization_and_gguf.md
[arm]: https://developer.arm.com/ai/models/hugging-face/Arm/tiny-sd-int8-xnnpack-executorch-vivo-x300/tinysd-int8-pte
