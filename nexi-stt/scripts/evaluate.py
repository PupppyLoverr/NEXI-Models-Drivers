"""Evaluate local PCM16 WAV/reference JSONL with a warmed offline dictation driver."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nexi_stt.audio import read_wav
from nexi_stt.engine import Driver
from nexi_stt.metrics import word_error_rate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    driver = Driver(args.model, threads=args.threads)
    rows = [json.loads(line) for line in args.data.read_text().splitlines() if line.strip()]
    if not rows:
        parser.error("Evaluation dataset must not be empty")
    records = []
    for row in rows:
        path = Path(row["wav"])
        path = path if path.is_absolute() else args.data.parent / path
        result = driver.transcribe(read_wav(path))
        quality = word_error_rate(row["text"], result["text"])
        records.append(
            {"wav": row["wav"], "reference": row["text"], "result": result, "quality": quality}
        )
    errors = sum(row["quality"]["word_errors"] for row in records)
    reference_words = sum(row["quality"]["reference_words"] for row in records)
    report = {
        "word_errors": errors,
        "reference_words": reference_words,
        "corpus_wer": errors / reference_words,
        "records": records,
        "warning": "Use held-out speakers/audio. Training-set WER is not generalization.",
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Corpus WER: {errors}/{reference_words} = {errors / reference_words:.4%}")


if __name__ == "__main__":
    main()
