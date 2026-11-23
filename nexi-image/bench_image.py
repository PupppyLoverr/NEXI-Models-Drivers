"""nexi-image bench: measured CPU generation (wall s/img, peak RSS via outer
measure wrapper). Honest scope: 256px, few steps — a latency/footprint floor,
not a quality claim. Quality vs other local models needs a human/preference
eval, recorded as open work.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from nexi_image import engine as eng_mod

PROMPTS = [
    "a red apple on a wooden table, studio lighting",
    "a small robot reading a book in a library",
    "a mountain lake at sunrise, photograph",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="bk-sdm")
    ap.add_argument("--steps", type=int, default=15)
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    t0 = time.perf_counter()
    eng = eng_mod.load_engine(a.engine)
    load_s = time.perf_counter() - t0

    times = []
    for i, p in enumerate(PROMPTS[:a.n]):
        t = time.perf_counter()
        img = eng.generate(p, steps=a.steps, size=a.size, seed=7 + i)
        dt = time.perf_counter() - t
        times.append(dt)
        img.save(f"nexi-image/results/bench_{i}.png")
        print(f"[{i}] {dt:.1f}s - {p[:50]}")

    out = {"engine": a.engine, "size": a.size, "steps": a.steps,
           "load_s": round(load_s, 1),
           "s_per_img_mean": round(sum(times) / len(times), 1),
           "s_per_img": [round(t, 1) for t in times]}
    print(json.dumps(out))
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
