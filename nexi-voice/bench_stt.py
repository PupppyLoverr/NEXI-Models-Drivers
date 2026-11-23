"""Benchmark STT: WER on a pinned LibriSpeech slice + RTF + peak RSS.

    python -m common.bench.measure --json results/stt_fw_tiny_outer.json -- \
        .venv/bin/python nexi-voice/bench_stt.py --engine fw-tiny --n 40
"""
import argparse
import io
import json
import re
import time
import wave
from pathlib import Path


def norm(t: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]", " ", t.lower()).split()


def wer(ref: str, hyp: str) -> float:
    r, h = norm(ref), norm(hyp)
    if not r:
        return 0.0
    # Levenshtein on words
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        nd = [i] + [0] * len(h)
        for j, hw in enumerate(h, 1):
            nd[j] = min(d[j] + 1, nd[j - 1] + 1,
                        d[j - 1] + (rw != hw))
        d = nd
    return d[-1] / len(r)


def libri_slice(n: int):
    """Pinned LibriSpeech slice read straight from the parquet (no datasets
    audio decoding — torchcodec/av are fragile on CPU-only torch builds)."""
    import pandas as pd
    import soundfile as sf
    from huggingface_hub import hf_hub_download
    pq = hf_hub_download("hf-internal-testing/librispeech_asr_demo",
                         "clean/validation-00000-of-00001.parquet",
                         repo_type="dataset")
    df = pd.read_parquet(pq)
    rows = []
    for _, row in df.head(n).iterrows():
        arr, sr = sf.read(io.BytesIO(row["audio"]["bytes"]))
        rows.append({"text": row["text"], "audio": {"array": arr,
                                                  "sampling_rate": sr}})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="fw-tiny")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from nexi_voice import stt as stt_mod

    rows = libri_slice(a.n)
    t0 = time.time()
    eng = stt_mod.load_engine(a.engine)
    load_s = time.time() - t0

    wers, rtfs = [], []
    for row in rows:
        audio = row["audio"]
        buf = io.BytesIO()
        import soundfile as sf
        sf.write(buf, audio["array"], audio["sampling_rate"], format="WAV")
        t0 = time.time()
        parts = eng.transcribe_wav_bytes(buf.getvalue())
        wall = time.time() - t0
        hyp = " ".join(parts)
        wers.append(wer(row["text"], hyp))
        rtfs.append(wall / (len(audio["array"]) / audio["sampling_rate"]))
    out = {"engine": a.engine, "n": len(rows), "load_s": round(load_s, 2),
           "wer_mean": round(sum(wers) / len(wers), 4),
           "rtf_mean": round(sum(rtfs) / len(rtfs), 3),
           "rtf_p90": round(sorted(rtfs)[int(len(rtfs) * 0.9) - 1], 3)}
    print(json.dumps(out))
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
