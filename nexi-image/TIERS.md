# Three native image-generation and editing variants

These are **upstream-based deployment profiles**, not three NEXI-trained models.
Quality targets are aspirational: no OpenAI or Nano Banana equivalence has been
established. No model download size is used as a substitute for inference RAM.

| CLI tier | Inference RAM target | Model | Editing mechanism | Defaults |
|---|---:|---|---|---|
| `small` | 1,000,000,000 bytes | BK-SDM-Tiny, Q4_0 linear weights, full TAESD | Img2img; latent mask plus exact final compositing | 256×256, 10 steps, CFG 7 |
| `medium` | 4,000,000,000 bytes | SDXL-Lightning four-step checkpoint, Q8_0, original VAE | Img2img; latent mask plus exact final compositing | 512×512, 4 steps, CFG 1 |
| `best` | 6,000,000,000 bytes | FLUX.2 Klein 4B Q8_0; Qwen3-4B Q4_K_M; full encoder/small decoder | Native instruction and multi-reference editing; optional final mask compositing | 512×512, 4 steps, CFG 1 |

The targets apply to the image workload, including the Python caller, **not an
entire machine**. OS, other applications and filesystem cache require additional
RAM. Storage is reported separately. Q8 is deliberately used in the higher tiers
to retain more weight precision; this does not establish a numerical quality score.
The names designate intended tiers, not measured cloud-quality rankings.

## Setup and provisioning

The Python wrapper/measurement implementation is Linux-only; Windows users can
use WSL2. The upstream native engine itself supports other platforms, but those
platforms have not been verified here.

```bash
cd nexi-image
bash setup.sh
bash setup_native.sh

# Download only the variant you need. Setup/download access the network.
.venv/bin/python -m nexi_image.tiers download --tier small
.venv/bin/python -m nexi_image.tiers download --tier medium
.venv/bin/python -m nexi_image.tiers download --tier best

.venv/bin/python -m nexi_image.tiers verify --tier small
```

All upstream assets use immutable revisions and SHA-256 checksums. Small and
medium also run an **offline conversion** during `download`. Small remaps BK's
sparse U-Net tensor names and quantizes using the pinned native engine; medium
quantizes the official ByteDance all-in-one checkpoint. A build receipt records
the pinned manifest fingerprint, converter binary hash, upstream assets and
actual derived GGUF checksum. `verify`/inference verify the derived artifact
against its local receipt; the receipt is local provenance, not a publisher
signature. Best uses checked upstream GGUF files directly.

Provisioning/building can use more memory and storage than inference. The small
converter imports PyTorch; generation/editing **do not**. Raw source weights are
retained by default for re-provisioning, but are not required for offline inference
once the converted GGUF and receipt exist. Deployment needs all `runtime_files`
listed in a generation report, the build receipt where applicable, and the
pinned binary. The model byte total excludes raw conversion inputs, executables,
Python dependencies, logs and generated images.

## Generate

```bash
.venv/bin/python -m nexi_image.tiers generate --tier best \
  --prompt 'A studio photograph of a red ceramic coffee mug on a wooden table, soft daylight' \
  --output outputs/mug.png --seed 42
```

Replace `best` with `small` or `medium`. Width/height may be explicit multiples of
64 between 128 and 1024; bigger resolutions/reference counts can exceed a tier's
budget and are **not** covered by lower-resolution measurements. Distilled
medium/best profiles require four nominal steps. Small allows 1–50 steps.
The same seed/weights/config/runtime gives repeatable pixels on the tested host;
cross-build/device bit identity is not guaranteed. Native PNG metadata can change
with temporary paths; compare `output_rgb_sha256`, not only PNG file hashes.

## Edit

### Native instruction editing (best)

```bash
.venv/bin/python -m nexi_image.tiers edit --tier best \
  --image outputs/mug.png \
  --prompt 'Change the red mug to blue. Preserve its shape, the wooden table and the lighting.' \
  --output outputs/blue-mug.png --seed 42

# Optional extra references (up to three, in addition to --image):
# --reference style.png --reference object.png
```

References are encoded as actual FLUX.2 conditioning, not replaced with a text
description. This is the editing-focused tier. There is no `--strength` control
for instruction editing. It is still a statistical generator: identities,
typography, exact layout and colours may drift.

### Low/middle tiers: img2img and masked regeneration

```bash
.venv/bin/python -m nexi_image.tiers edit --tier small \
  --image source.png --prompt 'A blue ceramic coffee cup on a wooden table' \
  --strength 0.65 --output outputs/edited.png

.venv/bin/python -m nexi_image.tiers edit --tier medium \
  --image source.png --mask selection.png \
  --prompt 'A blue ceramic coffee cup on a wooden table' \
  --strength 1 --output outputs/masked.png
```

These use **descriptions of the desired result**, not instruction-following
models. Higher strength changes more; lower strength may ignore the prompt.
The native runtime truncates the denoising schedule for strength below one, so
the effective step count can be below the configured nominal steps. A truncated
SDXL-Lightning schedule is not its published four-step evaluation recipe and
may have worse quality. At strength one, a mask is useful for local regeneration.

Masks must match the EXIF-oriented source dimensions. White selects edits, black
preserves the input, grey blends. Small/medium pass the mask to native latent
inpainting. Every tier also composites the generated pixels with the staged
input, guaranteeing byte-identical RGB pixels where the staged mask is zero.
Best's mask is **output compositing**, not trained masked/inpainting conditioning.
Inputs/references are EXIF-transposed, aspect-preservingly resized and black
letterboxed to the requested canvas; preservation refers to that canvas, not
to an arbitrary original-resolution file. Default canvas dimensions are those
of the selected tier, not inferred from the input image.

## Python API

```python
from nexi_image.tiers import generate

report = generate("best", "Turn the mug blue, preserve the scene", "edited.png",
                  image="source.png", mask="mask.png", seed=42)
```

The API does not download anything. Output writes are staged and replaced only
after successful inference and size verification. A failed process or missing
new output does not masquerade as an existing image's success.

## Measurement boundaries

After provisioning, reproduce serial generation, real masked editing and pixel
seed-repeat checks with:

```bash
.venv/bin/python -m nexi_image.benchmark_tiers --tiers small medium best
```

This uses real weights, not mocks, and takes many CPU minutes. It creates
generated input images, deterministic mask fixtures, native reports/logs and
pixel-change checks in `outputs/tier-benchmark/`. `--tiers small` limits the
workload; `--skip-repeat` omits the repeat rather than claiming it passed.

Every report contains exact native child peak RSS from `wait4`, a sampled
parent+child RSS sum (50 ms polling), the parent's own peak RSS and the sum of
parent/child individual peaks as a **conservative upper bound**. The two peaks
need not occur simultaneously. Sampling can miss brief spikes; its maximum is
not presented as the exact peak. Shared resident pages can be counted twice.
`fits_ram_target_conservative` compares that upper bound with the tier target;
it is not a hard memory limit or a guarantee for other inputs/hosts.

Inference runs a fresh native process with CPU backend, disk-backed parameters,
flash attention and VAE tiling. Hash verification warms model files before each
run. `--cache-state` is caller-supplied context, not a command that drops caches.
`total_wall_seconds` includes verification/preprocessing/native inference;
`native_wall_seconds` isolates the native child. Loading, denoising and decoding
are all included in child peak measurement.

## Licences, creative scope and quality

- [BK-SDM-Tiny](https://huggingface.co/nota-ai/bk-sdm-tiny): CreativeML OpenRAIL-M.
- [SDXL-Lightning](https://huggingface.co/ByteDance/SDXL-Lightning): OpenRAIL++ /
  inherited SDXL responsible-use restrictions; preserve notices/restrictions.
- [Klein 4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B),
  [small decoder](https://huggingface.co/black-forest-labs/FLUX.2-small-decoder) and
  [Qwen3](https://huggingface.co/Qwen/Qwen3-4B): Apache 2.0; retain licence/NOTICE
  obligations. The 9B/dev non-commercial models are not used here.
- [TAESD](https://huggingface.co/madebyollin/taesd): MIT.

No custom safety-unlearning or "uncensoring" finetune is supplied. Models can
retain learned safety mitigations. Local/offline deployment is not a promise
that any requested image is possible, lawful or licence-compliant. Public
services need appropriate input/output safeguards and consent checks. The
existing small LoRA trainer applies to BK's Diffusers path, not automatically to
quantized SDXL/FLUX models or to these native GGUF files.

Cloud parity would require a representative matched generation/editing suite
and independent evaluation, not one attractive image. There is no cloud API
dependency, paid evaluation, or invented OpenAI/Nano Banana score here. CPU
latency is much higher than the upstream GPU demonstrations; device/GPU/mobile
performance is unverified. Local measured results belong in BENCHMARKS.md.
