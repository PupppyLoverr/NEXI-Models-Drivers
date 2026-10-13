# NEXI Image driver

## Three generation/editing variants

See [TIERS.md](TIERS.md) for the `small` (1 GB workload target), `medium`
(1–4 GB target), and editing-focused `best` (6 GB target) native profiles,
including setup, CLI/API, masks, licences and measurement boundaries. They use
quantized BK-SDM, SDXL-Lightning and FLUX.2 Klein 4B respectively, with disk-backed
parameters. They are upstream-based profiles, not NEXI-trained or demonstrated
OpenAI/Nano Banana equivalents. Model storage is separate from RAM.

```bash
bash setup.sh
bash setup_native.sh
.venv/bin/python -m nexi_image.tiers download --tier best
.venv/bin/python -m nexi_image.tiers generate --tier best \
  --prompt 'A red ceramic mug on a wooden table' --output outputs/mug.png
.venv/bin/python -m nexi_image.tiers edit --tier best --image outputs/mug.png \
  --prompt 'Change the mug to blue, preserve the scene' --output outputs/edit.png
```

## Original Diffusers baseline and LoRA route

Real, local text-to-image generation using **upstream BK-SDM-Tiny**, not a NEXI
finetune. A compressed U-Net, CLIP text conditioning, DDIM sampler and TAESD
decoder run sequentially in separate CPU processes. No random test checkpoint.

**Measured result:** 256×256, ten steps, FP16, seed 42: a recognisable red apple,
58.94 seconds end-to-end, **1,085,317,120 bytes peak worker RSS**, and
**904,340,286 bytes inference model files**. This does **not** meet a strict
1 GB total-RAM target. Python dependencies add another ~1.21 GB on this host.
See [BENCHMARKS.md](BENCHMARKS.md) for measurement boundaries and limitations.

## Quick start

Tested on Linux x86_64, Python 3.11, Intel Xeon Platinum 8559C, no GPU.
Allow at least 3 GB available RAM for inference, several GB free disk for setup,
and more for training. ARM/mobile packaging and Windows/macOS execution are
not validated; RSS measurement currently depends on Linux `resource`/`wait4`.

```bash
cd nexi-image
bash setup.sh
.venv/bin/python -m nexi_image.driver download
.venv/bin/python -m nexi_image.driver verify
.venv/bin/python -m nexi_image.driver generate \
  --prompt 'A photo of a red apple on a wooden table, still life, studio lighting' \
  --output outputs/apple.png --seed 42 --steps 10 --dtype float16 \
  --cache-state 'fresh workers; page cache warmed by integrity verification'
```

Setup/download intentionally require internet. Generation verifies SHA-256 and
uses local files only, with Hugging Face offline environment flags; it performs
no download or telemetry. Once installed/downloaded, it also works disconnected.
Models use immutable repository revisions and file hashes in `manifest.json`.
Model files, generated images and adapters are ignored and are not in Git.

`generate` writes a PNG and sibling JSON: complete prompt/configuration, model
revisions and hashes, stage RSS/latency, output SHA-256, hardware and cache label.
Defaults: 256×256, ten DDIM steps, guidance 7.5, seed 42, four threads, FP16.
Dimensions 128–512 in multiples of 64 are accepted; larger images and more steps
cost substantially more RAM/time. This is a **preview** profile of a model
originally evaluated at 512×512/25 PNDM steps, not an equivalent quality setting.
On CPUs without fast FP16, try `--dtype float32` (higher RAM) or `bfloat16`.
CFG branches run sequentially by default to save memory. `--batched-guidance`
trades memory for speed: the tested batched FP16 run took 41.15s at 1.145 GB
peak worker RSS. Even sequential CFG exceeded 1 GiB, before parent/OS memory.

### Python API

From this folder, using the setup environment:

```python
from nexi_image.driver import generate

report = generate(
    prompt="A watercolor landscape with a blue ocean",
    output="outputs/landscape.png", seed=42, steps=10,
)
print(report["max_worker_peak_rss_bytes"])
```

Calls are synchronous and launch isolated workers; this is a Python API, not a
network server. Keep the folder on `PYTHONPATH` if importing from elsewhere.
The same prompt/seed/configuration produced byte-identical PNGs in fresh
processes on the tested host. This is not guaranteed across hardware, versions,
dtypes or thread counts. Prompts over CLIP's 77-token context are truncated.

## Adaptation: actual attention LoRA training

The included CPU trainer performs noise-prediction updates on U-Net attention
adapters, not prompt substitution. It leaves the base weights frozen and
precomputes text/latent embeddings. Use your own consented/licensed images and
captions. A JSONL dataset in `data/train.jsonl` has one row per image, paths
relative to that JSONL:

```json
{"image":"apple.png","caption":"A red apple in my watercolor illustration style"}
```

```bash
.venv/bin/python -m nexi_image.driver download --training
.venv/bin/python -m nexi_image.train_lora \
  --dataset data/train.jsonl --output adapters/style.safetensors \
  --steps 100 --rank 4 --resolution 256 --threads 4
.venv/bin/python -m nexi_image.driver generate \
  --prompt 'A red apple in my watercolor illustration style' \
  --adapter adapters/style.safetensors --output outputs/adapted.png
```

Keep the sibling adapter JSON: it records rank, optimizer settings, image and
dataset hashes, losses and adapter SHA-256, and is required for adapter loading.
Training needs the original VAE, bringing model files to 1,071,676,179 bytes.
A real one-update, rank-two, 128px smoke run trained 215,808 parameters, produced
an 883,048-byte adapter, and successfully loaded it for generation. Peak trainer
RSS was 2,263,867,392 bytes. **This proves execution, not useful adaptation.**
Training at 256px/many steps is not benchmarked; use more RAM, a representative
dataset, held-out prompts, and human evaluation. Adapters are BK-SDM specific,
not interchangeable with the optional native SD1.5 profile.

## Optional native experiment: SD1.5 Q4 + TAESD

This is a separately pinned upstream `stable-diffusion.cpp` CPU route, not a
quantized BK-SDM. It avoids PyTorch for generation and uses disk-backed parameter
loading plus flash attention. **It still failed the 1 GB RAM target.** Ten-step
Euler ancestral generation produced a recognisable apple but took ~130–152 seconds.
The faster optional four-step LCM profile had severe stripe/grid artifacts and
is not recommended. The primary fast preview is BK-SDM above.

Needs Git, C/C++ compiler, make, Python venv, internet for setup, and ~3 GB free
disk beyond the Python baseline. `setup_native.sh` pins CMake 3.31.6 and source
revision `d637cfb935feb2254898a8f1524046c958f3df80` (including pinned ggml).

```bash
bash setup_native.sh
.venv/bin/python -m nexi_image.native download
.venv/bin/python -m nexi_image.native verify
.venv/bin/python -m nexi_image.native generate \
  --prompt 'A photo of a red apple on a wooden table, still life, studio lighting' \
  --output outputs/native.png --steps 10 --params disk \
  --cache-state 'fresh process; warm page cache after SHA verification'
```

Full TAESD weights are required by this pinned runtime's metadata validation;
the standalone decoder file was insufficient. Native inference files total
1,891,605,632 bytes. `--binary` overrides the runtime path; the driver checks its
reported commit prefix and records the binary hash. `NEXI_NATIVE_HOME` can change
the setup location; pass its resulting executable with `--binary`. The driver
is stdlib-only, so system Python can run it after CMake setup.
`--profile lcm` selects the artifact-prone four-step experiment; default
`standard` uses ten Euler ancestral steps, guidance 7, without the LCM adapter.
The download includes the LCM file for experiments, even in standard mode.

## Tests

Offline tests require no models or PyTorch:

```bash
python3 -m unittest discover -s tests -v
.venv/bin/ruff check nexi_image tests
.venv/bin/mypy --ignore-missing-imports --follow-imports=skip nexi_image
bash -n setup.sh setup_native.sh
```

## Licences and deployment limits

- BK-SDM-Tiny and SD1.5: **CreativeML OpenRAIL-M**, not unrestricted MIT/Apache
  weights. Commercial/service use is permitted by the licence, but prohibited
  uses and redistribution obligations remain. The BK card's intended-use text
  says research. Review the complete [licence](https://huggingface.co/spaces/CompVis/stable-diffusion-license)
  and [BK card](https://huggingface.co/nota-ai/bk-sdm-tiny) before deployment.
  Redistributors must retain the licence and communicate its use restrictions.
  Do not use for unlawful/harmful content, exploitation, malicious personal-data
  use, discrimination or misleading impersonation. Output rights are your
  responsibility; the licence does not guarantee copyright clearance.
- LCM adapter: the [pinned card](https://huggingface.co/latent-consistency/lcm-lora-sdv1-5/tree/cf2fced511dbe7e26c8d1d397e728fbab875db4b)
  declares **OpenRAIL++**; this does not remove the base model's restrictions.
- [TAESD](https://huggingface.co/madebyollin/taesd): **MIT**; retain notices when
  redistributing. [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp):
  MIT runtime, separate from weight licences. Check transitive runtime notices.
- No safety checker/content moderation is bundled. A public-facing application
  must add its own abuse prevention, output review and consent safeguards.

This is not cloud-tool-equivalent quality, a sub-1-GB application package, a
mobile SDK, a trained NEXI image model, or a finished fine-tuned model. See
[ARCHITECTURE.md](ARCHITECTURE.md) and [USE_CASES.md](USE_CASES.md).
