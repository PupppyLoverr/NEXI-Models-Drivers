from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .assets import catalog, download
from .audio import read_wav
from .engine import Driver
from .server import serve


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Local-only English CPU dictation from PCM16 WAV")
    commands = root.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("download", help="Explicit network access; checksummed assets")
    fetch.add_argument("--preset", choices=sorted(catalog()), required=True)
    fetch.add_argument("--destination", type=Path, required=True)
    for name in ("transcribe", "serve"):
        command = commands.add_parser(name)
        command.add_argument("--model", type=Path, required=True, help="Local CT2 directory only")
        command.add_argument("--threads", type=int, default=4)
        if name == "transcribe":
            command.add_argument("wav", type=Path)
            command.add_argument("--format", choices=("json", "text", "timestamps"), default="json")
            command.add_argument("--output", type=Path)
            command.add_argument(
                "--hotwords", default="", help="Soft vocabulary bias, not a guarantee"
            )
            command.add_argument("--words", action="store_true")
            command.add_argument("--no-vad", action="store_true")
        else:
            command.add_argument("--port", type=int, default=8767)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "download":
            download(args.preset, args.destination)
            print(f"Verified assets: {args.destination}")
            return 0
        if args.command == "serve":
            serve(Driver(args.model, threads=args.threads), args.port)
            return 0
        audio = read_wav(args.wav)
        driver = Driver(args.model, threads=args.threads)
        result = driver.transcribe(
            audio,
            hotwords=args.hotwords,
            word_timestamps=args.words,
            vad=not args.no_vad,
        )
        result["model_load_seconds"] = driver.load_seconds
        if args.format == "text":
            output = result["text"] + "\n"
        elif args.format == "timestamps":
            output = (
                "\n".join(
                    f"[{row['start']:.2f} → {row['end']:.2f}] {row['text']}"
                    for row in result["segments"]
                )
                + "\n"
            )
        else:
            output = json.dumps(result, indent=2) + "\n"
        if args.output:
            args.output.write_text(output)
        else:
            print(output, end="")
        return 0
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"nexi-stt: {exc}", file=sys.stderr)
        return 2
