"""Map BK's pruned Diffusers U-Net to sd.cpp's sparse SD1 tiny U-Net layout."""

import argparse
from pathlib import Path


def unet_name(name: str) -> str:
    simple = {"time_embedding.linear_1": "time_embed.0",
              "time_embedding.linear_2": "time_embed.2", "conv_in": "input_blocks.0.0",
              "conv_norm_out": "out.0", "conv_out": "out.2"}
    for src, dst in simple.items():
        if name.startswith(src + "."):
            return "model.diffusion_model." + dst + name[len(src):]
    parts = name.split(".")
    if parts[0] not in ("down_blocks", "up_blocks"):
        raise ValueError(f"Unsupported BK tensor: {name}")
    block, layer = int(parts[1]), int(parts[3])
    kind = parts[2]
    if kind in ("resnets", "attentions"):
        index = 3 * block + layer + (1 if parts[0] == "down_blocks" else 0)
        base = f"{'input' if parts[0] == 'down_blocks' else 'output'}_blocks.{index}."
        tail = ".".join(parts[4:])
        if kind == "resnets":
            fields = {"norm1": "in_layers.0", "conv1": "in_layers.2",
                      "norm2": "out_layers.0", "conv2": "out_layers.3",
                      "time_emb_proj": "emb_layers.1", "conv_shortcut": "skip_connection"}
            key, _, rest = tail.partition(".")
            tail = fields[key] + "." + rest
        return "model.diffusion_model." + base + ("0." if kind == "resnets" else "1.") + tail
    if kind == "downsamplers":
        base = f"input_blocks.{3 * (block + 1)}.0.op."
        tail = ".".join(parts[5:])
    elif kind == "upsamplers":
        base = f"output_blocks.{3 * block + 2}.{1 if block == 0 else 2}."
        tail = ".".join(parts[4:])
    else:
        raise ValueError(f"Unsupported BK tensor: {name}")
    return "model.diffusion_model." + base + tail


def convert(root: Path, output: Path) -> None:
    from safetensors.torch import load_file, save_file
    unet = load_file(root / "unet.safetensors")
    clip = load_file(root / "clip.safetensors")
    tensors = {unet_name(k): v.contiguous() for k, v in unet.items()}
    tensors.update({"cond_stage_model.transformer." + k: v.contiguous() for k, v in clip.items()})
    if len(tensors) != len(unet) + len(clip):
        raise ValueError("Tensor-name collision during conversion")
    save_file(tensors, str(output))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    convert(args.root, args.output)
