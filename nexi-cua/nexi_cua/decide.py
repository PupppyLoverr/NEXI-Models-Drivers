"""Decision layer: NEXI-S1 scorer over element candidates.

Falls back to a pure heuristic scorer when no trained S1 weights are present,
so the driver is functional out of the box — the heuristic is honest about
being a string-overlap baseline, and the bench reports which scorer ran.
"""
from __future__ import annotations

import os
import re


def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


class HeuristicDecider:
    """String-overlap baseline. No learned weights."""
    name = "heuristic-v0"

    def decide(self, goal: str, cands: list[dict]) -> dict:
        g = set(_tok(goal))
        scored = []
        for i, c in enumerate(cands):
            t = set(_tok(c["action"] + " " + c["label"]))
            s = len(g & t) / max(1, len(g | t))
            scored.append((i, s))
        scored.sort(key=lambda x: -x[1])
        ranking = [i for i, _ in scored]
        best, best_s = (scored[0] if scored else (-1, 0.0))
        abstained = best_s < 0.15 or best < 0
        return {"choice": best if not abstained else -1,
                "score": best_s, "abstained": abstained,
                "ranking": ranking,
                "candidate": None if abstained else cands[best]}


class S1Decider:
    """Trained NEXI-S1 weights (nexi-s1/s1_v1.pt)."""
    name = "nexi-s1"

    def __init__(self, weights: str):
        import sys
        import torch
        root = os.path.join(os.path.dirname(__file__), "..", "..")
        sys.path.insert(0, os.path.join(root, "nexi-s1"))
        from s1.model import S1  # noqa: E402
        self._m = S1()
        ckpt = torch.load(weights, map_location="cpu", weights_only=True)
        self._m.load_state_dict(ckpt.get("weights", ckpt))
        self._m.eval()

    def decide(self, goal: str, cands: list[dict]) -> dict:
        d = self._m.decide(goal, cands)
        probs = d["probs"][:len(cands)]
        ranking = sorted(range(len(cands)), key=lambda i: -probs[i])
        out = {"choice": d["choice"], "score": max(probs, default=0.0),
               "abstain_prob": d["abstain_prob"],
               "abstained": d["abstained"], "ranking": ranking}
        out["candidate"] = None if d["abstained"] or d["choice"] < 0 \
            else cands[d["choice"]]
        if not d["abstained"] and d["choice"] < 0:
            out["abstained"] = True
        return out


def load_decider(weights: str | None = None):
    if weights and os.path.exists(weights):
        return S1Decider(weights)
    return HeuristicDecider()
