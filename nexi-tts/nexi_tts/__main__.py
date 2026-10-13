from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .assets import PROFILES, default_model_dir, download, profile_for, verify_assets
from .text import CHUNK_CHARS


def main() -> None:
    parser = argparse.ArgumentParser(description="Pinned offline Kitten CPU TTS: tiny or quality")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("download", "verify", "speak", "serve"):
        sub = commands.add_parser(name)
        sub.add_argument("--profile", choices=PROFILES, default="nano")
        sub.add_argument("--model-dir", type=Path)
        if name in ("speak", "serve"):
            sub.add_argument("--threads", type=int, default=2)
            sub.add_argument("--chunk-chars", type=int, default=CHUNK_CHARS)
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
        spec = profile_for(args.profile)
        args.model_dir = args.model_dir or default_model_dir(args.profile)
        if args.command == "download":
            download(args.model_dir, args.profile)
        if args.command in ("verify", "download"):
            config = verify_assets(args.model_dir, args.profile)
            print(
                json.dumps(
                    {
                        "profile": args.profile,
                        "repository": spec.repository,
                        "revision": spec.revision,
                        "disk_bytes": sum(s for s, _ in spec.files.values()),
                        "voices": config["voice_aliases"],
                        "model_dir": str(args.model_dir),
                    }
                )
            )
        elif args.command == "speak":
            from .driver import SAMPLE_RATE, Synthesizer

            start = time.perf_counter()
            synth = Synthesizer(
                args.model_dir, args.threads, profile=args.profile, chunk_chars=args.chunk_chars
            )
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
                        "profile": args.profile,
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

            serve(
                args.model_dir,
                args.threads,
                args.port,
                profile=args.profile,
                chunk_chars=args.chunk_chars,
            )
    except (ValueError, OSError, RuntimeError) as error:
        print(f"nexi-tts: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
