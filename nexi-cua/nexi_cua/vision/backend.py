"""Vision backend protocol — VLM escalation for the semantic path.

A backend answers exactly one question: where is the described thing?
`locate` returns normalized coords + the backend's confidence. Every backend
is a real local model; nothing is faked.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class Region:
    x: float          # normalized 0-1
    y: float
    w: float = 0.0
    h: float = 0.0
    confidence: float = 0.0
    source: str = "vlm"

    def center_px(self, sw: int, sh: int) -> tuple[float, float]:
        return self.x * sw, self.y * sh


class VisionBackend(Protocol):
    name: str

    def locate(self, image_path: str, description: str) -> Optional[Region]:
        ...

    def best_of(self, image_path: str, crops: list[str],
                description: str) -> tuple[int, float]:
        """Which crop best matches the description -> (index, confidence)."""
        ...


_TARGET_RE = __import__("re").compile(
    r"(?:the|a|an)\s+((?:red|green|blue|yellow|orange|purple|grey|gray|"
    r"highlighted|selected|active|blinking|large|small|top|bottom|left|"
    r"right|corner|round|square)\s+[\w-]+(?:\s+[\w-]+)?)",
    __import__("re").I)


def target_phrase(goal: str) -> str:
    """Extract the visually-grounded target phrase from a goal."""
    m = _TARGET_RE.search(goal)
    if m:
        return m.group(1).strip()
    m = re.search(r'(?:click|press|tap|hit|find|locate|open|select)\s+'
                  r'(?:the|a|an|on)?\s*["\']?([^"\']{2,60})["\']?', goal, re.I)
    return m.group(1).strip() if m else goal


def parse_region_json(text: str) -> Optional[tuple[float, float, float]]:
    """Parse VLM output for {x,y[,conf]} — tolerant of prose around it."""
    m = re.search(r'"x"\s*:\s*([0-9.]+)[^\d]*"y"\s*:\s*([0-9.]+)'
                  r'(?:[^\d]*"conf(?:idence)?"\s*:\s*([0-9.]+))?', text, re.I)
    if m:
        x, y = float(m.group(1)), float(m.group(2))
        c = float(m.group(3)) if m.group(3) else 0.7
        if 0 <= x <= 1 and 0 <= y <= 1:
            return x, y, min(c, 1.0)
        if x > 1 or y > 1:  # pixel coords on a 0-1000 or px scale
            return None
    m = re.search(r'([0-9]*\.?[0-9]+)[,\s]+([0-9]*\.?[0-9]+)', text)
    if m:
        x, y = float(m.group(1)), float(m.group(2))
        if 0 <= x <= 1 and 0 <= y <= 1:
            return x, y, 0.5
    return None


def parse_any_box(out: str, img_w: int, img_h: int) -> Optional[Region]:
    """Parse VLM grounding output in any shape — <|box_start|>(x1,y1),
    (x2,y2)<|box_end|>, prose "(x,y) and (x,y)", or a bare "x, y" point.
    Coords arrive as absolute px, 0-1000 scale, or normalized; pick the
    interpretation that lands inside the image."""
    nums = [float(v) for v in re.findall(
        r'\(?\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*\)?',
        out) for v in v]
    if len(nums) < 2:
        return None
    if len(nums) >= 4:
        x0, y0, x1, y1 = nums[0], nums[1], nums[2], nums[3]
    else:
        x0 = y0 = x1 = y1 = 0.0
        x0, y0 = nums[0], nums[1]
        x1, y1 = x0 + 20, y0 + 20  # point -> small box in px space
    mx = max(abs(v) for v in (x0, y0, x1, y1))
    if mx <= 1.5:                       # already normalized
        pass
    elif mx > 1001:                     # absolute pixels
        x0, y0, x1, y1 = x0 / img_w, y0 / img_h, x1 / img_w, y1 / img_h
    elif mx > max(img_w, img_h):        # 0-1000 normalized scale
        x0, y0, x1, y1 = x0 / 1000, y0 / 1000, x1 / 1000, y1 / 1000
    else:                               # fits image: assume absolute px
        x0, y0, x1, y1 = x0 / img_w, y0 / img_h, x1 / img_w, y1 / img_h
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    if not (0 <= x0 <= 1 and 0 <= y0 <= 1 and x1 <= 1.02 and y1 <= 1.02):
        return None
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if not (0 <= cx <= 1 and 0 <= cy <= 1):
        return None
    return Region(x=cx, y=cy, w=x1 - x0, h=y1 - y0, confidence=0.7)


def pick_backend(prefer: str = "") -> Optional[VisionBackend]:
    """Instantiate the best available backend WITHOUT loading the model —
    backends stay cold until the first locate() call (vision is escalation,
    not the default path).
    prefer="" / "auto": MLX on Apple Silicon, then llama.cpp;
    "mlx" / "llamacpp": that backend only."""
    import platform
    on_apple = platform.system() == "Darwin" and \
        platform.machine() in ("arm64", "arm")
    if prefer in ("mlx", "auto", "") and on_apple:
        try:
            from .vlm_mlx import MLXBackend
            if MLXBackend.available():
                return MLXBackend()
        except Exception:
            if prefer == "mlx":
                return None
    if prefer in ("llamacpp", "auto", ""):
        try:
            from .vlm_llamacpp import LlamaCppBackend
            if LlamaCppBackend.available():
                return LlamaCppBackend()
        except Exception:
            pass
    return None
