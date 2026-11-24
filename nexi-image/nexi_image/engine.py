"""Image engines. Default: BK-SDM-small (0.76B UNet, SD-1.5 arch) — the
smallest widely-used open diffusion weights; runs fp32 on CPU."""
from __future__ import annotations

import torch


class BkSdmEngine:
    name = "bk-sdm-small"
    MODEL_ID = "nota-ai/bk-sdm-small"

    def __init__(self, model_id: str | None = None):
        from diffusers import (StableDiffusionImg2ImgPipeline,
                               StableDiffusionPipeline)
        self._p = StableDiffusionPipeline.from_pretrained(
            model_id or self.MODEL_ID, torch_dtype=torch.float32,
            safety_checker=None, requires_safety_checker=False)
        self._p.set_progress_bar_config(disable=True)
        # img2img shares the same UNet/VAE weights — no extra RAM
        self._i2i = StableDiffusionImg2ImgPipeline(**self._p.components)
        self._i2i.set_progress_bar_config(disable=True)

    def generate(self, prompt: str, steps: int = 15, size: int = 256,
                 seed: int = 7):
        g = torch.Generator("cpu").manual_seed(seed)
        return self._p(prompt, num_inference_steps=steps, height=size,
                       width=size, generator=g).images[0]

    def edit(self, image, prompt: str, steps: int = 15,
             strength: float = 0.6, seed: int = 7):
        """img2img edit: strength 0.4-0.7 keeps composition, changes style."""
        g = torch.Generator("cpu").manual_seed(seed)
        return self._i2i(prompt, image=image, strength=strength,
                         num_inference_steps=steps, generator=g).images[0]


ENGINES = {"bk-sdm": BkSdmEngine}


def load_engine(name: str = "bk-sdm"):
    return ENGINES[name]()
