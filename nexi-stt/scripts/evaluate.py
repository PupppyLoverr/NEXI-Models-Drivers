"""Evaluate local PCM16 WAV/reference JSONL with a warmed offline dictation driver."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import resource
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from nexi_stt.audio import read_wav
from nexi_stt.benchmark import hardware
from nexi_stt.engine import Driver
from nexi_stt.metrics import word_error_rate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--profile", choices=("fast", "balanced"), default="fast")
    args = parser.parse_args()
    driver = Driver(args.model, threads=args.threads)
    rows = [json.loads(line) for line in args.data.read_text().splitlines() if line.strip()]
    if not rows:
        parser.error("Evaluation dataset must not be empty")
    records = []
    negative_count = false_positives = 0
    for row in rows:
        path = Path(row["wav"])
        path = path if path.is_absolute() else args.data.parent / path
        audio = read_wav(path)
        result = driver.transcribe(audio, profile=args.profile)
        kind = row.get("kind", "speech")
        if kind not in ("speech", "non_speech") or (kind == "non_speech" and row["text"]):
            raise ValueError("Rows must be speech or non_speech with an empty reference")
        quality = word_error_rate(row["text"], result["text"]) if kind == "speech" else None
        if kind == "non_speech":
            negative_count += 1
            false_positives += bool(result["text"].strip())
        records.append(
            {
                "wav": row["wav"],
                "wav_sha256": hashlib.sha256(audio).hexdigest(),
                "speaker_id": row.get("speaker_id"),
                "kind": kind,
                "reference": row["text"],
                "hypothesis": result["text"],
                "quality": quality,
                "audio_seconds": result["audio_seconds"],
                "transcribe_seconds": result["transcribe_seconds"],
            }
        )
    errors = sum(row["quality"]["word_errors"] for row in records if row["quality"])
    reference_words = sum(row["quality"]["reference_words"] for row in records if row["quality"])
    if not reference_words:
        raise ValueError("Evaluation requires at least one nonempty speech reference")
    times = sorted(row["transcribe_seconds"] for row in records)
    durations = sum(row["audio_seconds"] for row in records)
    report = {
        "schema_version": 2,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "hardware": hardware(),
        "manifest_sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "threads": args.threads,
        "profile": args.profile,
        "model": {k: v for k, v in driver.metadata.items() if k != "files"},
        "model_load_seconds": driver.load_seconds,
        "model_disk_bytes": sum(p.stat().st_size for p in args.model.rglob("*") if p.is_file()),
        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if sys.platform == "darwin" else 1024),
        "timing_definition": "One freshly loaded process; first clip is cold-call, subsequent "
        "clips reuse the model; times exclude model load. Serial runs, OS cache not flushed.",
        "audio_seconds": durations,
        "median_transcribe_seconds": statistics.median(times),
        "p95_transcribe_seconds_nearest_rank": times[math.ceil(0.95 * len(times)) - 1],
        "total_transcribe_seconds": sum(times),
        "total_real_time_factor": sum(times) / durations,
        "speech_clips": len(records) - negative_count,
        "non_speech_clips": negative_count,
        "non_speech_false_positives": false_positives,
        "word_errors": errors,
        "reference_words": reference_words,
        "corpus_wer": errors / reference_words,
        "records": records,
        "warning": "Read-speech subsets cannot establish a dictation/ASR category ranking; "
        "check upstream pretraining overlap. Controls are artificial, not real room noise.",
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Corpus WER: {errors}/{reference_words} = {errors / reference_words:.4%}")


if __name__ == "__main__":
    main()
