"""llama.cpp vision backend — llama-server + GGUF VLM (mtmd endpoint).

Cross-platform: llama.cpp ships for macOS/Windows/Linux. The runtime spawns
`llama-server` with a small VLM (default SmolVLM2-500M Q8 — ~500MB) and talks
the OpenAI-compatible /v1/chat/completions API with base64 images.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time
import urllib.request
from typing import Optional

from .backend import Region, parse_any_box

_DEFAULT_MODEL = "weights/vision/qwen2-vl-2b-q4_k_m.gguf"
_DEFAULT_MMPROJ = "weights/vision/mmproj-qwen2-vl-2b-f16.gguf"

_BOX_PROMPT = (
    "Provide the bounding box coordinates of the region this sentence "
    "describes: {desc}")

_LOCATE_PROMPT = (
    "This screenshot has a labeled grid: columns {cols} (left to right), "
    "rows 1-{rows} (top to bottom). Each cell is labeled like B3. "
    "Which single cell contains the element described below? "
    "Reply ONLY with JSON: "
    '{{"cell": "<label>", "confidence": <0-1>}}\n'
    "Target: {desc}")

_ZOOM_PROMPT = (
    "This image is a zoomed crop with a labeled 4x4 grid (cells numbered "
    "1-16, left to right, top to bottom). Which single cell best centers "
    "on the element described below? Reply ONLY with JSON: "
    '{{"cell": <1-16>, "confidence": <0-1>}}\n'
    "Target: {desc}")

_CROP_PROMPT = (
    "You are a UI grounding model. Which of these candidate crops best "
    "matches: {desc}\nReply ONLY with the crop number (1..{n}) and "
    "confidence, as JSON: \"pick\": <int>, \"confidence\": <float>")


class LlamaCppBackend:
    name = "llama.cpp"

    def __init__(self, model_path: str = "", mmproj_path: str = "",
                 port: int = 8097, n_ctx: int = 2048):
        root = os.path.join(os.path.dirname(__file__), "..", "..")
        self.model_path = model_path or os.path.join(root, _DEFAULT_MODEL)
        self.mmproj_path = mmproj_path or os.path.join(root, _DEFAULT_MMPROJ)
        self.port = port
        self.n_ctx = n_ctx
        self.proc: Optional[subprocess.Popen] = None

    @staticmethod
    def available() -> bool:
        """Cheap probe: llama-server binary + both GGUFs present. Does NOT
        spawn the server (first locate() call warms it)."""
        root = os.path.join(os.path.dirname(__file__), "..", "..")
        return bool(shutil.which("llama-server")) and os.path.exists(
            os.path.join(root, _DEFAULT_MODEL)) and os.path.exists(
            os.path.join(root, _DEFAULT_MMPROJ))

    # ------------------------------------------------------------ server
    def warm(self, timeout: float = 60.0) -> None:
        if self._alive():
            return
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"VLM weights missing: {self.model_path}")
        if not os.path.exists(self.mmproj_path):
            raise FileNotFoundError(f"VLM mmproj missing: {self.mmproj_path}")
        exe = shutil.which("llama-server")
        if not exe:
            raise FileNotFoundError("llama-server not on PATH "
                                    "(brew install llama.cpp)")
        self.proc = subprocess.Popen(
            [exe, "-m", self.model_path, "--mmproj", self.mmproj_path,
             "--host", "127.0.0.1", "--port", str(self.port),
             "-c", str(self.n_ctx), "-ngl", "99"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._alive():
                return
            time.sleep(0.3)
        raise RuntimeError("llama-server did not come up")

    def _alive(self) -> bool:
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/health", timeout=2)
            return True
        except Exception:
            return False

    def shutdown(self) -> None:
        if self.proc:
            self.proc.terminate()
            self.proc = None

    # ------------------------------------------------------------ inference
    def _chat(self, prompt: str, image_path: str = "",
              image_paths: Optional[list[str]] = None,
              max_tokens: int = 96) -> str:
        paths = image_paths or ([image_path] if image_path else [])
        content: list[dict] = [{"type": "text", "text": prompt}]
        for p in paths:
            with open(p, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"}})
        body = {"messages": [{"role": "user", "content": content}],
                "temperature": 0.0, "max_tokens": max_tokens,
                "chat_template_kwargs": {"enable_thinking": False}}
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=240) as r:
            out = json.loads(r.read().decode())
        return out["choices"][0]["message"]["content"] or ""

    def locate(self, image_path: str, description: str) -> Optional[Region]:
        """Try the VLM's native bounding-box grounding first (Qwen2-VL
        emits <|box_start|>(x1,y1),(x2,y2)<|box_end|>); fall back to
        labeled-grid grounding for models without box training."""
        self.warm()
        out = self._chat(_BOX_PROMPT.format(desc=description),
                         image_path, max_tokens=96)
        region = _parse_box(out, image_path)
        if region is not None:
            region.source = self.name
            return region
        return self._locate_grid(image_path, description)

    def _locate_grid(self, image_path: str,
                     description: str) -> Optional[Region]:
        """Grid-based grounding: ask which labeled cell holds the target,
        then zoom into that cell with a finer sub-grid. Works for small
        VLMs that answer 'which cell' better than raw coordinates."""
        cols, rows = 8, 6
        grid_path, cells = _grid_overlay(image_path, cols, rows)
        col_names = "-".join(chr(ord("A") + i) for i in range(cols))
        out = self._chat(_LOCATE_PROMPT.format(cols=col_names, rows=rows,
                                               desc=description),
                         grid_path, max_tokens=64)
        cell = _parse_cell(out)
        if cell is None:
            return None
        (x0, y0, x1, y1), conf = cell
        if not (0 <= x0 < x1 <= 1.0 and 0 <= y0 < y1 <= 1.0):
            return None
        # zoom pass: crop the winning cell, overlay a 4x4 sub-grid
        try:
            zoom_path, (zx0, zy0, zw, zh) = _zoom_crop(
                image_path, x0, y0, x1, y1)
            out2 = self._chat(_ZOOM_PROMPT.format(desc=description),
                              zoom_path, max_tokens=64)
            sub = _parse_subcell(out2)
            if sub is not None:
                (sx0, sy0, sx1, sy1), conf2 = sub
                fx0 = zx0 + sx0 * zw
                fy0 = zy0 + sy0 * zh
                fx1 = zx0 + sx1 * zw
                fy1 = zy0 + sy1 * zh
                x0, y0, x1, y1 = fx0, fy0, fx1, fy1
                conf = 0.4 * conf + 0.6 * conf2
        except Exception:
            pass
        return Region(x=(x0 + x1) / 2, y=(y0 + y1) / 2,
                      confidence=min(conf, 1.0), source=self.name)

    def best_of(self, image_path: str, crops: list[str],
                description: str) -> tuple[int, float]:
        if not crops:
            return -1, 0.0
        self.warm()
        out = self._chat(_CROP_PROMPT.format(desc=description, n=len(crops)),
                         image_paths=crops, max_tokens=64)
        m = __import__("re").search(r'"pick"\s*:\s*(\d+).*?"conf[^"]*"\s*:\s*([0-9.]+)', out)
        if m:
            i = int(m.group(1)) - 1
            if 0 <= i < len(crops):
                return i, min(float(m.group(2)), 1.0)
        m = __import__("re").search(r'\b(\d+)\b', out)
        if m:
            i = int(m.group(1)) - 1
            if 0 <= i < len(crops):
                return i, 0.5
        return -1, 0.0


_MAX_SIDE = 768  # downscale before encoding — fewer vision tiles, faster


def _downscale(img, max_side: int = _MAX_SIDE):
    w, h = img.size
    m = max(w, h)
    if m <= max_side:
        return img
    s = max_side / m
    return img.resize((max(int(w * s), 1), max(int(h * s), 1)))


def _grid_overlay(image_path: str, cols: int, rows: int,
                  subgrid: bool = False) -> tuple[str, list]:
    """Draw a labeled grid over the image. Returns (path, cells) where each
    cell is (label, (x0,y0,x1,y1)) in normalized coordinates."""
    from PIL import Image, ImageDraw
    img = _downscale(Image.open(image_path).convert("RGB"))
    W, H = img.size
    d = ImageDraw.Draw(img)
    cells = []
    for r in range(rows):
        for c in range(cols):
            x0, y0 = c / cols, r / rows
            x1, y1 = (c + 1) / cols, (r + 1) / rows
            label = str(r * cols + c + 1) if subgrid else \
                f"{chr(ord('A') + c)}{r + 1}"
            cells.append((label, (x0, y0, x1, y1)))
            px0, py0 = int(x0 * W), int(y0 * H)
            px1, py1 = int(x1 * W), int(y1 * H)
            d.rectangle([px0, py0, px1, py1], outline=(255, 0, 0), width=2)
            fs = max(14, min(W // cols, H // rows) // 4)
            tx, ty = px0 + 4, py0 + 2
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                d.text((tx + dx, ty + dy), label, fill=(255, 255, 255),
                       font_size=fs)
            d.text((tx, ty), label, fill=(255, 0, 0), font_size=fs)
    out = image_path + ".grid.png"
    img.save(out)
    return out, cells


def _zoom_crop(image_path: str, x0: float, y0: float, x1: float,
               y1: float, pad: float = 0.05):
    """Crop the winning cell (plus padding) and draw a numbered 4x4
    sub-grid. Returns (path, (cx0, cy0, cw, ch)) normalized to original."""
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    W, H = img.size
    cw, chh = (x1 - x0) * (1 + 2 * pad), (y1 - y0) * (1 + 2 * pad)
    cx0 = min(max(x0 - (x1 - x0) * pad, 0.0), 1.0 - cw)
    cy0 = min(max(y0 - (y1 - y0) * pad, 0.0), 1.0 - chh)
    box = (int(cx0 * W), int(cy0 * H),
           int((cx0 + cw) * W), int((cy0 + chh) * H))
    crop = _downscale(img.crop(box), _MAX_SIDE)
    tmp = image_path + ".zoom.png"
    crop.save(tmp)
    grid_path, _ = _grid_overlay(tmp, 4, 4, subgrid=True)
    return grid_path, (cx0, cy0, cw, chh)


def _parse_box(out: str, image_path: str) -> Optional[Region]:
    """Parse a VLM grounding reply via the shared multi-format parser."""
    from PIL import Image
    W, H = Image.open(image_path).size
    return parse_any_box(out, W, H)


def _parse_cell(out: str):
    """Parse {"cell": "B3", "confidence": f} -> ((x0,y0,x1,y1), conf)."""
    import re
    m = re.search(r'"cell"\s*:\s*"?([A-Za-z])\s*(\d+)"?', out)
    if not m:
        m = re.search(r'\b([A-Za-z])(\d+)\b', out)
    if not m:
        return None
    col = ord(m.group(1).upper()) - ord("A")
    row = int(m.group(2)) - 1
    if not (0 <= col < 8 and 0 <= row < 6):
        return None
    cm = re.search(r'"conf[^"]*"\s*:\s*([0-9.]+)', out)
    conf = float(cm.group(1)) if cm else 0.5
    return (col / 8.0, row / 6.0, (col + 1) / 8.0, (row + 1) / 6.0), conf


def _parse_subcell(out: str):
    """Parse {"cell": n} on a 4x4 grid -> ((x0,y0,x1,y1), conf)."""
    import re
    m = re.search(r'"cell"\s*:\s*(\d+)', out)
    if not m:
        m = re.search(r'\b(\d{1,2})\b', out)
    if not m:
        return None
    n = int(m.group(1))
    if not (1 <= n <= 16):
        return None
    n -= 1
    c, r = n % 4, n // 4
    cm = re.search(r'"conf[^"]*"\s*:\s*([0-9.]+)', out)
    conf = float(cm.group(1)) if cm else 0.5
    return (c / 4.0, r / 4.0, (c + 1) / 4.0, (r + 1) / 4.0), conf
