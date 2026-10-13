"""mlx-vlm vision backend — Apple Silicon fast path.

Used when `mlx-vlm` is installed and weights are present. Same Region
contract as the llama.cpp backend so the rest of the system never knows the
difference.
"""
from __future__ import annotations

import os
from typing import Optional

from .backend import Region, parse_any_box

_BOX_PROMPT = ("Provide the bounding box coordinates of the region this "
               "sentence describes: {desc}")

_DEFAULT_MODEL = "mlx-community/Qwen2-VL-2B-Instruct-4bit"


class MLXBackend:
    name = "mlx-vlm"

    def __init__(self, model: str = _DEFAULT_MODEL):
        self.model_name = model
        self._loaded = None
        self._config = None

    @staticmethod
    def available() -> bool:
        """Cheap availability probe — does NOT import or load anything."""
        import importlib.util
        return importlib.util.find_spec("mlx_vlm") is not None

    def warm(self, timeout: float = 120.0) -> None:
        if self._loaded is not None:
            return
        from mlx_vlm import load  # noqa: delayed import
        from mlx_vlm.utils import load_config
        self._loaded = load(self.model_name)
        self._config = load_config(self.model_name)

    def _gen(self, prompt: str, image_paths: list[str],
             max_tokens: int = 96) -> str:
        self.warm()
        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template
        model, proc = self._loaded
        cfg = apply_chat_template(proc, self._config, prompt,
                                  num_images=len(image_paths))
        out = generate(model, proc, cfg, image_paths,
                       max_tokens=max_tokens, temperature=0.0, verbose=False)
        return out.text if hasattr(out, "text") else str(out)

    def locate(self, image_path: str, description: str) -> Optional[Region]:
        out = self._gen(_BOX_PROMPT.format(desc=description), [image_path])
        from PIL import Image
        W, H = Image.open(image_path).size
        region = parse_any_box(out, W, H)
        if region is not None:
            region.source = self.name
        return region

    def best_of(self, image_path: str, crops: list[str],
                description: str) -> tuple[int, float]:
        import re
        if not crops:
            return -1, 0.0
        prompt = ("Which crop best matches: " + description +
                  "\nReply ONLY JSON {\"pick\": <int 1..%d>, \"confidence\": <float>}"
                  % len(crops))
        out = self._gen(prompt, crops, max_tokens=64)
        m = re.search(r'"pick"\s*:\s*(\d+)', out)
        if m:
            i = int(m.group(1)) - 1
            c = re.search(r'"conf[^"]*"\s*:\s*([0-9.]+)', out)
            return i, float(c.group(1)) if c and 0 <= i < len(crops) else 0.5
        return -1, 0.0
