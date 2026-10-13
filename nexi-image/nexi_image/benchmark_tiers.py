"""Reproduce serial real generation, masked editing and seed checks (no download)."""

import argparse
import json
from pathlib import Path

from .tiers import BINARY, TIERS, generate

PROMPT = ("A studio photograph of a red ceramic coffee mug on a wooden table, "
          "soft daylight, a small engraved label reading NEXI")
CACHE = "fresh native process; warm files after verification; serial inference"


def mask_changes(before: Path, after: Path, mask: Path) -> dict:
    from PIL import Image, ImageChops
    with Image.open(before) as source, Image.open(after) as result, Image.open(mask) as selection:
        if source.size != result.size or source.size != selection.size:
            raise ValueError("Comparison images/mask must have equal dimensions")
        channels = ImageChops.difference(source.convert("RGB"), result.convert("RGB")).split()
        changed = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
        changed = changed.point(lambda value: 255 if value else 0)
        outside = selection.convert("L").point(lambda value: 0 if value else 255)
        inside = selection.convert("L").point(lambda value: 255 if value else 0)
        return {"zero_mask_pixels": outside.histogram()[255],
                "changed_zero_mask_pixels": ImageChops.multiply(changed, outside).histogram()[255],
                "changed_selected_pixels": ImageChops.multiply(changed, inside).histogram()[255]}


def benchmark(tier: str, models: str, binary: str, output: Path, threads: int,
              repeat: bool = True) -> dict:
    from PIL import Image, ImageDraw
    output.mkdir(parents=True, exist_ok=True)
    source, edit, selection = (output / f"{tier}-{part}.png" for part in ("generate", "edit", "mask"))
    original = generate(tier, PROMPT, source, models=models, binary=binary, threads=threads, cache_state=CACHE)
    w, h = original["config"]["width"], original["config"]["height"]
    mask = Image.new("L", (w, h))
    ImageDraw.Draw(mask).rectangle((w // 8, h // 8, 7 * w // 8, 7 * h // 8), fill=255)
    mask.save(selection)
    prompt = ("Change the red mug to blue ceramic. Preserve its shape, label, table and lighting."
              if tier == "best" else "A studio photograph of a blue ceramic coffee mug on a wooden table, soft daylight")
    edited = generate(tier, prompt, edit, models=models, binary=binary, threads=threads,
                      image=source, mask=selection, strength=None if tier == "best" else
                      (1.0 if tier == "medium" else .8), cache_state=CACHE)
    checks = mask_changes(source, edit, selection)
    if checks["changed_zero_mask_pixels"] or not checks["changed_selected_pixels"]:
        raise RuntimeError(f"Mask preservation/edit change check failed: {checks}")
    summary = {"tier": tier, "generation_report": str(source.with_suffix(".json")),
               "editing_report": str(edit.with_suffix(".json")), "mask_check": checks,
               "generation_fits_ram_target": original["fits_ram_target_conservative"],
               "editing_fits_ram_target": edited["fits_ram_target_conservative"]}
    if repeat:
        second = generate(tier, PROMPT, output / f"{tier}-repeat.png", models=models, binary=binary,
                          threads=threads, cache_state=CACHE)
        summary["seed_pixels_identical"] = original["output_rgb_sha256"] == second["output_rgb_sha256"]
        if not summary["seed_pixels_identical"]:
            raise RuntimeError(f"Seed pixel repeat check failed for {tier}")
    (output / f"{tier}-checks.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tiers", nargs="+", choices=TIERS, default=list(TIERS))
    parser.add_argument("--models", default="models/tiers")
    parser.add_argument("--binary", default=str(BINARY))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/tier-benchmark"))
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--skip-repeat", action="store_true")
    args = parser.parse_args()
    for tier in args.tiers:
        print(json.dumps(benchmark(tier, args.models, args.binary, args.output_dir, args.threads,
                                   repeat=not args.skip_repeat), indent=2), flush=True)


if __name__ == "__main__":
    main()
