#!/usr/bin/env python3
"""Render per-tier benchmark summaries from existing result JSON files."""

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TIERS = ("nexi-4gb", "nexi-8gb", "nexi-16gb", "nexi-24gb")
METHOD = (
    "Measured locally: CPU-only (8 vCPU, no GPU), llama.cpp b11580, Q4_K_M GGUF "
    "(24gb: UD-Q4_K_XL base GGUF + LoRA at load time), temperature 0, seed 2026, "
    "thinking disabled. Base and tuned use the same GGUF export path and the same item subset."
)

EVAL_ROWS = (
    ("Tool-call exact match", ("tool", "acc"), ("tool", "n")),
    ("CUA action accuracy", ("cua", "acc"), ("cua", "n")),
    ("CUA abstain accuracy", ("cua", "abstain_acc"), ("cua", "abstain_n")),
    ("HumanEval+ base pass@1", ("humaneval", "base_pass@1"), ("humaneval", "limit")),
    ("HumanEval+ plus pass@1", ("humaneval", "plus_pass@1"), ("humaneval", "limit")),
    ("IFEval prompt-level strict", ("ifeval", "prompt_level_strict_acc"), ("ifeval", "limit")),
    ("IFEval instruction-level strict", ("ifeval", "inst_level_strict_acc"), ("ifeval", "limit")),
)


def load_json(path):
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def nested(data, keys):
    value = data
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def raw(value):
    return "not run" if value is None else str(value)


def percent(value):
    return "not run" if not is_number(value) else f"{value * 100:.1f}%"


def score_delta(base, tuned):
    if not is_number(base) or not is_number(tuned):
        return "not run"
    return f"{(tuned - base) * 100:+.1f} pp"


def format_n(value):
    return "not run" if value is None else str(value)


def paired_n(base, tuned, tuned_eval_present):
    if not tuned_eval_present:
        return format_n(base)
    if base == tuned and base is not None:
        return format_n(base)
    if base is None and tuned is None:
        return "not run"
    return f"{format_n(base)}/{format_n(tuned)}"


def format_bytes(value):
    return "not run" if not is_number(value) else f"{int(value):,} B"


def format_gb(value):
    return "not run" if not is_number(value) else f"{value:.3f} GB"


def format_tps(value):
    return "not run" if not is_number(value) else f"{value:.3f} tok/s"


def format_kb(value):
    return "not run" if not is_number(value) else f"{int(value):,} KB"


def read_tier(tier):
    results = ROOT / tier / "results"
    return {
        "footprint": load_json(results / "footprint.json"),
        "base": load_json(results / "eval_base.json"),
        "tuned": load_json(results / "eval_tuned.json"),
        "training": load_json(results / "train_summary.json"),
        "release": load_json(results / "release.json"),
    }


def release_line(release):
    if release is None:
        return "Release decision pending tuned eval."
    ships = raw(release.get("ships"))
    reason = raw(release.get("reason"))
    return f"Release status: ships `{ships}`; reason: {reason}."


def eval_table(data):
    lines = [
        "| Metric | n | Base | NEXI tuned | Δ |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, score_path, n_path in EVAL_ROWS:
        base = nested(data["base"], ("tasks",) + score_path)
        tuned = nested(data["tuned"], ("tasks",) + score_path)
        base_n = nested(data["base"], ("tasks",) + n_path)
        tuned_n = nested(data["tuned"], ("tasks",) + n_path)
        lines.append(
            f"| {label} | {paired_n(base_n, tuned_n, data['tuned'] is not None)} | {percent(base)} | "
            f"{percent(tuned)} | {score_delta(base, tuned)} |"
        )
    return lines


def footprint_heading(footprint):
    model = raw(nested(footprint, ("gguf_file",)))
    ctx = raw(nested(footprint, ("ctx",)))
    return f"## Footprint (llama-bench / llama-cli on the shipped base GGUF `{model}`, ctx {ctx})"


def footprint_table(data):
    footprint = data["footprint"]
    base = data["base"]
    tuned = data["tuned"]
    rows = (
        ("GGUF file size", format_bytes(nested(footprint, ("gguf_bytes",)))),
        ("Context", raw(nested(footprint, ("ctx",)))),
        ("Peak RSS", format_gb(nested(footprint, ("peak_rss_gb",)))),
        ("Prompt tok/s", format_tps(nested(footprint, ("pp512_tps",)))),
        ("Generation tok/s", format_tps(nested(footprint, ("tg128_tps",)))),
        ("Base eval server peak RSS (ctx 4096)", format_kb(nested(base, ("server_peak_rss_kb",)))),
        ("Tuned eval server peak RSS (ctx 4096)", format_kb(nested(tuned, ("server_peak_rss_kb",)))),
    )
    lines = ["| Metric | Value |", "|---|---:|"]
    lines.extend(f"| {label} | {value} |" for label, value in rows)
    return lines


def first_value(data, keys):
    if not isinstance(data, dict):
        return None
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def loss_values(summary):
    history = summary.get("log_history") if isinstance(summary, dict) else None
    losses = [
        entry["loss"]
        for entry in (history or [])
        if isinstance(entry, dict) and is_number(entry.get("loss"))
    ]
    if not losses:
        return None, None
    return losses[0], losses[-1]


def training_list(summary):
    first_loss, last_loss = loss_values(summary)
    rows = (
        ("Steps", first_value(summary, ("steps", "optimizer_steps"))),
        ("Global step", first_value(summary, ("global_step",))),
        ("Examples", first_value(summary, ("examples", "examples_seen"))),
        ("Examples available", first_value(summary, ("examples_available",))),
        ("Sequence length", first_value(summary, ("seq",))),
        ("Wall seconds", first_value(summary, ("wall_seconds", "wall_s"))),
        ("First loss", first_loss),
        ("Last loss", last_loss),
    )
    return [f"- {label}: {raw(value)}" for label, value in rows]


def training_section(summary):
    if summary is None:
        return ["Training run in progress."]
    return training_list(summary)


def across_tiers_table(all_data):
    labels = ("Tool", "CUA", "HumanEval+ plus", "IFEval prompt-strict")
    specs = (
        (("tool", "acc"), ("tool", "n")),
        (("cua", "acc"), ("cua", "n")),
        (("humaneval", "plus_pass@1"), ("humaneval", "limit")),
        (("ifeval", "prompt_level_strict_acc"), ("ifeval", "limit")),
    )
    lines = ["| Metric | " + " | ".join(TIERS) + " |", "|---|" + "---:|" * len(TIERS)]
    for label, (score_path, n_path) in zip(labels, specs):
        cells = []
        for tier in TIERS:
            data = all_data[tier]
            source = data["tuned"] if nested(data["release"], ("ships",)) == "tuned" else data["base"]
            score = nested(source, ("tasks",) + score_path)
            count = nested(source, ("tasks",) + n_path)
            if not is_number(score):
                cells.append("not run")
            else:
                cells.append(f"{percent(score)} (n={format_n(count)})")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return lines


def vendor_references(tier):
    if tier == "nexi-24gb":
        return [
            "- Qwen3.8-27B SWE-bench Pro 61.7%, GPQA Diamond 89.2%, source "
            "https://huggingface.co/Qwen/Qwen3.8-27B"
        ]
    if tier == "nexi-16gb":
        return [
            "- Gemma 4 12B LiveCodeBench v6 72.0%, GPQA Diamond 78.8%, source "
            "https://ai.google.dev/gemma/docs/core/model_card_4"
        ]
    if tier == "nexi-8gb":
        return [
            "- No vendor numbers are reproduced here; see the "
            "[base model card](https://huggingface.co/Qwen/Qwen3.5-4B)."
        ]
    return [
        "- No vendor numbers are reproduced here; see the "
        "[base model card](https://huggingface.co/Qwen/Qwen3.5-2B)."
    ]


def render(tier, all_data):
    data = all_data[tier]
    display_tier = tier.removeprefix("nexi-").upper()
    lines = [
        f"# NEXI {display_tier} Benchmarks",
        "",
        release_line(data["release"]),
        "",
        METHOD,
        "",
        "## Held-out evals[^eval-metrics]",
        "",
        *eval_table(data),
        "",
        "[^eval-metrics]: The subsets are small. Tool-call exact match is canonicalized name+arguments equal to the "
        "reference. CUA action accuracy is the chosen candidate index or `NONE` equal to the reference, on the "
        "NEXI-CUA held-out synth set, seed 99991; CUA abstain accuracy is exact-match accuracy on rows whose reference "
        "is `NONE`. HumanEval base pass@1 and HumanEval+ plus pass@1 are the fractions of prompts whose single "
        "generated solution passes, respectively, the original HumanEval tests and the HumanEval+ tests. IFEval "
        "prompt-level strict is the fraction of prompts satisfying all instructions under strict scoring; "
        "instruction-level strict is the fraction of individual instructions satisfied under strict scoring.",
        "",
        footprint_heading(data["footprint"]),
        "",
        *footprint_table(data),
        "",
        "## Training",
        "",
        *training_section(data["training"]),
        "",
        "## Across tiers[^across-tiers]",
        "",
        *across_tiers_table(all_data),
        "",
        "[^across-tiers]: n differs by tier and items are the first N of the same held-out sets.",
        "",
        "## Published reference scores (vendor-reported, not measured by NEXI, full precision, different harnesses)",
        "",
        *vendor_references(tier),
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tier", nargs="*", help="tier folder(s); defaults to all four")
    args = parser.parse_args()
    invalid = [tier for tier in args.tier if tier not in TIERS]
    if invalid:
        parser.error(f"invalid tier(s): {', '.join(invalid)}")
    selected = args.tier or list(TIERS)
    all_data = {tier: read_tier(tier) for tier in TIERS}
    for tier in selected:
        path = ROOT / tier / "BENCHMARKS.md"
        path.write_text(render(tier, all_data), encoding="utf-8")
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
