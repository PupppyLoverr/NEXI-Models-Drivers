"""Full-parameter Whisper supervised fine-tuning from local consented WAV/text pairs."""

from __future__ import annotations

import argparse
import json
import os
import random
import resource
import sys
import time
from pathlib import Path

from nexi_stt.assets import digest, verify
from nexi_stt.audio import inspect_wav, read_wav
from nexi_stt.engine import offline_environment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True, help="Local HF Whisper directory")
    parser.add_argument("--data", type=Path, required=True, help="JSONL: wav path + text")
    parser.add_argument("--config", type=Path, default=Path("training-config.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, help="Override config for an optimization smoke")
    args = parser.parse_args()
    offline_environment()
    import torch
    from faster_whisper.audio import decode_audio
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    config = json.loads(args.config.read_text())
    steps = args.steps if args.steps is not None else config["steps"]
    accumulation = config["gradient_accumulation"]
    if not 1 <= steps <= 100000 or not 1 <= accumulation <= 128:
        parser.error("steps must be 1–100000, gradient_accumulation 1–128")
    if not 1 <= config["threads"] <= 64 or not 0 < config["learning_rate"] < 1:
        parser.error("Invalid threads/learning_rate")
    if args.output.exists():
        parser.error("Output already exists; refusing to overwrite a checkpoint")
    base_manifest = json.loads((args.base / "nexi-assets.json").read_text())
    verify(args.base, base_manifest["files"])
    rows = [json.loads(line) for line in args.data.read_text().splitlines() if line.strip()]
    if not rows:
        parser.error("Training dataset must not be empty")
    for row in rows:
        path = Path(row["wav"])
        row["wav"] = str(path if path.is_absolute() else args.data.parent / path)
        info = inspect_wav(read_wav(Path(row["wav"])))
        if info.seconds > 30 or not isinstance(row["text"], str) or not row["text"].strip():
            parser.error("Training rows require >0–30 second PCM16 WAV and nonempty text")
    random.seed(config["seed"])
    torch.manual_seed(config["seed"])
    torch.set_num_threads(config["threads"])
    start = time.perf_counter()
    processor = WhisperProcessor.from_pretrained(str(args.base), local_files_only=True)
    model = WhisperForConditionalGeneration.from_pretrained(
        str(args.base),
        local_files_only=True,
        use_safetensors=True,
    ).to("cpu")
    model.config.use_cache = False
    if config["freeze_encoder"]:
        model.freeze_encoder()
    if config["gradient_checkpointing"]:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.train()
    optimizer = torch.optim.AdamW(
        (parameter for parameter in model.parameters() if parameter.requires_grad),
        lr=config["learning_rate"],
    )
    losses = []
    optimizer.zero_grad(set_to_none=True)
    for step in range(steps):
        step_loss = 0.0
        for micro in range(accumulation):
            row = rows[(step * accumulation + micro) % len(rows)]
            waveform = decode_audio(row["wav"], sampling_rate=16000)
            features = processor.feature_extractor(
                waveform,
                sampling_rate=16000,
                return_tensors="pt",
            ).input_features
            labels = processor.tokenizer(row["text"], return_tensors="pt").input_ids
            if labels.shape[1] > model.config.max_target_positions:
                raise ValueError("Transcript exceeds Whisper target token limit")
            if labels[0, 0].item() == model.config.decoder_start_token_id:
                labels = labels[:, 1:]
            loss = model(input_features=features, labels=labels).loss
            if not torch.isfinite(loss).item():
                raise RuntimeError("Nonfinite training loss; checkpoint not saved")
            step_loss += loss.detach().item() / accumulation
            (loss / accumulation).backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        losses.append(step_loss)
        print(json.dumps({"step": step + 1, "loss": step_loss}), flush=True)
    args.output.mkdir(parents=True)
    model.save_pretrained(args.output, safe_serialization=True)
    processor.save_pretrained(args.output)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report = {
        "base": {key: value for key, value in base_manifest.items() if key != "files"},
        "config": {**config, "steps": steps},
        "examples": len(rows),
        "losses": losses,
        "training_and_save_seconds": time.perf_counter() - start,
        "peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "platform": sys.platform,
        "python": sys.version,
        "torch": torch.__version__,
        "cpu_threads": torch.get_num_threads(),
        "device": "cpu",
        "dtype": "float32",
        "checkpoint_sha256": digest(args.output / "model.safetensors"),
        "data_sha256": digest(args.data),
        "warning": "Training loss is not accuracy. No held-out evaluation or quality claim.",
    }
    (args.output / "training-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    main()
