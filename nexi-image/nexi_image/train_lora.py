"""Offline captioned-image UNet attention LoRA training, batch one on CPU."""

import argparse
import json
import os
from pathlib import Path
import resource
import tempfile
import time

from .assets import digest, verify
from .driver import OFFLINE, run_worker


def samples(path: Path) -> list[dict]:
    records = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not isinstance(row.get("image"), str) or not row["image"]:
            raise ValueError("Every dataset row requires an image path")
        if not isinstance(row.get("caption"), str) or not row["caption"].strip():
            raise ValueError("Every dataset row requires a caption")
        image = (path.parent / row["image"]).resolve()
        if not image.is_file():
            raise ValueError(f"Missing dataset image: {image}")
        records.append({"image": str(image), "caption": row["caption"]})
    if not records:
        raise ValueError("Dataset is empty")
    return records


def train(dataset: str, output: str, models: str = "models", steps: int = 100,
          rank: int = 4, resolution: int = 256, threads: int = 4,
          seed: int = 42, learning_rate: float = 1e-4) -> dict:
    if not 1 <= steps <= 100000 or not 1 <= rank <= 64 or not 1 <= threads <= 64:
        raise ValueError("invalid steps, rank, or threads")
    if resolution < 128 or resolution > 512 or resolution % 64:
        raise ValueError("resolution must be 128–512 in multiples of 64")
    if not 0 < learning_rate <= 0.01 or not 0 <= seed < 2**63:
        raise ValueError("invalid learning rate or seed")
    os.environ.update(OFFLINE)
    root = Path(models).resolve()
    output_path = Path(output).resolve()
    if output_path.suffix != ".safetensors":
        raise ValueError("output must be .safetensors")
    model_bytes = verify(root, training=True)
    records = samples(Path(dataset).resolve())
    started = time.perf_counter()
    precompute: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="nexi-image-train-") as tmp:
        workspace = Path(tmp)
        for i, row in enumerate(records):
            sample_work = workspace / str(i)
            sample_work.mkdir()
            config = {"models": str(root), "threads": threads, "dtype": "float32",
                      "seed": seed + i, "prompt": row["caption"], "negative": "",
                      "width": resolution, "height": resolution, "image": row["image"]}
            precompute.extend(run_worker(stage, config, sample_work)
                              for stage in ("encode", "training_encode"))

        import torch
        import torch.nn.functional as functional
        from diffusers import DDPMScheduler, UNet2DConditionModel
        from peft import LoraConfig, get_peft_model_state_dict
        from safetensors.torch import save_file

        torch.set_num_threads(threads)
        torch.set_num_interop_threads(1)
        torch.manual_seed(seed)
        cached = [(torch.load(workspace / str(i) / "training_latents.pt", weights_only=True),
                   torch.load(workspace / str(i) / "embeddings.pt", weights_only=True)[1:])
                  for i in range(len(records))]
        unet = UNet2DConditionModel.from_pretrained(root / "bk/unet", variant="fp16",
                                                   torch_dtype=torch.float32, local_files_only=True)
        unet.requires_grad_(False)
        unet.add_adapter(LoraConfig(r=rank, lora_alpha=rank, init_lora_weights="gaussian",
                                   target_modules=["to_q", "to_k", "to_v", "to_out.0"]))
        unet.enable_gradient_checkpointing()
        unet.train()
        parameters = [p for p in unet.parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW(parameters, lr=learning_rate)
        scheduler = DDPMScheduler.from_pretrained(root / "bk/scheduler", local_files_only=True)
        losses = []
        for step in range(steps):
            latent, embedding = cached[step % len(cached)]
            noise = torch.randn_like(latent)
            timestep = torch.randint(0, scheduler.config.num_train_timesteps, (1,)).long()
            noisy = scheduler.add_noise(latent, noise, timestep)
            prediction = unet(noisy, timestep, encoder_hidden_states=embedding).sample
            target = noise if scheduler.config.prediction_type == "epsilon" else scheduler.get_velocity(latent, noise, timestep)
            loss = functional.mse_loss(prediction.float(), target.float())
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite training loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(parameters, 1.0)
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            losses.append(loss.item())
        state = get_peft_model_state_dict(unet)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        save_file({name: tensor.detach().contiguous() for name, tensor in state.items()}, str(output_path))
        report = {"schema": 1, "base_model": "nota-ai/bk-sdm-tiny", "rank": rank,
                  "steps": steps, "resolution": resolution, "seed": seed,
                  "learning_rate": learning_rate, "threads": threads,
                  "trainable_parameters": sum(p.numel() for p in parameters),
                  "losses": losses, "precompute": precompute,
                  "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                  "wall_seconds": time.perf_counter() - started, "model_disk_bytes": model_bytes,
                  "adapter_bytes": output_path.stat().st_size, "adapter_sha256": digest(output_path),
                  "dataset_sha256": digest(Path(dataset)),
                  "images": [{**r, "sha256": digest(Path(r["image"]))} for r in records],
                  "quality_claim": "none; optimizer smoke test is not evidence of useful adaptation"}
        output_path.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help='Local JSONL: {"image":"relative.png","caption":"..."}')
    parser.add_argument("--output", default="adapters/style.safetensors")
    parser.add_argument("--models", default="models")
    for name, value in (("steps", 100), ("rank", 4), ("resolution", 256), ("threads", 4), ("seed", 42)):
        parser.add_argument(f"--{name}", type=int, default=value)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    try:
        print(json.dumps(train(**vars(parser.parse_args())), indent=2))
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
