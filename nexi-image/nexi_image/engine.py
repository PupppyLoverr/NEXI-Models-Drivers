"""Image engines. Default: BK-SDM-small (0.76B UNet, SD-1.5 arch) — the
smallest widely-used open diffusion weights; runs fp32 on CPU."""
from __future__ import annotations

import torch


class BkSdmEngine:
    name = "bk-sdm-small"
    MODEL_ID = "nota-ai/bk-sdm-small"

    def __init__(self, model_id: str | None = None):
        from diffusers import StableDiffusionPipeline
        self._p = StableDiffusionPipeline.from_pretrained(
            model_id or self.MODEL_ID, torch_dtype=torch.float32,
            safety_checker=None, requires_safety_checker=False)
        self._p.set_progress_bar_config(disable=True)

    def generate(self, prompt: str, steps: int = 15, size: int = 256,
                 seed: int = 7):
        g = torch.Generator("cpu").manual_seed(seed)
        return self._p(prompt, num_inference_steps=steps, height=size,
                       width=size, generator=g).images[0]


ENGINES = {"bk-sdm": BkSdmEngine}


def load_engine(name: str = "bk-sdm"):
    return ENGINES[name]()
