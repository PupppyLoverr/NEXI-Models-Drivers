"""Weight downloads for NEXI-CUA.

The semantic policy (NEXI-CUA-1, ~6.3MB) ships in the repo. The vision
escalation model is downloaded on demand — this is the ONLY part with a
network dependency, and only at setup time, never at runtime.

  python -m nexi_cua.cli download-weights        # llama.cpp GGUFs
  python -m nexi_cua.cli download-weights --mlx  # note for Apple Silicon
"""
from __future__ import annotations

import os
import urllib.request

GGUFS = {
    # Qwen2-VL-2B-Instruct (bartowski GGUF): vision encoder + language model
    "weights/vision/qwen2-vl-2b-q4_k_m.gguf":
        "https://huggingface.co/bartowski/Qwen2-VL-2B-Instruct-GGUF/"
        "resolve/main/Qwen2-VL-2B-Instruct-Q4_K_M.gguf",
    "weights/vision/mmproj-qwen2-vl-2b-f16.gguf":
        "https://huggingface.co/bartowski/Qwen2-VL-2B-Instruct-GGUF/"
        "resolve/main/mmproj-Qwen2-VL-2B-Instruct-f16.gguf",
    # SmolVLM2-500M — tiny alternative backend
    "weights/vision/SmolVLM2-500M-Q8_0.gguf":
        "https://huggingface.co/ggml-org/SmolVLM2-500M-Video-Instruct-GGUF/"
        "resolve/main/SmolVLM2-500M-Video-Instruct-Q8_0.gguf",
    "weights/vision/mmproj-SmolVLM2-500M-Q8_0.gguf":
        "https://huggingface.co/ggml-org/SmolVLM2-500M-Video-Instruct-GGUF/"
        "resolve/main/mmproj-SmolVLM2-500M-Video-Instruct-F16.gguf",
}

_MLX_NOTE = """\
On Apple Silicon the fastest path is MLX — no files needed here; the model
downloads itself from the HF hub on first use:
  pip install mlx-vlm
  # uses mlx-community/Qwen2-VL-2B-Instruct-4bit automatically
"""


def _fetch(url: str, dest: str) -> None:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total:
                print(f"\r  {os.path.basename(dest)}: "
                      f"{got * 100 // total}%", end="", flush=True)
    os.replace(tmp, dest)
    print(f"\r  {os.path.basename(dest)}: done")


def download(root: str, only_smolv: bool = False) -> None:
    for rel, url in GGUFS.items():
        if only_smolv and "SmolVLM" not in rel:
            continue
        dest = os.path.join(root, rel)
        if os.path.exists(dest):
            print(f"  {rel}: already present")
            continue
        print(f"  {rel}")
        _fetch(url, dest)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser("nexi-cua download-weights")
    ap.add_argument("--root", default=os.path.join(
        os.path.dirname(__file__), ".."))
    ap.add_argument("--smolvlm", action="store_true",
                    help="only the ~545MB SmolVLM2 files")
    ap.add_argument("--mlx", action="store_true",
                    help="print the Apple-Silicon MLX setup note")
    args = ap.parse_args(argv)
    if args.mlx:
        print(_MLX_NOTE)
        return 0
    download(args.root, only_smolv=args.smolvlm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
