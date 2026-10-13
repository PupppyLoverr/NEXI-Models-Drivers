# Process benchmarks

`footprint.sh` measures the existing text GGUF tiers. `process.py` is a dependency-free
wrapper for any local STT, TTS, or image inference command on Linux with GNU `time`.
It runs a **fresh process**, propagates its exit code, and records elapsed wall time,
maximum resident memory in bytes, hardware, the exact command, and optional asset bytes.
It does not download or run a model by itself.

```sh
# Download weights and install the selected driver's dependencies first.
# Substitute that driver's documented inference command after --.
python3 common/bench/process.py \
  --label my-local-inference \
  --asset-path /absolute/path/to/model-assets \
  --output /existing/results/directory/measurement.json \
  -- /absolute/path/to/inference-command arg1 arg2

python3 -m unittest discover -s common/bench -p 'test_*.py' -v
```

The output parent directory must exist. `--asset-path` may be repeated; overlapping
files/hard links are counted once. This is logical file size, **not** the full
Python environment, download cache, allocated disk blocks, or training footprint.
On macOS supply `--time-binary gtime` after installing GNU time; BSD time is not supported.
Windows users can run this wrapper under WSL; individual driver support is documented
in each model folder.

## Reading results honestly

- Fresh-process wall time includes imports, model load, inference and output writing;
  it is not warm inference latency or time-to-first-token/audio. It does not imply an
  OS page-cache cold start. Measure internal timings separately when comparing them.
- GNU time maximum RSS is the largest process high-water mark (including waited-for
  children where the OS accounts them), **not the sum of simultaneous workers**. For a
  multi-worker runtime, also measure aggregate memory. It does not measure GPU VRAM.
- Run one modality at a time for comparisons. Set and record thread counts. Archive
  the model revision, input/prompt/reference, seed, resolution/sample rate, inference
  options, versions and output hash alongside the measurement in the model folder.
- Use decimal MB/GB for byte-based RAM budgets; label MiB/GiB explicitly if using
  binary units. An on-disk 25 MB checkpoint is not evidence of 25 MB runtime RAM.
- A failing command produces `status: failed`; never present it as a completed
  inference benchmark. Unit-test or random tiny pipelines are not quality evidence.
- Published comparisons belong in a separate table from local measurements when
  hardware, datasets, precision, resolution or timing definitions differ. Unknown
  memory or quality numbers stay unknown. Cloud services do not have a local RAM figure.

## Independent modality review

[The 2026-10-13 review](reviews/modalities-2026-10-13.md) records the reviewed
commits, remaining fine-tuning/quality limitations, real speech checks and an
independent native small-image reproduction. Its JSON evidence is stored under
each modality's own `results/review/` or `evidence/review/` subfolder; model
weights, environments and generated media are excluded from Git.
