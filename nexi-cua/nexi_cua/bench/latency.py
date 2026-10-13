"""Real latency + memory benchmark for NEXI-CUA-1.

Measures what the spec asks: cold latency, warm latency, p50/p95/p99, CPU
time, RSS RAM, MPS availability — on this machine, no synthetic claims.
"""
from __future__ import annotations

import gc
import os
import statistics
import sys
import time

import torch

from ..policy.infer import SemanticPolicy
from ..training.synth import generate


def _rss_mb() -> float:
    import resource
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux KiB
    return v / 1e6 if sys.platform == "darwin" else v / 1e3


def _pctl(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    k = max(0, min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1)))))
    return sorted(xs)[k]


def run_bench(n_warm: int = 300, n_cold: int = 3, weights_dir: str = "") -> dict:
    out: dict = {}
    # ---- cold load --------------------------------------------------------
    cold = []
    for _ in range(n_cold):
        gc.collect()
        t0 = time.perf_counter()
        pol = SemanticPolicy(weights_dir=weights_dir)
        cold.append((time.perf_counter() - t0) * 1e3)
    # warm policy in scope for the rest
    policy = pol

    # ---- candidate + featurize + decide ------------------------------------
    samples = generate(n_warm, seed=4242)
    obs_w, dec_w = [], []
    for s in samples:
        t0 = time.perf_counter()
        obs = s.obs
        obs_w.append((time.perf_counter() - t0) * 1e3)
    cpu0 = time.process_time()
    lat = []
    for s in samples:
        t0 = time.perf_counter()
        policy.decide(s.obs, s.obs.goal)
        lat.append((time.perf_counter() - t0) * 1e3)
    cpu_used = time.process_time() - cpu0

    out["device"] = policy.device
    out["model_params"] = policy.model.param_count()
    out["weights_bytes"] = os.path.getsize(
        os.path.join(weights_dir or os.path.join(
            os.path.dirname(__file__), "..", "..", "weights"),
            "nexi-cua-1.pt"))
    out["cold_load_ms"] = {"mean": round(statistics.mean(cold), 2),
                           "min": round(min(cold), 2), "max": round(max(cold), 2)}
    out["decide_warm_ms"] = {
        "mean": round(statistics.mean(lat), 3),
        "p50": round(_pctl(lat, 50), 3),
        "p95": round(_pctl(lat, 95), 3),
        "p99": round(_pctl(lat, 99), 3),
        "min": round(min(lat), 3), "max": round(max(lat), 3),
        "n": len(lat)}
    out["decide_cpu_seconds_total"] = round(cpu_used, 3)
    out["rss_mb_peak"] = round(_rss_mb(), 1)
    if sys.platform == "darwin":
        out["mps_available"] = torch.backends.mps.is_available()
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(run_bench(), indent=2))
