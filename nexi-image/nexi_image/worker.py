"""Offline CPU tensor stages; called by the lightweight parent."""

import json
import resource
import sys
import time
from pathlib import Path

from .driver import OFFLINE


def main() -> None:
    import os
    os.environ.update(OFFLINE)
    stage, config_path, work_path = sys.argv[1:]
    config = json.loads(Path(config_path).read_text())
    work = Path(work_path)
    started = time.perf_counter()
    import torch
    from diffusers import AutoencoderTiny, DDIMScheduler, UNet2DConditionModel
    from transformers import CLIPTextModel, CLIPTokenizer

    torch.set_num_threads(config["threads"])
    torch.set_num_interop_threads(1)
    dtype = getattr(torch, config["dtype"])
    root = Path(config["models"])
    if stage == "encode":
        tokenizer = CLIPTokenizer.from_pretrained(root / "bk/tokenizer", local_files_only=True)
        encoder = CLIPTextModel.from_pretrained(root / "bk/text_encoder", variant="fp16",
                                               torch_dtype=dtype, local_files_only=True).eval()
        tokens = tokenizer([config["negative"], config["prompt"]], padding="max_length",
                           max_length=tokenizer.model_max_length, truncation=True, return_tensors="pt")
        with torch.inference_mode():
            embeddings = encoder(tokens.input_ids)[0]
        torch.save(embeddings, work / "embeddings.pt")
    elif stage == "denoise":
        unet = UNet2DConditionModel.from_pretrained(root / "bk/unet", variant="fp16",
                                                   torch_dtype=dtype, local_files_only=True).eval()
        if config.get("adapter"):
            from peft import LoraConfig, set_peft_model_state_dict
            from safetensors.torch import load_file
            metadata = json.loads(Path(config["adapter"]).with_suffix(".json").read_text())
            unet.add_adapter(LoraConfig(r=metadata["rank"], lora_alpha=metadata["rank"],
                                       target_modules=["to_q", "to_k", "to_v", "to_out.0"]))
            set_peft_model_state_dict(unet, load_file(config["adapter"]))
        scheduler = DDIMScheduler.from_pretrained(root / "bk/scheduler", local_files_only=True)
        scheduler.set_timesteps(config["steps"])
        embeddings = torch.load(work / "embeddings.pt", weights_only=True).to(dtype)
        generator = torch.Generator(device="cpu").manual_seed(config["seed"])
        latents = torch.randn((1, 4, config["height"] // 8, config["width"] // 8),
                              generator=generator, dtype=torch.float32).to(dtype) * scheduler.init_noise_sigma
        with torch.inference_mode():
            for t in scheduler.timesteps:
                if config.get("batched_guidance"):
                    batch = scheduler.scale_model_input(torch.cat([latents, latents]), t)
                    noise = unet(batch, t, encoder_hidden_states=embeddings).sample
                    unconditional, conditional = noise.chunk(2)
                else:
                    sample = scheduler.scale_model_input(latents, t)
                    unconditional = unet(sample, t, encoder_hidden_states=embeddings[:1]).sample
                    conditional = unet(sample, t, encoder_hidden_states=embeddings[1:]).sample
                guided = unconditional + config["guidance"] * (conditional - unconditional)
                latents = scheduler.step(guided, t, latents, eta=0).prev_sample
        torch.save(latents.float(), work / "latents.pt")
    elif stage == "training_encode":
        import numpy as np
        from PIL import Image, ImageOps
        from diffusers import AutoencoderKL
        vae = AutoencoderKL.from_pretrained(root / "bk/vae", variant="fp16",
                                           torch_dtype=torch.float32, local_files_only=True).eval()
        with Image.open(config["image"]) as image:
            image = ImageOps.fit(image.convert("RGB"), (config["width"], config["height"]))
            pixels = torch.from_numpy(np.array(image).astype("float32") / 127.5 - 1).permute(2, 0, 1)[None]
        with torch.inference_mode():
            latent = vae.encode(pixels).latent_dist.sample(
                generator=torch.Generator().manual_seed(config["seed"])) * vae.config.scaling_factor
        torch.save(latent, work / "training_latents.pt")
    elif stage == "decode":
        from PIL import Image
        vae = AutoencoderTiny.from_pretrained(root / "taesd", local_files_only=True).eval()
        latents = torch.load(work / "latents.pt", weights_only=True)
        with torch.inference_mode():
            decoded = vae.decode(latents / vae.config.scaling_factor).sample
        array = ((decoded[0].float().clamp(-1, 1) + 1) * 127.5).round().byte().permute(1, 2, 0).numpy()
        Image.fromarray(array).save(config["output"])
    else:
        raise ValueError(f"Unknown stage {stage}")
    metrics = {"stage": stage, "wall_seconds": time.perf_counter() - started,
               "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
               "torch": torch.__version__}
    (work / f"{stage}.json").write_text(json.dumps(metrics))


if __name__ == "__main__":
    main()
