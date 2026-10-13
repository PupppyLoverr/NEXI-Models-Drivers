from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .assets import FILES, REPOSITORY, REVISION, default_model_dir, download, verify_assets


def main() -> None:
    parser = argparse.ArgumentParser(description="Pinned offline Kitten nano-int8 CPU TTS")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("download", "verify", "speak", "serve"):
        sub = commands.add_parser(name)
        sub.add_argument("--model-dir", type=Path, default=default_model_dir())
        if name in ("speak", "serve"):
            sub.add_argument("--threads", type=int, default=2)
        if name == "speak":
            text_group = sub.add_mutually_exclusive_group(required=True)
            text_group.add_argument("--text")
            text_group.add_argument("--text-file", type=Path)
            sub.add_argument("--output", type=Path, required=True)
            sub.add_argument("--voice", default="Jasper")
            sub.add_argument("--language", default="en")
            sub.add_argument("--speed", type=float, default=1.0)
        if name == "serve":
            sub.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        if args.command == "download":
            download(args.model_dir)
        if args.command in ("verify", "download"):
            config = verify_assets(args.model_dir)
            print(
                json.dumps(
                    {
                        "repository": REPOSITORY,
                        "revision": REVISION,
                        "disk_bytes": sum(s for s, _ in FILES.values()),
                        "voices": config["voice_aliases"],
                        "model_dir": str(args.model_dir),
                    }
                )
            )
        elif args.command == "speak":
            from .driver import SAMPLE_RATE, Synthesizer

            start = time.perf_counter()
            synth = Synthesizer(args.model_dir, args.threads)
            loaded = time.perf_counter()
            text = (
                args.text if args.text is not None else args.text_file.read_text(encoding="utf-8")
            )
            samples = synth.to_file(text, args.output, args.voice, args.language, args.speed)
            elapsed = time.perf_counter() - loaded
            print(
                json.dumps(
                    {
                        "output": str(args.output),
                        "sample_rate": SAMPLE_RATE,
                        "audio_seconds": samples / SAMPLE_RATE,
                        "load_seconds": loaded - start,
                        "synthesis_seconds": elapsed,
                        "real_time_factor": elapsed / (samples / SAMPLE_RATE),
                    }
                )
            )
        elif args.command == "serve":
            from .server import serve

            serve(args.model_dir, args.threads, args.port)
    except (ValueError, OSError, RuntimeError) as error:
        print(f"nexi-tts: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
